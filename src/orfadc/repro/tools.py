"""Resource-allocation multi-fidelity tool middleware (paper Sec. II-B, Table I).

Four tools, all JSON-in / JSON-out so an LLM (or MCP client) can call them:

  active_sizing          Stage 1  power_ratio_list -> active configurations
  impedance_matching     Stage 2  PSO on the critical stages (Eq. 1)
  band_planning          Stage 3  SA on MCR2/MCR3 with Eq. 3 + calibration (Eq. 2)
  fullchain_evaluation   Stage 4  high-fidelity S-param / NF / P1dB evaluation

The simulator is pluggable (``backend``).  ``SurrogateBackend`` runs anywhere;
a Cadence backend must return the same metric dictionary.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from ..schemas import Spec
from ..tools.cost_functions import stage2_cost, stage3_cost
from . import circuit as ck
from .device import DeviceOP, knowledge_database, op_for_row
from .mcr_eq3 import eq3_voltage
from .optim import pso, simulated_annealing

# Equivalent EDA cost model (seconds) used to report paper-like wall-clock
# numbers; the surrogate itself runs in milliseconds.
EQUIV_COST_S = {"hf_critical": 0.5, "hf_full": 12.0, "lf": 0.002}
# The paper's comparison is sequential ("for controlled comparison, execute reasoning
# sequentially").  Set ORFADC_PARALLEL=1 to credit concurrent simulations instead
# (Searcher fan-out, PSO particles, GA population) up to SimCounter.max_parallel.
PARALLEL = os.environ.get("ORFADC_PARALLEL", "0") == "1"
STAGE2_BOUNDS = {  # Table II, Stage 2
    "k": (0.1, 0.7), "l1_ph": (100, 1000), "l2_ph": (100, 1000), "r1_ohm": (100, 1000),
    "r2_ohm": (100, 1000), "c1_ff": (0, 50), "c2_ff": (0, 50), "ls_ph": (0, 150),
}
NOMINAL_STAGE2_LOAD = (250.0, 0.0)


# ---------------------------------------------------------------------------
# bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class SimCounter:
    hf_critical: int = 0
    hf_full: int = 0
    lf: int = 0
    cpu_s: float = 0.0
    budget_hf: int | None = None
    budget_equiv_s: float | None = None
    parallel: int = 1          # concurrent simulations in the current batch (fan-out x particles)
    max_parallel: int = 64     # licence/CPU cap (paper: 2x64-core EPYC workstation)
    equiv_s: float = 0.0
    hard_stop: str = ""        # set when an external cap (e.g. Spectre calls per design) is reached

    def charge(self, kind: str, n: int = 1) -> None:
        setattr(self, kind, getattr(self, kind) + n)
        self.equiv_s += n * EQUIV_COST_S[kind] / max(min(self.parallel, self.max_parallel), 1)

    def equiv_time_s(self) -> float:
        return self.equiv_s

    @property
    def hf_total(self) -> int:
        return self.hf_critical + self.hf_full

    def exhausted(self) -> bool:
        if self.hard_stop:
            return True
        if self.budget_hf is not None and self.hf_total >= self.budget_hf:
            return True
        return self.budget_equiv_s is not None and self.equiv_time_s() >= self.budget_equiv_s

    def to_dict(self) -> dict:
        return {"hf_critical": self.hf_critical, "hf_full": self.hf_full, "lf": self.lf,
                "hf_total": self.hf_total, "equiv_time_s": round(self.equiv_time_s(), 2),
                "cpu_s": round(self.cpu_s, 3)}


class BudgetExhausted(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    def simulate(self, design: ck.LNADesign, f_hz: np.ndarray, **kw: Any) -> dict: ...


class SurrogateBackend:
    name = "surrogate_twoport_v1"

    def simulate(self, design: ck.LNADesign, f_hz: np.ndarray, **kw: Any) -> dict:
        return ck.simulate(design, f_hz, **kw)


@dataclass
class ToolContext:
    spec: Spec
    backend: Backend = field(default_factory=SurrogateBackend)
    counter: SimCounter = field(default_factory=SimCounter)
    seed: int = 0
    log: list[dict] = field(default_factory=list)

    @property
    def fc_hz(self) -> float:
        return self.spec.fc_ghz * 1e9

    def sim(self, design: ck.LNADesign, f_hz: np.ndarray, kind: str, final: bool = False, **kw: Any) -> dict:
        if self.counter.exhausted():
            raise BudgetExhausted("high-fidelity simulation budget exhausted")
        t = time.perf_counter()
        backend = getattr(self.backend, "final", None) if final else None
        out = (backend or self.backend).simulate(design, f_hz, **kw)
        self.counter.cpu_s += time.perf_counter() - t
        self.counter.charge(kind)
        cap = getattr(backend, "max_calls", None) if backend is not None else None
        if cap and getattr(backend, "n_calls", 0) >= cap:
            self.counter.hard_stop = f"{backend.name}: {cap} calls per design reached"
        return out


# ---------------------------------------------------------------------------
# Stage 1: active sizing & biasing
# ---------------------------------------------------------------------------

def _stage_options(kind: str, target_ma: float, tol: float) -> list[dict]:
    best: dict[float, dict] = {}
    for row in knowledge_database():
        if row["kind"] != kind:
            continue
        err = (target_ma - row["stage_current_ma"]) / target_ma  # never exceed the budget
        if -0.005 <= err <= tol and (row["w_um"] not in best or err < best[row["w_um"]]["_err"]):
            best[row["w_um"]] = dict(row, _err=err)
    return [dict(r, target_current_ma=target_ma) for _, r in sorted(best.items())]


def active_sizing(power_ratio_list: list[float], total_current_ma: float, tol: float = 0.15) -> dict:
    ratios = [float(x) for x in power_ratio_list]
    if len(ratios) != 3 or any(x <= 0 for x in ratios):
        raise ValueError("power_ratio_list must hold three positive ratios")
    tot = sum(ratios)
    ratios = [x / tot for x in ratios]
    targets = [total_current_ma * r for r in ratios]
    opts = [_stage_options("cascode", targets[0], tol),
            _stage_options("diff", targets[1], tol),
            _stage_options("diff", targets[2], tol)]
    missing = [i + 1 for i, o in enumerate(opts) if not o]
    if missing:
        return {"power_ratio_list": ratios, "active_params_dict_list": [],
                "status": "infeasible", "reason": f"no device within +-{tol:.0%} of the current for stage(s) {missing}"}
    configs = []
    for crit in ("large", "small"):
        for noncrit in ("large", "small"):
            pick = (lambda o, sz: o[-1] if sz == "large" else o[0])
            stages = [pick(opts[0], crit), pick(opts[1], crit), pick(opts[2], noncrit)]
            configs.append({
                "config_id": f"crit_{crit}__noncrit_{noncrit}",
                "stages": [{k: v for k, v in s.items() if not k.startswith("_")} for s in stages],
            })
    return {"power_ratio_list": ratios, "stage_currents_ma": targets,
            "active_params_dict_list": configs, "status": "ok",
            "n_feasible_per_stage": [len(o) for o in opts]}


def ops_from_active(active: dict) -> tuple[list[DeviceOP], list[float]]:
    ops = [op_for_row(s) for s in active["stages"]]
    return ops, [float(s["stage_current_ma"]) for s in active["stages"]]


# ---------------------------------------------------------------------------
# Stage 2: impedance matching for the critical stages
# ---------------------------------------------------------------------------

def l_match(zin: complex, w: float, z0: float = 50.0) -> tuple[float, float, bool]:
    """Series Lg at the gate + shunt Lpar at the 50-ohm side (Fig. 3)."""
    r, x = zin.real, zin.imag
    if r <= 0:
        return 1e-12, 1e-9, False
    if r >= z0:  # cannot step up with this topology: fall back to series resonance
        return max(-x, 1e-3) / w, 1e-9, False
    xt = -math.sqrt(z0 * r - r * r)
    xlg = xt - x
    bpar = -xt / (r * r + xt * xt)
    ok = xlg > 0 and bpar > 0
    lg = max(xlg, 1.0) / w
    lpar = 1.0 / (w * bpar) if bpar > 0 else 1e-9
    return lg, lpar, ok


def _critical_design(ops: list[DeviceOP], currents: list[float], x: dict, fc_hz: float,
                     lg: float = 1e-12, lpar: float = 1e-6) -> ck.LNADesign:
    m1 = ck.MCRPhysical(k=x["k"], l1_h=x["l1_ph"] * 1e-12, l2_h=x["l2_ph"] * 1e-12,
                        r1_ohm=x["r1_ohm"], r2_ohm=x["r2_ohm"], c1_f=x["c1_ff"] * 1e-15,
                        c2_f=x["c2_ff"] * 1e-15, f_loss_hz=fc_hz)
    dummy = ck.MCRPhysical(k=0.3, l1_h=200e-12, l2_h=200e-12, r1_ohm=300, r2_ohm=300,
                           c1_f=0.0, c2_f=0.0, f_loss_hz=fc_hz)
    return ck.LNADesign(ops=ops, stage_currents_ma=currents, ls_h=x["ls_ph"] * 1e-12, lg_h=lg,
                        lpar_h=lpar, mcr1=m1, mcr2=dummy, mcr3=dummy, fc_hz=fc_hz)


def evaluate_critical(ctx: ToolContext, active: dict, x: dict) -> dict:
    """Two OCEAN-like runs: (1) without input match -> Zin, (2) with L-match."""
    ops, cur = ops_from_active(active)
    fc = ctx.fc_hz
    w = 2 * math.pi * fc
    d0 = _critical_design(ops, cur, x, fc)
    r0 = ctx.sim(d0, np.array([fc]), "hf_critical", upto="stage2", include_match=False,
                 nominal_load=NOMINAL_STAGE2_LOAD)
    lg, lpar, ok = l_match(complex(r0["zin"][0]), w)
    d1 = _critical_design(ops, cur, x, fc, lg=lg, lpar=lpar)
    r1 = ctx.sim(d1, np.array([fc]), "hf_critical", upto="stage2", include_match=True,
                 nominal_load=NOMINAL_STAGE2_LOAD)
    return {"design": d1, "lg_ph": lg * 1e12, "lpar_ph": lpar * 1e12, "lmatch_ok": ok,
            "nf_db": float(r1["nf_db"][0]), "s11_db": float(r1["s11_db"][0]),
            "gain_cp_db": float(r1["gain_db"][0]), "zin_unmatched": complex(r0["zin"][0])}


def impedance_matching(ctx: ToolContext, active: dict, *, nf_headroom_db: float = 0.2,
                       gain_require_db: float | None = None, n_particles: int = 8,
                       iters: int = 8, seed: int | None = None) -> dict:
    names = list(STAGE2_BOUNDS)
    lb = np.array([STAGE2_BOUNDS[n][0] for n in names], float)
    ub = np.array([STAGE2_BOUNDS[n][1] for n in names], float)
    cache: dict[tuple, dict] = {}

    def cost(vec: np.ndarray) -> float:
        x = dict(zip(names, map(float, vec)))
        res = evaluate_critical(ctx, active, x)
        c = stage2_cost(res["nf_db"], ctx.spec.nf_max_db, res["s11_db"], nf_headroom_db)["cost"]
        if gain_require_db is not None:  # Gain_require: hit the critical-gain target (+-1 dB)
            c += 100.0 * max(0.0, abs(gain_require_db - res["gain_cp_db"]) - 1.0)
        else:
            c -= 0.01 * min(res["gain_cp_db"], 32.0)  # tie-breaker: prefer higher critical gain
        # tie-breaker: prefer NF margin beyond the headroom (saves Refiner loops)
        c -= 0.05 * min(max(ctx.spec.nf_max_db - nf_headroom_db - res["nf_db"], 0.0), 1.5)
        cache[tuple(np.round(vec, 9))] = res | {"x": x}
        return c

    outer = ctx.counter.parallel
    if PARALLEL:
        ctx.counter.parallel = outer * n_particles  # particles of one PSO iteration run concurrently
    try:
        opt = pso(cost, lb, ub, n_particles=n_particles, iters=iters,
                  seed=ctx.seed if seed is None else seed,
                  stop_at=(-0.075 if gain_require_db is not None else -0.01 * 32 - 0.075))
    finally:
        ctx.counter.parallel = outer
    res = cache.get(tuple(np.round(opt.x, 9)))
    if res is None:
        # recompute best (numerical key mismatch)
        res = evaluate_critical(ctx, active, dict(zip(names, map(float, opt.x))))
        res["x"] = dict(zip(names, map(float, opt.x)))
    c2 = stage2_cost(res["nf_db"], ctx.spec.nf_max_db, res["s11_db"], nf_headroom_db)
    # band sweep of the matched critical stages (used by Stage 3 as the
    # "simulated voltage response of the critical performance components")
    f = ck.sweep_grid(ctx.fc_hz, ctx.spec.fbw_ratio)
    band = ctx.sim(res["design"], f, "hf_critical", upto="stage2", include_match=True,
                   nominal_load=NOMINAL_STAGE2_LOAD)
    passive = dict(res["x"]) | {"lg_ph": res["lg_ph"], "lpar_ph": res["lpar_ph"]}
    return {
        "passive_params_cpstages": passive,
        "sim_result_cpstages": {"nf_db": res["nf_db"], "s11_db": res["s11_db"],
                                "gain_cp_db": res["gain_cp_db"], "lmatch_ok": res["lmatch_ok"],
                                "ip1db_cp_dbm": float(band["compression"]["ip1db_dbm"])},
        "stage2_cost": c2,
        "feasible": c2["cost"] == 0.0 and (gain_require_db is None or abs(res["gain_cp_db"] - gain_require_db) <= 1.0),
        "nf_headroom_db": nf_headroom_db, "gain_require_db": gain_require_db,
        "_band": {"f_hz": f.tolist(), "gain_to_g2_db": band["gain_to_g2_db"].tolist()},
    }


# ---------------------------------------------------------------------------
# Stage 3: frequency-bandwidth planning (multi-fidelity)
# ---------------------------------------------------------------------------

def _stage3_bounds(spec: Spec, par2: dict, par3: dict) -> tuple[np.ndarray, np.ndarray]:
    lo_ghz, hi_ghz = spec.band_edges_ghz
    cmin2 = max(par2["c_pri_f"], par2["c_sec_f"]) * 1e15
    cmin3 = max(par3["c_pri_f"], par3["c_sec_f"]) * 1e15
    lb = [0.1, lo_ghz, 0.1, cmin2, 0.1, lo_ghz, 0.1, cmin3]
    ub = [0.8, hi_ghz, 8.0, max(200.0, cmin2 + 1), 0.8, hi_ghz, 8.0, max(200.0, cmin3 + 1)]
    return np.array(lb), np.array(ub)


def _full_design(ops, currents, passive2: dict, mcrv: np.ndarray, fc_hz: float) -> ck.LNADesign:
    par2 = ck.node_parasitics(ops[1], ops[2], None)
    par3 = ck.node_parasitics(ops[2], None, ck.DEFAULT_LOAD)
    k2, f2, q2, c2, k3, f3, q3, c3 = map(float, mcrv)
    m2 = ck.map_mcr(k2, 2 * math.pi * f2 * 1e9, q2, c2 * 1e-15, par2)
    m3 = ck.map_mcr(k3, 2 * math.pi * f3 * 1e9, q3, c3 * 1e-15, par3)
    p = passive2
    m1 = ck.MCRPhysical(k=p["k"], l1_h=p["l1_ph"] * 1e-12, l2_h=p["l2_ph"] * 1e-12, r1_ohm=p["r1_ohm"],
                        r2_ohm=p["r2_ohm"], c1_f=p["c1_ff"] * 1e-15, c2_f=p["c2_ff"] * 1e-15, f_loss_hz=fc_hz)
    return ck.LNADesign(ops=list(ops), stage_currents_ma=list(currents), ls_h=p["ls_ph"] * 1e-12,
                        lg_h=p["lg_ph"] * 1e-12, lpar_h=p["lpar_ph"] * 1e-12, mcr1=m1, mcr2=m2,
                        mcr3=m3, fc_hz=fc_hz)


def _lf_gain(f: np.ndarray, gain_g2: np.ndarray, ops, mcrv: np.ndarray, variant: str,
             half: bool = False) -> tuple[np.ndarray, list[float]]:
    k2, f2, q2, c2, k3, f3, q3, c3 = map(float, mcrv)
    total = gain_g2.copy()
    fc_idx = len(f) // 2
    per_stage = []
    for op, k, f0, q, c in ((ops[1], k2, f2, q2, c2), (ops[2], k3, f3, q3, c3)):
        ro = 1.0 / op.gds_s
        gm50 = op.gm_s * ro / (ro + 50.0)
        cs = op.cdb_f + op.cgd_f * 0.12
        v = eq3_voltage(f, k=k, w0=2 * math.pi * f0 * 1e9, q0=q, c_f=c * 1e-15, gm50_s=gm50,
                        rs_drv_ohm=ro, cs_drv_f=cs, variant=variant, half=half)["gain_db"]
        total = total + v
        per_stage.append(float(v[fc_idx]))
    return total, per_stage


def band_planning(ctx: ToolContext, active: dict, stage2: dict, *, gain_user_db: float | None = None,
                  gain_req_list: list[float] | None = None, calibrate: bool = True, max_rounds: int = 4,
                  sa_iters: int = 500, variant: str = "corrected", half: bool = False,
                  simulation_based: bool = False, x0: list[float] | None = None,
                  seed: int | None = None) -> dict:
    """SA over MCR2/MCR3 (k, w0, Q0, C).  ``simulation_based=True`` replaces the
    Eq.-3 model with a full simulation per SA step (Fig. 5b reference)."""
    gain_user = ctx.spec.gain_db if gain_user_db is None else gain_user_db
    ops, cur = ops_from_active(active)
    par2 = ck.node_parasitics(ops[1], ops[2], None)
    par3 = ck.node_parasitics(ops[2], None, ck.DEFAULT_LOAD)
    lb, ub = _stage3_bounds(ctx.spec, par2, par3)
    lo, hi = ctx.spec.band_edges_ghz
    f_band = np.linspace(lo, hi, 21) * 1e9
    g2 = np.interp(f_band, np.array(stage2["_band"]["f_hz"]), np.array(stage2["_band"]["gain_to_g2_db"]))
    passive2 = stage2["passive_params_cpstages"]
    residual = np.zeros_like(f_band)
    rs = ctx.seed if seed is None else seed
    t0 = time.perf_counter()

    def req_pen(per_stage: list[float]) -> float:
        if not gain_req_list:
            return 0.0
        return sum(max(0.0, abs(g - r) - 1.5) for g, r in zip(per_stage, gain_req_list[1:]))

    def lf_cost(x: np.ndarray) -> float:
        ctx.counter.charge("lf")
        g, per = _lf_gain(f_band, g2, ops, x, variant, half)
        g = g + residual
        return stage3_cost(g.tolist(), gain_user)["cost"] + 1000.0 * req_pen(per) + 0.1 * float(np.ptp(g))

    def hf_eval(x: np.ndarray) -> dict:
        d = _full_design(ops, cur, passive2, x, ctx.fc_hz)
        r = ctx.sim(d, f_band, "hf_full")
        return {"design": d, "gain_db": r["gain_db"], "res": r}

    def hf_cost(x: np.ndarray) -> float:
        g = hf_eval(x)["gain_db"]
        return stage3_cost(g.tolist(), gain_user)["cost"] + 0.1 * float(np.ptp(g))

    rounds = []
    x_best = None if x0 is None else np.clip(np.asarray(x0, float), lb, ub)
    if simulation_based:
        opt = simulated_annealing(hf_cost, lb, ub, iters=sa_iters, seed=rs, stop_at=0.1 * 3.0)
        x_best = opt.x
        hf = hf_eval(x_best)
        rounds.append({"round": 0, "hf_cost": stage3_cost(hf["gain_db"].tolist(), gain_user)["cost"]})
    else:
        for rnd in range(max_rounds if calibrate else 1):
            opt = simulated_annealing(lf_cost, lb, ub, iters=sa_iters, seed=rs + rnd, x0=x_best, stop_at=0.1 * 1)
            x_best = opt.x
            g_lf, per = _lf_gain(f_band, g2, ops, x_best, variant, half)
            hf = hf_eval(x_best)
            hf_c = stage3_cost(hf["gain_db"].tolist(), gain_user)
            rounds.append({"round": rnd, "lf_cost": float(opt.f), "hf_cost": hf_c["cost"],
                           "max_abs_residual_db": float(np.max(np.abs(hf["gain_db"] - (g_lf + residual))))})
            if hf_c["cost"] == 0.0 or not calibrate:
                break
            if rnd > 0 and rounds[-1]["max_abs_residual_db"] < 1e-6:
                break  # calibration converged to an infeasible point
            residual = hf["gain_db"] - g_lf  # multi-fidelity correction
    g_lf, per = _lf_gain(f_band, g2, ops, x_best, variant, half)
    k2, f2, q2, c2, k3, f3, q3, c3 = map(float, x_best)
    design = hf["design"]
    return {
        "passive_params_dict": {"mcr2": {"k": k2, "f0_ghz": f2, "q0": q2, "c_ff": c2},
                                "mcr3": {"k": k3, "f0_ghz": f3, "q0": q3, "c_ff": c3},
                                "mcr2_physical": design.mcr2.to_dict(), "mcr3_physical": design.mcr3.to_dict()},
        "cal_gain_dict": {"f_ghz": (f_band / 1e9).tolist(), "gain_lf_db": g_lf.tolist(),
                          "gain_hf_db": hf["gain_db"].tolist(), "stage_gain_lf_db_at_fc": per,
                          "stage_gain_hf_db_at_fc": hf["res"].get("stage_gain_db_at_fc"),
                          "gain_to_g2_db_at_fc": float(g2[len(g2) // 2])},
        "stage3_cost": stage3_cost(hf["gain_db"].tolist(), gain_user),
        "rounds": rounds, "cpu_s": time.perf_counter() - t0,
        "_design": design, "_x": x_best.tolist(),
    }


# ---------------------------------------------------------------------------
# Stage 4: full-chain evaluation
# ---------------------------------------------------------------------------

def spec_check(m: dict, spec: Spec, s11_max_db: float = -10.0) -> dict:
    v = {
        "gain": max(0.0, abs(spec.gain_db - m["gain_min_db"]) - 3.0),
        "ripple": max(0.0, m["ripple_db"] - 3.0),
        "nf": max(0.0, m["nf_fc_db"] - spec.nf_max_db),
        "ip1db": max(0.0, spec.ip1db_min_dbm - m["ip1db_dbm"]),
        "s11": max(0.0, m["s11_max_inband_db"] - s11_max_db),
        "power": max(0.0, m["power_ma"] - spec.power_ma * 1.001),
    }
    return {"violations": v, "total_violation": float(sum(v.values())),
            "pass": all(x == 0.0 for x in v.values())}


def fullchain_evaluation(ctx: ToolContext, design: ck.LNADesign) -> dict:
    f = ck.sweep_grid(ctx.fc_hz, ctx.spec.fbw_ratio)
    r = ctx.sim(design, f, "hf_full", final=True)  # HybridBackend routes Stage 4 to Cadence
    m = ck.band_metrics(r, ctx.fc_hz, ctx.spec.fbw_ratio)
    m["power_ma"] = design.power_ma
    if r.get("power_ma_measured") is not None:  # Spectre DC operating point (PDK backend): use the measured current
        m["power_ma_planned"] = design.power_ma
        m["power_ma"] = float(r["power_ma_measured"])
    chk = spec_check(m, ctx.spec)
    return {
        "sim_results_dict": m, "spec_check": chk, "pass": chk["pass"],
        "compression_stages": {k: {kk: float(vv) if not isinstance(vv, str) else vv for kk, vv in v.items()}
                               for k, v in r["compression"]["stages"].items()},
        "backend": (getattr(ctx.backend, "final", None) or ctx.backend).name,
        "evidence_source": r.get("source", "surrogate"), "not_silicon_result": True,
        "_sweep": {"f_ghz": (f / 1e9).tolist(), "gain_db": r["gain_db"].tolist(),
                   "s11_db": r["s11_db"].tolist(), "nf_db": r["nf_db"].tolist(),
                   "nfmin_db": r["nfmin_db"].tolist()},
    }
