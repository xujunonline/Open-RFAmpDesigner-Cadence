"""Two-tier multi-agent framework (paper Sec. II-C, Fig. 6).

RFAmpManager  -- keeps the candidate queue S, ranks candidates, schedules
                 SEARCHCANDIDATES / REFINECANDIDATE, escalates to Stage 1.
RFAmpSearcher -- stateless: power split -> 4 active configs x {gain-
                 constrained, unconstrained} Stage-2 syntheses -> dS.
RFAmpRefiner  -- stateless: Stage 3/4 loop with the paper's staged
                 back-tracking policy; returns a design or a summary report.

Decisions are made by a *policy*.  ``RulePolicy`` encodes the expert rules
quoted in the paper and runs offline.  ``orfadc.repro.llm.LLMPolicy`` routes
the same decisions through a ReAct loop on any chat model.
"""
from __future__ import annotations

import os

import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..schemas import Spec
from . import tools as T
from .memory import MemoryStore


def _public(d: Any) -> Any:
    """Strip private '_' keys so tool outputs are JSON/LLM friendly."""
    if isinstance(d, dict):
        return {k: _public(v) for k, v in d.items() if not str(k).startswith("_")}
    if isinstance(d, (list, tuple)):
        return [_public(v) for v in d]
    if isinstance(d, (np.floating, np.integer)):
        return d.item()
    if isinstance(d, float):
        return round(d, 4)
    return d


@dataclass
class Candidate:
    cid: str
    power_ratio_list: list[float]
    active: dict
    stage2: dict
    nf_headroom_db: float
    gain_require_db: float | None
    origin: str = "search"
    stage3_x0: list[float] | None = None
    score: float = 0.0

    def brief(self) -> dict:
        r = self.stage2["sim_result_cpstages"]
        return {"cid": self.cid, "origin": self.origin, "power_ratio_list": [round(x, 3) for x in self.power_ratio_list],
                "config_id": self.active["config_id"], "nf_cp_db": round(r["nf_db"], 3),
                "s11_cp_db": round(r["s11_db"], 2), "gain_cp_db": round(r["gain_cp_db"], 2),
                "ip1db_cp_dbm": round(r["ip1db_cp_dbm"], 2), "stage2_feasible": self.stage2["feasible"],
                "nf_headroom_db": self.nf_headroom_db, "gain_require_db": self.gain_require_db,
                "score": round(self.score, 3)}


@dataclass
class DesignSession:
    """Shared, JSON-callable state for one spec/seed run."""
    spec: Spec
    seed: int = 0
    budget_equiv_s: float | None = 3600.0
    memory: MemoryStore | None = None
    backend: T.Backend | None = None
    candidates: dict[str, Candidate] = field(default_factory=dict)
    designs: dict[str, dict] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"search": 0, "refine": 0})
    _ids: itertools.count = field(default_factory=itertools.count)

    def __post_init__(self) -> None:
        self.ctx = T.ToolContext(self.spec, backend=self.backend or T.SurrogateBackend(), seed=self.seed)
        self.ctx.counter.budget_equiv_s = self.budget_equiv_s
        self.t0 = time.perf_counter()

    def event(self, _agent: str, _event: str, **payload: Any) -> None:
        self.trace.append({"t": round(time.perf_counter() - self.t0, 3), "agent": _agent, "event": _event,
                           "sims": self.ctx.counter.to_dict(), **_public(payload)})

    def new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):03d}"

    # ------------------------- raw tools (Table I) -------------------------
    def tool_active_sizing(self, power_ratio_list: list[float]) -> dict:
        return T.active_sizing(power_ratio_list, self.spec.power_ma)

    def tool_impedance_matching(self, power_ratio_list: list[float], config_id: str, nf_headroom_db: float = 0.2,
                                gain_require_db: float | None = None, x0: dict | None = None,
                                origin: str = "search") -> dict:
        act = self.tool_active_sizing(power_ratio_list)
        cfg = next((c for c in act["active_params_dict_list"] if c["config_id"] == config_id), None)
        if cfg is None:
            return {"error": f"config {config_id} not available for split {power_ratio_list}", "status": act["status"]}
        s2 = T.impedance_matching(self.ctx, cfg, nf_headroom_db=nf_headroom_db, gain_require_db=gain_require_db,
                                  seed=self.seed + len(self.candidates))
        cid = self.new_id("C")
        cand = Candidate(cid, act["power_ratio_list"], cfg, s2, nf_headroom_db, gain_require_db, origin=origin)
        self.candidates[cid] = cand
        return {"cid": cid} | cand.brief()

    def tool_band_planning(self, cid: str, gain_user_db: float | None = None,
                           gain_req_list: list[float] | None = None, seed_offset: int = 0) -> dict:
        cand = self.candidates[cid]
        s3 = T.band_planning(self.ctx, cand.active, cand.stage2, gain_user_db=gain_user_db,
                             gain_req_list=gain_req_list, x0=cand.stage3_x0,
                             seed=self.seed + seed_offset + 97 * len(self.designs))
        did = self.new_id("D")
        self.designs[did] = {"cid": cid, "stage3": s3, "design": s3["_design"]}
        cand.stage3_x0 = s3["_x"]
        return {"did": did, "stage3_cost": s3["stage3_cost"], "rounds": s3["rounds"],
                "stage_gain_hf_db_at_fc": s3["cal_gain_dict"]["stage_gain_hf_db_at_fc"],
                "passive_params_dict": {k: s3["passive_params_dict"][k] for k in ("mcr2", "mcr3")}}

    def tool_fullchain_evaluation(self, did: str) -> dict:
        rec = self.designs[did]
        fc = T.fullchain_evaluation(self.ctx, rec["design"])
        rec["fullchain"] = fc
        cand = self.candidates[rec["cid"]]
        out = {"did": did, "pass": fc["pass"], "sim_results_dict": fc["sim_results_dict"],
               "violations": fc["spec_check"]["violations"], "compression_stages": fc["compression_stages"],
               "nf_cp_db": cand.stage2["sim_result_cpstages"]["nf_db"]}
        return _public(out)

    def budget_left(self) -> bool:
        return not self.ctx.counter.exhausted()


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

class RulePolicy:
    """Deterministic expert policy -- the rules stated in paper Sec. II-B-4/II-C."""

    name = "rule"

    # ---- manager ----
    def initial_splits(self, spec: Spec, hints: dict) -> list[list[float]]:
        """Balanced split first; the output stage governs linearity, so a stage-3-heavy split
        (weak stage 2) is always the second probe, first when IP1dB is demanding."""
        balanced, linear = [0.4, 0.3, 0.3], [0.35, 0.15, 0.5]
        out = [linear, balanced] if spec.ip1db_min_dbm >= -20 else [balanced, linear]
        if hints.get("power_ratio_list"):
            hint = [round(float(x), 3) for x in hints["power_ratio_list"]]
            out = [hint] + [s for s in out if not np.allclose(s, hint, atol=1e-3)]
        return out

    def gain_cp_targets(self, spec: Spec, hints: dict) -> list[float | None]:
        if "gain_cp_db" in hints:
            return [hints["gain_cp_db"], None]
        tgt = spec.gain_db - 8.0 - 0.6 * max(0.0, spec.ip1db_min_dbm + 25.0)
        return [None, round(tgt, 1)]

    def nf_headroom(self, spec: Spec, hints: dict) -> float:
        return float(hints.get("nf_headroom_db", 0.2))

    def score(self, spec: Spec, c: Candidate) -> float:
        r = c.stage2["sim_result_cpstages"]
        nf_margin = spec.nf_max_db - r["nf_db"]
        lin_margin = r["ip1db_cp_dbm"] - (spec.ip1db_min_dbm + 4.0)
        excess_gain = max(0.0, r["gain_cp_db"] - (spec.gain_db - 6.0))
        return (5.0 if c.stage2["feasible"] else 0.0) + min(nf_margin, 1.5) + 0.5 * min(lin_margin, 4.0) \
            - 0.3 * excess_gain + (1.0 if c.origin == "kb" else 0.0)

    def next_split(self, spec: Spec, tried: list[list[float]], bottleneck: str | None) -> list[float] | None:
        """Move current between stages according to the last bottleneck; when every move around
        the latest split was tried, continue from earlier splits (breadth-first)."""
        moves = {"ip1db:stage3": [0.0, -0.05, 0.05], "ip1db:stage2": [-0.05, 0.05, 0.0],
                 "ip1db:stage1": [0.05, -0.05, 0.0], "nf": [0.05, -0.05, 0.0],
                 "gain": [-0.025, 0.05, -0.025], "stage2_infeasible": [0.05, -0.05, 0.0]}
        order = [bottleneck] if bottleneck in moves else []
        order += [m for m in ("ip1db:stage3", "nf", "gain", "ip1db:stage2", "ip1db:stage1") if m not in order]
        anchors = [np.array(t) for t in reversed(tried)] or [np.array([0.4, 0.3, 0.3])]
        for last in anchors:
            for m in order:
                cand = np.round(last + np.array(moves[m]), 3)
                if cand.min() < 0.1:
                    continue
                cand = (cand / cand.sum()).round(3).tolist()
                if not any(np.allclose(cand, t, atol=1e-3) for t in tried):
                    return cand
        return None

    # ---- refiner ----
    def __init__(self) -> None:
        self._tried_req: dict[str, list] = {}

    def _seen(self, cand: "Candidate", req: list) -> bool:
        lst = self._tried_req.setdefault(cand.cid, [])
        for r in lst:
            if len(r) == len(req) and all(
                    (a == b) if isinstance(a, str) or isinstance(b, str) else abs(a - b) <= 0.6
                    for a, b in zip(req, r)):
                return True
        lst.append(req)
        return False

    def refine_action(self, spec: Spec, cand: Candidate, fc: dict, s3: dict, step: int) -> dict:
        v = fc["violations"]
        m = fc["sim_results_dict"]
        comp = fc["compression_stages"]
        g_hf = s3.get("stage_gain_hf_db_at_fc") or [None, None, None]
        g_cp = cand.stage2["sim_result_cpstages"]["gain_cp_db"]
        if v["power"] > 0:
            return {"action": "fail", "bottleneck": "power", "reason": "active configuration exceeds the current budget"}
        if v["ip1db"] > 0:
            worst = min(comp, key=lambda k: comp[k]["ip1db_dbm_if_alone"])
            mech = comp[worst].get("mechanism", "")
            need = v["ip1db"] + 1.0
            if worst != "stage1" and m["gain_min_db"] > spec.gain_db - 1.5 and v["ip1db"] <= 3.0 \
                    and not self._seen(cand, ["gain_user"]):
                # cheapest move: use the +-3 dB gain tolerance -- less total gain, same topology
                return {"action": "rerun_stage3", "gain_user_db": round(spec.gain_db - 2.2, 2),
                        "why": f"IP1dB short by {v['ip1db']:.1f} dB: trade surplus gain for linearity"}
            if worst == "stage1":
                return {"action": "fail", "bottleneck": "ip1db:stage1", "reason": "first stage compresses first"}
            if g_cp > spec.gain_db - 6.0:
                new_req = round(spec.gain_db - 10.0 - 0.5 * v["ip1db"], 1)
                if cand.gain_require_db is None or new_req < cand.gain_require_db - 0.5:
                    return {"action": "rerun_stage2", "gain_require_db": new_req, "nf_headroom_db": cand.nf_headroom_db,
                            "why": f"critical gain {g_cp:.1f} dB leaves no room for later stages: target {new_req} dB"}
            if worst == "stage2":
                new_req = round(max(g_cp - need, 6.0), 1)
                if cand.gain_require_db is not None and new_req >= cand.gain_require_db - 0.2:
                    return {"action": "fail", "bottleneck": "ip1db:stage2", "reason": "critical gain already minimal"}
                return {"action": "rerun_stage2", "gain_require_db": new_req, "nf_headroom_db": cand.nf_headroom_db,
                        "why": f"IP1dB short by {v['ip1db']:.1f} dB, stage 2 compresses first: lower critical gain"}
            # stage 3 is the bottleneck; partition = gain_to_g2 + stage2(+MCR2) + stage3(+MCR3)
            g0 = g_hf[0] if g_hf[0] is not None else g_cp - 10.0
            rest = spec.gain_db + 1.0 - g0
            if mech == "voltage_swing":
                req = [g0, round(rest * 0.6, 1), round(rest * 0.4, 1)]
                why = "stage 3 output swing limits: move gain from stage 3 to stage 2"
            else:
                g2_now = g_hf[1] if g_hf[1] is not None else rest / 2
                g2_new = round(g2_now - need, 1)
                if g2_new < -2.0 and rest - g2_new > 18.0:
                    if cand.gain_require_db is None or g_cp - need >= 10.0:
                        return {"action": "rerun_stage2", "gain_require_db": round(max(g_cp - need, 10.0), 1),
                                "nf_headroom_db": cand.nf_headroom_db,
                                "why": "stage 3 current-limited and stage 2 already low: lower critical gain"}
                    return {"action": "fail", "bottleneck": "ip1db:stage3", "reason": "stage 3 needs more current"}
                req = [g0, g2_new, round(rest - g2_new, 1)]
                why = f"stage 3 {mech}: less gain before stage 3, more gain in its own load"
            if self._seen(cand, req):
                return {"action": "fail", "bottleneck": "ip1db:stage3", "reason": "gain redistribution exhausted"}
            return {"action": "rerun_stage3", "gain_req_list": req, "why": why}
        if v["nf"] > 0.02:
            nf_cp = cand.stage2["sim_result_cpstages"]["nf_db"]
            if m["nf_fc_db"] - nf_cp > 0.6 and g_hf[1] is not None and g_hf[1] < 4.0:
                total = spec.gain_db + 1.0 - g_hf[0]
                g2 = round(max(total * 0.6, 6.0), 1)
                return {"action": "rerun_stage3", "gain_req_list": [g_hf[0], g2, round(total - g2, 1)],
                        "why": "later stages add noise because MCR2 is lossy: require stage-2 gain"}
            headroom = round(cand.nf_headroom_db + 1.2 * v["nf"] + 0.1, 2)
            if headroom > 2.0:
                return {"action": "fail", "bottleneck": "nf", "reason": "NF headroom exhausted"}
            return {"action": "rerun_stage2", "nf_headroom_db": headroom, "gain_require_db": cand.gain_require_db,
                    "why": f"NF short by {v['nf']:.2f} dB: raise headroom to {headroom}"}
        if v["nf"] > 0:
            return {"action": "rerun_stage2", "nf_headroom_db": round(cand.nf_headroom_db + 0.15, 2),
                    "gain_require_db": cand.gain_require_db, "why": "NF marginal"}
        if v["gain"] > 0:
            delta = spec.gain_db - m["gain_min_db"]
            return {"action": "rerun_stage3", "gain_user_db": round(spec.gain_db + 0.6 * delta, 2),
                    "why": f"minimum in-band gain off by {delta:.1f} dB"}
        if v["ripple"] > 0 or v["s11"] > 0:
            if v["s11"] > 0 and step % 2 == 1:
                return {"action": "rerun_stage2", "nf_headroom_db": cand.nf_headroom_db,
                        "gain_require_db": cand.gain_require_db, "why": "in-band S11 too high"}
            return {"action": "rerun_stage3", "why": "ripple/S11: re-plan passband"}
        return {"action": "fail", "bottleneck": "unknown", "reason": "no violation recognised"}


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------

class RFAmpSearcher:
    def __init__(self, session: DesignSession, policy: RulePolicy) -> None:
        self.s, self.p = session, policy

    def search(self, power_ratio_list: list[float], nf_headroom_db: float,
               gain_targets: list[float | None]) -> list[Candidate]:
        s = self.s
        s.counts["search"] += 1
        act = s.tool_active_sizing(power_ratio_list)
        if T.PARALLEL:
            s.ctx.counter.parallel = max(1, len(act["active_params_dict_list"]) * len(gain_targets))
        s.event("searcher", "active_sizing", split=power_ratio_list, status=act["status"],
                n=len(act["active_params_dict_list"]))
        out = []
        for cfg in act["active_params_dict_list"]:
            for g in gain_targets:
                if not s.budget_left():
                    return out
                try:
                    r = s.tool_impedance_matching(power_ratio_list, cfg["config_id"], nf_headroom_db, g)
                except T.BudgetExhausted:
                    s.ctx.counter.parallel = 1
                    return out
                out.append(s.candidates[r["cid"]])
                s.event("searcher", "impedance_matching", **r)
        s.ctx.counter.parallel = 1
        return out


@dataclass
class RefineReport:
    cid: str
    success: bool
    did: str | None
    metrics: dict | None
    violations: dict | None
    bottleneck: str | None
    steps: int
    reason: str = ""

    def to_dict(self) -> dict:
        return _public(self.__dict__)


def _norm_viol(v: dict) -> float:
    from .baselines import NORM
    return float(sum(x / NORM[k] for k, x in v.items()))


class RFAmpRefiner:
    def __init__(self, session: DesignSession, policy: RulePolicy, max_steps: int = 6, report_best: bool = False,
                 backoff: bool = False) -> None:
        self.s, self.p, self.max_steps, self.report_best, self.backoff = session, policy, max_steps, report_best, backoff

    def refine(self, cid: str) -> RefineReport:
        s = self.s
        s.counts["refine"] += 1
        gain_user, gain_req_list, seed_off = None, None, 0
        last = best = None
        for step in range(self.max_steps):
            if not s.budget_left():
                break
            try:
                s3 = s.tool_band_planning(cid, gain_user_db=gain_user, gain_req_list=gain_req_list, seed_offset=seed_off)
                fc = s.tool_fullchain_evaluation(s3["did"])
            except T.BudgetExhausted:
                break
            s.event("refiner", "evaluate", cid=cid, did=s3["did"], passed=fc["pass"],
                    violations=fc["violations"], metrics=fc["sim_results_dict"])
            last = (s3, fc)
            if best is None or _norm_viol(fc["violations"]) < _norm_viol(best[1]["violations"]):
                best = last
            if fc["pass"]:
                return RefineReport(cid, True, s3["did"], fc["sim_results_dict"], fc["violations"], None, step + 1)
            act = self.p.refine_action(s.spec, s.candidates[cid], fc, s3, step)
            s.event("refiner", "decide", cid=cid, **act)
            if act["action"] == "fail":
                return RefineReport(cid, False, s3["did"], fc["sim_results_dict"], fc["violations"],
                                    act.get("bottleneck"), step + 1, act.get("reason", ""))
            if act["action"] == "rerun_stage2":
                old = s.candidates[cid]
                try:
                    r = s.tool_impedance_matching(old.power_ratio_list, old.active["config_id"],
                                                  act.get("nf_headroom_db", old.nf_headroom_db),
                                                  act.get("gain_require_db", old.gain_require_db), origin="refine")
                except T.BudgetExhausted:
                    break
                s.event("refiner", "impedance_matching", **r)
                if not r["stage2_feasible"] and self.backoff:
                    # B21 (docs/124): a too aggressive Stage-2 request is infeasible -> retry halfway between the
                    # old and requested settings; if that also fails keep the old candidate and re-plan Stage 3.
                    g_old = old.stage2["sim_result_cpstages"]["gain_cp_db"]
                    g_new = act.get("gain_require_db", old.gain_require_db)
                    h_new = act.get("nf_headroom_db", old.nf_headroom_db)
                    mid_g = None if g_new is None else round(0.5 * (g_old + g_new), 1)
                    mid_h = round(0.5 * (old.nf_headroom_db + h_new), 3)
                    try:
                        r = s.tool_impedance_matching(old.power_ratio_list, old.active["config_id"], mid_h, mid_g,
                                                      origin="refine")
                    except T.BudgetExhausted:
                        break
                    s.event("refiner", "impedance_matching", backoff=True, **r)
                    if not r["stage2_feasible"]:
                        s.event("refiner", "backoff_keep_candidate", cid=old.cid)
                        seed_off += 1
                        continue
                cid = r["cid"]
                gain_req_list = None
                if not r["stage2_feasible"]:
                    if self.report_best and best is not None:      # keep what this loop already evaluated (B20)
                        b3, bfc = best
                        return RefineReport(cid, False, b3["did"], bfc["sim_results_dict"], bfc["violations"],
                                            "stage2_infeasible", step + 1,
                                            "critical stages cannot meet NF/S11 at the requested gain")
                    return RefineReport(cid, False, None, None, None, "stage2_infeasible", step + 1,
                                        "critical stages cannot meet NF/S11 at the requested gain")
            else:
                gain_user = act.get("gain_user_db", gain_user)
                gain_req_list = act.get("gain_req_list", gain_req_list)
                seed_off += 1
        if last is None:
            return RefineReport(cid, False, None, None, None, "budget", 0, "budget exhausted")
        s3, fc = best if self.report_best else last      # report_best: least normalised violation of this loop
        worst = min(fc["compression_stages"], key=lambda k: fc["compression_stages"][k]["ip1db_dbm_if_alone"])
        v = fc["violations"]
        bott = f"ip1db:{worst}" if v["ip1db"] > 0 else max(v, key=v.get)
        return RefineReport(cid, False, s3["did"], fc["sim_results_dict"], v, bott, self.max_steps,
                            "refine budget exhausted")


class RFAmpManager:
    def __init__(self, session: DesignSession, policy: RulePolicy | None = None, *, mode: int = 1,
                 use_refiner: bool = True, kb_top_k: int = 3, refine_steps: int = 6, per_split: int = 3) -> None:
        self.s = session
        self.p = policy or RulePolicy()
        self.mode = mode
        self.use_refiner = use_refiner
        self.kb_top_k = kb_top_k
        self.per_split = per_split
        self.searcher = RFAmpSearcher(session, self.p)
        # ORFADC_REPORT_BEST=1 (set by `bench design --backend pdk`): a failed run reports its least-violating
        # evaluated design instead of the last one (B20, docs/123 §9); off by default so surrogate tables reproduce.
        self.report_best = os.environ.get("ORFADC_REPORT_BEST", "0") == "1"
        self.backoff = os.environ.get("ORFADC_STAGE2_BACKOFF", "0") == "1"   # B21 (docs/124)
        self.refiner = RFAmpRefiner(session, self.p, max_steps=refine_steps if use_refiner else 1,
                                    report_best=self.report_best, backoff=self.backoff)
        self.queue: list[Candidate] = []

    def _preload_from_kb(self) -> None:
        mem = self.s.memory
        if mem is None:
            return
        for row in mem.retrieve(self.s.spec, k=self.kb_top_k):
            if not self.s.budget_left():
                return
            try:
                r = self.s.tool_impedance_matching(row["power_ratio_list"], row["config_id"],
                                                   row.get("nf_headroom_db", 0.2), row.get("gain_require_db"),
                                                   origin="kb")
            except T.BudgetExhausted:
                return
            cand = self.s.candidates[r["cid"]]
            cand.stage3_x0 = _scale_stage3_x0(row.get("stage3_x"), row["spec"], self.s.spec)
            self.queue.append(cand)
            self.s.event("manager", "kb_preload", from_spec=row["spec"].get("id"), **r)

    def run(self) -> dict:
        s, p = self.s, self.p
        hints = s.memory.insights(s.spec) if (s.memory is not None and self.mode == 2) else {}
        s.event("manager", "plan", mode=self.mode, hints=hints, policy=p.name)
        if self.mode == 2:
            self._preload_from_kb()
        tried: list[list[float]] = []
        pending_splits = p.initial_splits(s.spec, hints)
        bottleneck = None
        best: RefineReport | None = None
        success: RefineReport | None = None
        while s.budget_left():
            if not self.queue:
                split = pending_splits.pop(0) if pending_splits else p.next_split(s.spec, tried, bottleneck)
                if split is None:
                    break
                tried.append(split)
                new = self.searcher.search(split, p.nf_headroom(s.spec, hints), p.gain_cp_targets(s.spec, hints))
                for c in new:
                    c.score = p.score(s.spec, c)
                new.sort(key=lambda c: -c.score)
                self.queue.extend(new[: self.per_split])
                if not new:
                    bottleneck = "power"
                    continue
            for c in self.queue:
                c.score = p.score(s.spec, c)
            self.queue.sort(key=lambda c: -c.score)
            cand = self.queue.pop(0)
            s.event("manager", "refine_candidate", **cand.brief())
            rep = self.refiner.refine(cand.cid)
            s.event("manager", "refine_report", **rep.to_dict())
            self._remember(cand, rep)
            if rep.success:
                success = rep
                break
            key = _norm_viol if self.report_best else (lambda v: sum(v.values()))
            if rep.violations and (best is None or key(rep.violations) < key(best.violations)):
                best = rep
            bottleneck = rep.bottleneck
            # prune: drop queued candidates sharing a split that failed on current allocation
            if bottleneck and (bottleneck.startswith("ip1db:stage") or bottleneck == "power"):
                self.queue = [c for c in self.queue if c.power_ratio_list != cand.power_ratio_list or c.origin == "kb"]
        final = success or best
        return {
            "spec": s.spec.id, "seed": s.seed, "mode": self.mode, "policy": p.name, "success": success is not None,
            "report": final.to_dict() if final else None, "sims": s.ctx.counter.to_dict(),
            "n_search": s.counts["search"], "n_refine": s.counts["refine"], "splits_tried": tried,
            "design": s.designs[final.did]["design"].summary() if final and final.did else None,
            "sweep": s.designs[final.did]["fullchain"]["_sweep"] if final and final.did and "fullchain" in s.designs[final.did] else None,
        }

    def _remember(self, cand: Candidate, rep: RefineReport) -> None:
        mem = self.s.memory
        if mem is None or rep.did is None or rep.metrics is None:
            return
        cand = self.s.candidates[rep.cid]
        d = self.s.designs[rep.did]
        g = d["stage3"]["cal_gain_dict"]["stage_gain_hf_db_at_fc"]
        comp = d.get("fullchain", {}).get("compression_stages", {})
        ip = [round(comp[k]["ip1db_dbm_if_alone"], 2) for k in ("stage1", "stage2", "stage3")] if comp else None
        rec = {"pass": rep.success, "power_ratio_list": cand.power_ratio_list, "config_id": cand.active["config_id"],
               "nf_headroom_db": cand.nf_headroom_db, "gain_require_db": cand.gain_require_db,
               "gain_distribution_db": g, "nf1_db": cand.stage2["sim_result_cpstages"]["nf_db"],
               "nf_db": rep.metrics["nf_fc_db"], "ip1_stages_dbm": ip, "ip1db_dbm": rep.metrics["ip1db_dbm"],
               "gain_min_db": rep.metrics["gain_min_db"], "stage2_x": cand.stage2["passive_params_cpstages"],
               "stage3_x": d["stage3"]["_x"]}
        mem.add_design(self.s.spec, rec)
        text = (f"{rec['nf1_db']:.2f} dB NF1 and {g[0] if g else float('nan'):.1f} dB gain1 leads to {rec['nf_db']:.2f} dB NF. "
                f"The headroom was {cand.nf_headroom_db} dB. IP1 per stage {ip} and gains {g} lead to IP1 of {rec['ip1db_dbm']:.1f} dBm.")
        mem.add_experience(self.s.spec, {"pass": rep.success, "text": text, "nf_headroom_db": cand.nf_headroom_db,
                                         "gain_cp_db": cand.stage2["sim_result_cpstages"]["gain_cp_db"],
                                         "power_ratio_list": cand.power_ratio_list, "bottleneck": rep.bottleneck})


def _scale_stage3_x0(x: list[float] | None, old_spec: dict, new: Spec) -> list[float] | None:
    if not x:
        return None
    x = list(x)
    ratio = new.fc_ghz / float(old_spec["fc_ghz"])
    x[1] *= ratio
    x[5] *= ratio
    return x


def run_design(spec: Spec, seed: int = 0, *, mode: int = 1, memory_dir: Path | None = None,
               budget_equiv_s: float = 3600.0, use_refiner: bool = True, policy: RulePolicy | None = None,
               backend: T.Backend | None = None) -> dict:
    mem = MemoryStore(memory_dir) if memory_dir else None
    session = DesignSession(spec, seed=seed, budget_equiv_s=budget_equiv_s, memory=mem, backend=backend)
    mgr = RFAmpManager(session, policy, mode=mode, use_refiner=use_refiner)
    out = mgr.run()
    out["trace"] = session.trace
    out["backend"] = session.ctx.backend.name
    out["_session"] = session  # in-process only (bench/cadence-check); dropped before JSON dumps
    return out
