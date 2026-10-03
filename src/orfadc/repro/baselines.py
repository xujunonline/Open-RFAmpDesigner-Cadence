"""Baselines of paper Sec. III-A-3 on the same simulator and budget.

* ``ga_vanilla`` / ``bo_vanilla`` -- flat search in an 18-D physical space
  (6 active + Ls/Lg/Lpar + 3x3 MCR variables), one full simulation per point.
* ``ga_subtool`` / ``bo_subtool`` -- tool-enhanced: Stage-1/Stage-2 tools
  synthesise the critical stages; the optimiser searches a reduced 14-D space
  (power split, device extremes, critical-gain target, NF headroom and the
  eight Stage-3 MCR variables).  The paper reports 16-D; our Stage-2 tool
  absorbs two of their variables, so the count differs by design.

All methods minimise the same normalised total spec violation and stop at
the first passing design or when the equivalent-time budget is exhausted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..schemas import Spec
from . import circuit as ck
from . import tools as T
from .device import device_op
from .optim import bayes_opt, genetic

NORM = {"gain": 3.0, "ripple": 3.0, "nf": 1.0, "ip1db": 3.0, "s11": 3.0, "power": 3.0}


def scalar_violation(chk: dict) -> float:
    return float(sum(v / NORM[k] for k, v in chk["violations"].items()))


class _Stop(Exception):
    pass


@dataclass
class Tracker:
    ctx: T.ToolContext
    best: float = math.inf
    best_eval: dict | None = None
    passed: dict | None = None
    n: int = 0
    history: list | None = None

    def __post_init__(self) -> None:
        self.history = []

    def record(self, ev: dict, design: ck.LNADesign) -> float:
        self.n += 1
        v = scalar_violation(ev["spec_check"])
        if v < self.best:
            self.best, self.best_eval = v, ev | {"design": design.summary()}
        self.history.append({"hf_total": self.ctx.counter.hf_total, "equiv_s": self.ctx.counter.equiv_time_s(),
                             "best_violation": self.best})
        if ev["pass"]:
            self.passed = ev | {"design": design.summary()}
            raise _Stop
        return v


# ---------------------------------------------------------------------------
# flat 18-D physical space
# ---------------------------------------------------------------------------

def flat_bounds(spec: Spec) -> tuple[np.ndarray, np.ndarray, list[str]]:
    lo, hi = spec.band_edges_ghz
    names = ["w1", "vb1", "w2", "vb2", "w3", "vb3", "ls_ph", "lg_ph", "lpar_ph",
             "k1", "l1_ph", "r1_ohm", "k2", "f02", "q02", "k3", "f03", "q03"]
    lb = [45, 0.30, 45, 0.30, 45, 0.30, 0, 50, 50, 0.1, 100, 100, 0.1, lo, 0.1, 0.1, lo, 0.1]
    ub = [180, 0.50, 117, 0.50, 117, 0.50, 150, 2000, 2000, 0.8, 1000, 1000, 0.8, hi, 8.0, 0.8, hi, 8.0]
    return np.array(lb, float), np.array(ub, float), names


def flat_design(spec: Spec, x: np.ndarray) -> ck.LNADesign:
    w1, vb1, w2, vb2, w3, vb3, ls, lg, lpar, k1, l1, r1, k2, f02, q02, k3, f03, q03 = map(float, x)
    ops = [device_op("cascode", round(w1, 2), round(vb1, 4)), device_op("diff", round(w2, 2), round(vb2, 4)),
           device_op("diff", round(w3, 2), round(vb3, 4))]
    cur = [ops[0].id_ma, 2 * ops[1].id_ma, 2 * ops[2].id_ma]
    fc = spec.fc_ghz * 1e9
    m1 = ck.MCRPhysical(k=k1, l1_h=l1 * 1e-12, l2_h=l1 * 1e-12, r1_ohm=r1, r2_ohm=r1, c1_f=0.0, c2_f=0.0, f_loss_hz=fc)
    par2 = ck.node_parasitics(ops[1], ops[2], None)
    par3 = ck.node_parasitics(ops[2], None, ck.DEFAULT_LOAD)
    c2 = max(par2["c_pri_f"], par2["c_sec_f"])
    c3 = max(par3["c_pri_f"], par3["c_sec_f"])
    m2 = ck.map_mcr(k2, 2 * math.pi * f02 * 1e9, q02, c2, par2)
    m3 = ck.map_mcr(k3, 2 * math.pi * f03 * 1e9, q03, c3, par3)
    return ck.LNADesign(ops=ops, stage_currents_ma=cur, ls_h=ls * 1e-12, lg_h=lg * 1e-12, lpar_h=lpar * 1e-12,
                        mcr1=m1, mcr2=m2, mcr3=m3, fc_hz=fc)


def run_flat(spec: Spec, seed: int, method: str, budget_equiv_s: float = 3600.0,
             backend: T.Backend | None = None) -> dict:
    ctx = T.ToolContext(spec, backend=backend or T.SurrogateBackend(), seed=seed)
    ctx.counter.budget_equiv_s = budget_equiv_s
    tr = Tracker(ctx)
    lb, ub, _ = flat_bounds(spec)

    def f(x: np.ndarray) -> float:
        d = flat_design(spec, x)
        ev = T.fullchain_evaluation(ctx, d)
        return tr.record(ev, d)

    max_evals = int(budget_equiv_s / T.EQUIV_COST_S["hf_full"]) + 1
    try:
        if method == "ga":
            ctx.counter.parallel = 20 if T.PARALLEL else 1  # GA generation evaluated concurrently if enabled
            genetic(f, lb, ub, pop=20, gens=100000, seed=seed)
        else:
            bayes_opt(f, lb, ub, n_init=12, iters=max_evals - 12, seed=seed)
    except (_Stop, T.BudgetExhausted):
        pass
    return _pack(spec, seed, f"{method}_vanilla", ctx, tr)


# ---------------------------------------------------------------------------
# tool-enhanced 14-D space
# ---------------------------------------------------------------------------

def run_subtool(spec: Spec, seed: int, method: str, budget_equiv_s: float = 3600.0,
                backend: T.Backend | None = None) -> dict:
    ctx = T.ToolContext(spec, backend=backend or T.SurrogateBackend(), seed=seed)
    ctx.counter.budget_equiv_s = budget_equiv_s
    tr = Tracker(ctx)
    lo, hi = spec.band_edges_ghz
    lb = np.array([0.2, 0.2, 0, 0, 6.0, 0.0, 0.1, lo, 0.1, 40, 0.1, lo, 0.1, 40], float)
    ub = np.array([0.6, 0.6, 1, 1, 30.0, 1.5, 0.8, hi, 8.0, 200, 0.8, hi, 8.0, 200], float)
    cache: dict[tuple, tuple] = {}

    def f(x: np.ndarray) -> float:
        a, b = float(x[0]), float(x[1])
        split = [round(a, 2), round(b, 2), round(max(1.0 - a - b, 0.1), 2)]
        crit = "large" if x[2] > 0.5 else "small"
        nonc = "large" if x[3] > 0.5 else "small"
        g_req, head = 3.0 * round(float(x[4]) / 3.0), 0.5 * round(float(x[5]) / 0.5)
        key = (tuple(split), crit, nonc, g_req, head)
        if key not in cache:
            act = T.active_sizing(split, spec.power_ma)
            cfg = next((c for c in act["active_params_dict_list"]
                        if c["config_id"] == f"crit_{crit}__noncrit_{nonc}"), None)
            if cfg is None:
                cache[key] = (None, None)
            else:
                cache[key] = (cfg, T.impedance_matching(ctx, cfg, nf_headroom_db=head, gain_require_db=g_req,
                                                        seed=seed))
        cfg, s2 = cache[key]
        if cfg is None:
            tr.n += 1
            return 50.0
        ops, cur = T.ops_from_active(cfg)
        mcr = np.array(x[6:14], float)
        par2 = ck.node_parasitics(ops[1], ops[2], None)
        par3 = ck.node_parasitics(ops[2], None, ck.DEFAULT_LOAD)
        mcr[3] = max(mcr[3], max(par2["c_pri_f"], par2["c_sec_f"]) * 1e15)
        mcr[7] = max(mcr[7], max(par3["c_pri_f"], par3["c_sec_f"]) * 1e15)
        d = T._full_design(ops, cur, s2["passive_params_cpstages"], mcr, ctx.fc_hz)
        ev = T.fullchain_evaluation(ctx, d)
        return tr.record(ev, d)

    try:
        if method == "ga":
            ctx.counter.parallel = 16 if T.PARALLEL else 1
            genetic(f, lb, ub, pop=16, gens=100000, seed=seed)
        else:
            bayes_opt(f, lb, ub, n_init=10, iters=290, seed=seed)
    except (_Stop, T.BudgetExhausted):
        pass
    return _pack(spec, seed, f"{method}_subtool", ctx, tr)


def _pack(spec: Spec, seed: int, name: str, ctx: T.ToolContext, tr: Tracker) -> dict:
    best = tr.passed or tr.best_eval
    return {
        "spec": spec.id, "seed": seed, "method": name, "success": tr.passed is not None,
        "sims": ctx.counter.to_dict(), "n_evals": tr.n, "best_violation": tr.best,
        "metrics": best["sim_results_dict"] if best else None,
        "violations": best["spec_check"]["violations"] if best else None,
        "design": best["design"] if best else None, "history": tr.history,
        "sweep": best["_sweep"] if best else None,
    }


def run_baseline(name: str, spec: Spec, seed: int, budget_equiv_s: float) -> dict:
    method, kind = name.split("_")
    if kind == "vanilla":
        return run_flat(spec, seed, method, budget_equiv_s)
    return run_subtool(spec, seed, method, budget_equiv_s)
