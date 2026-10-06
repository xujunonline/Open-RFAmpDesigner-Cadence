"""Agent implementation v2 (docs/131): LLM-driven ReAct Manager / Searcher / Refiner.

Every agent runs its own Thought -> Action -> Observation loop (paper Sec. II-C, Fig. 6):
the LLM answers ``<rationale>...</rationale><tools>{"tool": name, "args": {...}}</tools>``,
the tool runs, and the trimmed observation plus the remaining budget go back to the LLM.

* ``ManagerAgent``  -- keeps the candidate queue; tools search_candidates / refine_candidate
                       (each runs a fresh sub-agent), list_candidates, query_memory,
                       load_kb_candidates (mode 2), finish.
* ``SearcherAgent`` -- stateless; tools active_sizing (Stage 1), impedance_matching (Stage 2), finish.
* ``RefinerAgent``  -- stateless; tools band_planning (Stage 3), fullchain_evaluation (Stage 4),
                       impedance_matching (Stage 2 re-run on the same split/config), finish.

Invalid actions come back as an error observation (counted) and the LLM retries.  Repeated
failures, the LLM call cap, transport loss or the EDA budget end the run with a
``terminated_reason``; v2 never substitutes the rule policy for the LLM.

``ScriptedReActTransport`` (offline tests only) replays a script and otherwise answers with each
agent's ``oracle()`` -- the v1 rule policy expressed as v2 actions -- so the protocol, validation
and bookkeeping are exercised without network.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..schemas import Spec
from . import tools as T
from .agents import DesignSession, RefineReport, RulePolicy, _norm_viol, _public, _scale_stage3_x0
from .llm import V2_SPLIT_RANGE, _valid_split, parse_tools
from .memory import MemoryStore

AGENT_IMPL = "v2"
PROMPT_DIR = Path(__file__).with_name("prompts") / "v2"
OBS_MAX_CHARS = 3000
HISTORY_FULL = 6                      # most recent steps sent in full; older ones as one-line summaries
MAX_STEPS = {"manager": 60, "searcher": 24, "refiner": 16}
MAX_CONSECUTIVE_INVALID = 3
MAX_CONSECUTIVE_ERRORS = 3
GLOBAL_STOPS = ("eda_budget", "llm_call_cap", "llm_unavailable")
LLM_MAX_CALLS_DEFAULT = 200


class ActionError(ValueError):
    """An action the agent may not take; returned to the LLM as an error observation."""


# ---------------------------------------------------------------------------
# LLM access and accounting shared by all agents of one design
# ---------------------------------------------------------------------------

@dataclass
class UsageV2:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    notional_cost_usd: float = 0.0
    errors: int = 0
    invalid_actions: int = 0
    latency_s: float = 0.0
    fallbacks: int = 0               # always 0 in v2 (no rule fallback); kept for llm-table/llm-seeds
    rule_after_disable: int = 0      # always 0 in v2
    disabled_reason: str = ""
    calls_by_role: dict = field(default_factory=dict)


class Brain:
    def __init__(self, transport: Any, max_calls: int | None = None) -> None:
        self.transport = transport
        self.usage = UsageV2()
        self.log: list[dict] = []
        self.max_calls = max_calls if max_calls is not None else int(
            os.environ.get("ORFADC_LLM_MAX_CALLS") or LLM_MAX_CALLS_DEFAULT)
        self.stop = ""                   # global stop reason (llm_call_cap / llm_unavailable)
        self._consecutive_errors = 0
        self.rule = RulePolicy()         # used by the scripted oracle only

    @property
    def scripted(self) -> bool:
        return bool(getattr(self.transport, "wants_oracle", False))

    def ask(self, role: str, system: str, user: str, staged: dict | None = None) -> str | None:
        """One LLM call; None when the call failed or a global stop is in force."""
        if self.stop:
            return None
        if self.usage.calls >= self.max_calls:
            self.stop = "llm_call_cap"
            self.usage.disabled_reason = f"max_calls={self.max_calls} reached"
            return None
        if self.scripted:
            self.transport.role, self.transport.pending = role, staged
        t = time.perf_counter()
        try:
            text, u = self.transport.complete(system, user)
        except Exception as exc:  # network/auth/quota: counted, retried by the agent loop, never replaced by rules
            self.usage.errors += 1
            self._consecutive_errors += 1
            self.log.append({"role": role, "error": repr(exc)[:600]})
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.stop = "llm_unavailable"
                self.usage.disabled_reason = f"{self._consecutive_errors} consecutive transport errors; last: {repr(exc)[:300]}"
            return None
        dt = time.perf_counter() - t
        self._consecutive_errors = 0
        u = u or {}
        self.usage.calls += 1
        self.usage.calls_by_role[role] = self.usage.calls_by_role.get(role, 0) + 1
        self.usage.latency_s += dt
        self.usage.prompt_tokens += int(u.get("prompt_tokens", 0))
        self.usage.completion_tokens += int(u.get("completion_tokens", 0))
        self.usage.cached_prompt_tokens += int(u.get("cached_prompt_tokens", 0))
        self.usage.notional_cost_usd += float(u.get("notional_cost_usd", 0.0))
        self.log.append({"role": role, "response": text[-1500:], "prompt_tokens": int(u.get("prompt_tokens", 0)),
                         "completion_tokens": int(u.get("completion_tokens", 0)), "latency_s": round(dt, 3)})
        return text


# ---------------------------------------------------------------------------
# argument validation
# ---------------------------------------------------------------------------

def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _gain(v: Any) -> bool:
    return _num(v) and 0 < v < 45


KINDS: dict[str, tuple[Callable[[Any], bool], str]] = {
    "split": (lambda v: _valid_split(v, V2_SPLIT_RANGE),
              f"3 numbers, each in [{V2_SPLIT_RANGE[0]}, {V2_SPLIT_RANGE[1]}], summing to 1"),
    "headroom": (lambda v: _num(v) and 0 <= v <= 3, "a number in [0, 3] dB"),
    "gain?": (lambda v: v is None or _gain(v), "null or a gain in (0, 45) dB"),
    "gain_list?": (lambda v: v is None or (isinstance(v, list) and len(v) == 3 and all(
        x is None or (_num(x) and -10 <= x <= 40) for x in v)), "null or [g0, g2, g3] in dB (each -10..40 or null)"),
    "targets?": (lambda v: v is None or (isinstance(v, list) and 1 <= len(v) <= 3 and all(x is None or _gain(x) for x in v)),
                 "null or 1-3 critical-gain targets in dB (null = unconstrained)"),
    "id": (lambda v: isinstance(v, str) and bool(v), "an id string"),
    "id?": (lambda v: v is None or (isinstance(v, str) and bool(v)), "null or an id string"),
    "ids": (lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v), "a list of id strings"),
    "text?": (lambda v: v is None or isinstance(v, str), "a short string"),
    "bool": (lambda v: isinstance(v, bool), "true or false"),
    "k": (lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 10, "an integer 1..10"),
}


@dataclass
class ToolSpec:
    fn: Callable[..., dict]
    desc: str
    args: dict[str, tuple[str, bool]]          # name -> (kind, required)

    def signature(self, name: str) -> str:
        a = ", ".join(f"{k}{'' if req else '?'}: {KINDS[kind][1]}" for k, (kind, req) in self.args.items())
        return f"- `{name}`({a}) -- {self.desc}"


def _normalise_split(s: list[float]) -> list[float]:
    tot = float(sum(s))
    return [round(float(x) / tot, 3) for x in s]


def _same_split(a: list[float], b: list[float]) -> bool:
    return all(abs(x - y) < 1e-3 for x, y in zip(a, b))


def _trim(obs: Any) -> str:
    text = json.dumps(_public(obs), default=float, ensure_ascii=False)
    return text if len(text) <= OBS_MAX_CHARS else text[:OBS_MAX_CHARS] + " ...[truncated]"


def _render_action(act: dict) -> str:
    return f"<rationale>rule-derived action (scripted)</rationale><tools>{json.dumps(act)}</tools>"


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

class ReActAgent:
    role = "agent"

    def __init__(self, session: DesignSession, brain: Brain, max_steps: int | None = None) -> None:
        self.s, self.brain = session, brain
        self.max_steps = max_steps or MAX_STEPS[self.role]
        self.history: list[dict] = []
        self.terminated = ""
        self.steps = 0

    # -- to be provided by subclasses --
    def tools(self) -> dict[str, ToolSpec]:
        raise NotImplementedError

    def task(self) -> dict:
        raise NotImplementedError

    def oracle(self) -> dict | None:
        """Next action under the v1 rule policy (ScriptedReActTransport only)."""
        return None

    # -- prompt --
    def system_prompt(self) -> str:
        text = (PROMPT_DIR / f"{self.role}.md").read_text(encoding="utf-8")
        text = text.replace("{SPLIT_LO}", f"{V2_SPLIT_RANGE[0]:g}").replace("{SPLIT_HI}", f"{V2_SPLIT_RANGE[1]:g}")
        tools = "\n".join(spec.signature(n) for n, spec in self.tools().items())
        return (text.rstrip() + "\n\n## Tools\n" + tools + "\n\n## Protocol\n"
                "Answer every turn with exactly ONE action:\n"
                "<rationale>one or two sentences citing the observed numbers</rationale>"
                "<tools>{\"tool\": \"<name>\", \"args\": {...}}</tools>\n"
                "Do not write hidden or step-by-step reasoning. Optional arguments may be omitted. "
                "An invalid action returns {\"error\": ...}; correct it and retry. "
                "Call `finish` when your task is done or cannot be improved.\n")

    def user_message(self) -> str:
        c = self.s.ctx.counter
        budget = {"equiv_eda_s_used": round(c.equiv_time_s(), 1), "equiv_eda_s_budget": c.budget_equiv_s,
                  "llm_calls_left": max(self.brain.max_calls - self.brain.usage.calls, 0),
                  "agent_steps_left": self.max_steps - self.steps}
        lines = ["TASK:", _trim(self.task()), "", "HISTORY (oldest first):"]
        if not self.history:
            lines.append("(none)")
        n_old = max(len(self.history) - HISTORY_FULL, 0)
        for h in self.history[:n_old]:
            lines.append(f"[step {h['step']}] {h['tool']} -> {h['summary']}")
        for h in self.history[n_old:]:
            lines.append(f"[step {h['step']}] action: {json.dumps({'tool': h['tool'], 'args': h['args']}, default=float)}")
            lines.append(f"<observation>{h['obs']}</observation>")
        lines += ["", "BUDGET: " + json.dumps(budget), "", "Choose the next action."]
        return "\n".join(lines)

    # -- validation --
    def validate(self, act: Any) -> tuple[str, dict]:
        if not isinstance(act, dict):
            raise ActionError("no parsable <tools>{\"tool\": ..., \"args\": {...}}</tools> block in the answer")
        name, args = act.get("tool"), act.get("args", {})
        tools = self.tools()
        if name not in tools:
            raise ActionError(f"unknown tool {name!r}; available: {sorted(tools)}")
        if not isinstance(args, dict):
            raise ActionError("'args' must be a JSON object")
        spec = tools[name]
        extra = set(args) - set(spec.args)
        if extra:
            raise ActionError(f"{name}: unknown argument(s) {sorted(extra)}; allowed: {sorted(spec.args)}")
        for k, (kind, req) in spec.args.items():
            if k not in args:
                if req:
                    raise ActionError(f"{name}: missing required argument {k!r}")
                continue
            ok, what = KINDS[kind]
            if not ok(args[k]):
                raise ActionError(f"{name}: {k} must be {what}, got {args[k]!r}")
        return name, args

    # -- loop --
    def _record(self, tool: str, args: dict, obs: dict) -> None:
        o = _trim(obs)
        summary = obs.get("summary") if isinstance(obs, dict) and obs.get("summary") else o[:160]
        self.history.append({"step": self.steps, "tool": tool, "args": _public(args), "obs": o, "summary": summary})
        if self.brain.log:
            self.brain.log[-1].update({"agent_step": self.steps, "tool": tool, "args": _public(args),
                                       "observation": o[:400]})

    def run(self) -> str:
        """Run the loop; returns the terminated_reason."""
        invalid = 0
        system = self.system_prompt()
        while self.steps < self.max_steps:
            if self.s.ctx.counter.exhausted():
                return self._end("eda_budget")
            if self.brain.stop:
                return self._end(self.brain.stop)
            staged = self.oracle() if self.brain.scripted else None
            text = self.brain.ask(self.role, system, self.user_message(), staged)
            if text is None:                        # failed call: the loop retries until the error cap trips
                continue
            self.steps += 1
            try:
                name, args = self.validate(parse_tools(text))
                obs = self.tools()[name].fn(**args)
            except ActionError as exc:
                invalid += 1
                self.brain.usage.invalid_actions += 1
                self._record("invalid", {}, {"error": str(exc)})
                if invalid >= MAX_CONSECUTIVE_INVALID:
                    return self._end("invalid_actions")
                continue
            except T.BudgetExhausted:
                return self._end("eda_budget")
            invalid = 0
            self._record(name, args, obs)
            if self.terminated:
                return self._end(self.terminated)
        return self._end("max_steps")

    def _end(self, reason: str) -> str:
        self.terminated = reason
        self.s.event(self.role, "terminated", reason=reason, steps=self.steps)
        return reason


# ---------------------------------------------------------------------------
# Searcher
# ---------------------------------------------------------------------------

class SearcherAgent(ReActAgent):
    role = "searcher"

    def __init__(self, session: DesignSession, brain: Brain, instruction: dict, tried_before: list[list[float]],
                 splits_log: list[list[float]], per_split: int = 3) -> None:
        super().__init__(session, brain)
        self.instruction, self.tried_before, self.splits_log, self.per_split = instruction, tried_before, splits_log, per_split
        self.sized: dict[tuple, dict] = {}
        self.generated: list[str] = []
        self.returned: list[str] | None = None

    def tools(self) -> dict[str, ToolSpec]:
        return {
            "active_sizing": ToolSpec(self.t_active_sizing, "Stage 1: split the current budget over the three stages -> "
                                      "four extreme active configurations (no simulation cost).",
                                      {"power_ratio_list": ("split", True)}),
            "impedance_matching": ToolSpec(self.t_impedance_matching, "Stage 2: PSO + L-match synthesis of the critical "
                                           "stages for one sized configuration (costs critical-stage simulations); "
                                           "returns a candidate id.",
                                           {"power_ratio_list": ("split", True), "config_id": ("id", True),
                                            "nf_headroom_db": ("headroom", False), "gain_require_db": ("gain?", False)}),
            "finish": ToolSpec(self.t_finish, "Return the candidate ids worth refining, best first.",
                               {"cids": ("ids", True), "note": ("text?", False)}),
        }

    def task(self) -> dict:
        return {"spec": self.s.spec.__dict__, "instruction": self.instruction,
                "splits_tried_in_earlier_searches": self.tried_before,
                "sized_this_search": [list(k) for k in self.sized],
                "candidates_generated": [self.s.candidates[c].brief() for c in self.generated]}

    def t_active_sizing(self, power_ratio_list: list[float]) -> dict:
        split = _normalise_split(power_ratio_list)
        if any(_same_split(split, t) for t in self.tried_before):
            raise ActionError(f"power_ratio_list {split} was already searched; propose a different allocation")
        act = self.s.tool_active_sizing(split)
        self.sized[tuple(split)] = act
        if not any(_same_split(split, t) for t in self.splits_log):
            self.splits_log.append(split)
        self.s.event("searcher", "active_sizing", split=split, status=act["status"], n=len(act["active_params_dict_list"]))
        cfgs = [{"config_id": c["config_id"],
                 "stages": [{k: st.get(k) for k in ("kind", "w_um", "stage_current_ma", "gm_s", "ft_ghz")} for st in c["stages"]]}
                for c in act["active_params_dict_list"]]
        return {"power_ratio_list": split, "status": act["status"], "reason": act.get("reason"), "configs": cfgs,
                "summary": f"{act['status']}: {[c['config_id'] for c in cfgs]}"}

    def t_impedance_matching(self, power_ratio_list: list[float], config_id: str, nf_headroom_db: float = 0.2,
                             gain_require_db: float | None = None) -> dict:
        split = _normalise_split(power_ratio_list)
        key = next((k for k in self.sized if _same_split(list(k), split)), None)
        if key is None:
            raise ActionError("call active_sizing for this power_ratio_list first")
        ids = [c["config_id"] for c in self.sized[key]["active_params_dict_list"]]
        if config_id not in ids:
            raise ActionError(f"config_id {config_id!r} not in {ids}")
        r = self.s.tool_impedance_matching(list(key), config_id, nf_headroom_db, gain_require_db)
        self.generated.append(r["cid"])
        cand = self.s.candidates[r["cid"]]
        cand.score = self.brain.rule.score(self.s.spec, cand)
        self.s.event("searcher", "impedance_matching", **r)
        return {**cand.brief(), "summary": f"{r['cid']} nf_cp={cand.brief()['nf_cp_db']} "
                                           f"gain_cp={cand.brief()['gain_cp_db']} feasible={cand.brief()['stage2_feasible']}"}

    def t_finish(self, cids: list[str], note: str | None = None) -> dict:
        bad = [c for c in cids if c not in self.generated]
        if bad:
            raise ActionError(f"unknown candidate ids {bad}; generated in this search: {self.generated}")
        self.returned = list(dict.fromkeys(cids))
        self.terminated = "finish"
        return {"returned": self.returned, "summary": f"returned {self.returned}"}

    def result(self) -> list[str]:
        return self.returned if self.returned is not None else list(self.generated)

    def oracle(self) -> dict | None:
        split = self.instruction.get("power_ratio_list")
        if not self.sized:
            if split is None:
                split = self.brain.rule.next_split(self.s.spec, self.tried_before, None)
            return {"tool": "active_sizing", "args": {"power_ratio_list": split}}
        key = next(iter(self.sized))
        targets = self.instruction.get("gain_cp_targets") or [None]
        head = self.instruction.get("nf_headroom_db", 0.2)
        done = {(self.s.candidates[c].active["config_id"], self.s.candidates[c].gain_require_db) for c in self.generated}
        for cfg in self.sized[key]["active_params_dict_list"]:
            for g in targets:
                if (cfg["config_id"], g) not in done:
                    return {"tool": "impedance_matching", "args": {"power_ratio_list": list(key), "config_id": cfg["config_id"],
                                                                  "nf_headroom_db": head, "gain_require_db": g}}
        best = sorted(self.generated, key=lambda c: -self.s.candidates[c].score)[: self.per_split]
        return {"tool": "finish", "args": {"cids": best}}


# ---------------------------------------------------------------------------
# Refiner
# ---------------------------------------------------------------------------

class RefinerAgent(ReActAgent):
    role = "refiner"

    def __init__(self, session: DesignSession, brain: Brain, cid: str, note: str | None = None,
                 report_best: bool = False) -> None:
        super().__init__(session, brain)
        self.cid0 = self.cid = cid
        self.note = note
        self.report_best = report_best
        self.gain_user: float | None = None
        self.gain_req_list: list | None = None
        self.seed_off = 0
        self.pending: dict | None = None             # last band_planning output not yet evaluated
        self.evals: list[tuple[dict, dict]] = []      # (stage3 obs, fullchain obs)
        self.mine: set[str] = set()
        self.report: RefineReport | None = None
        self._stage2_infeasible = False

    def tools(self) -> dict[str, ToolSpec]:
        return {
            "band_planning": ToolSpec(self.t_band_planning, "Stage 3: plan MCR2/MCR3 for the current candidate "
                                      "(Eq. 3 + multi-fidelity calibration); returns a design id (did).",
                                      {"gain_user_db": ("gain?", False), "gain_req_list": ("gain_list?", False)}),
            "fullchain_evaluation": ToolSpec(self.t_fullchain, "Stage 4: high-fidelity full-chain evaluation of a design "
                                             "id; returns pass flag, metrics, violations and per-stage compression.",
                                             {"did": ("id", True)}),
            "impedance_matching": ToolSpec(self.t_impedance_matching, "Stage 2 re-run for the current power split and "
                                           "active configuration with a new NF headroom / critical-gain target; the new "
                                           "candidate becomes current.",
                                           {"nf_headroom_db": ("headroom", True), "gain_require_db": ("gain?", False)}),
            "finish": ToolSpec(self.t_finish, "End the refinement with a report (success only for a passing did).",
                               {"success": ("bool", True), "did": ("id?", False), "bottleneck": ("text?", False),
                                "reason": ("text?", False)}),
        }

    def task(self) -> dict:
        c = self.s.candidates[self.cid]
        return {"spec": self.s.spec.__dict__, "candidate_to_refine": self.cid0, "current_candidate": c.brief(),
                "manager_note": self.note, "current_gain_user_db": self.gain_user,
                "current_gain_req_list": self.gain_req_list, "pending_design_not_evaluated": (self.pending or {}).get("did"),
                "evaluations_so_far": len(self.evals)}

    def t_band_planning(self, gain_user_db: float | None = None, gain_req_list: list | None = None) -> dict:
        if gain_user_db is not None:
            self.gain_user = gain_user_db
        if gain_req_list is not None:
            self.gain_req_list = gain_req_list
        s3 = self.s.tool_band_planning(self.cid, gain_user_db=self.gain_user, gain_req_list=self.gain_req_list,
                                       seed_offset=self.seed_off)
        self.seed_off += 1
        self.mine.add(s3["did"])
        self.pending = s3
        self.s.event("refiner", "band_planning", cid=self.cid, did=s3["did"], gain_user_db=self.gain_user,
                     gain_req_list=self.gain_req_list)
        return {**s3, "summary": f"{s3['did']} stage3_cost={s3['stage3_cost']}"}

    def t_fullchain(self, did: str) -> dict:
        if did not in self.mine:
            raise ActionError(f"did {did!r} was not planned in this refinement; designs: {sorted(self.mine)}")
        fc = self.s.tool_fullchain_evaluation(did)
        s3 = self.pending if self.pending and self.pending["did"] == did else {"did": did}
        self.pending = None
        self.evals.append((s3, fc))
        self.s.event("refiner", "evaluate", cid=self.cid, did=did, passed=fc["pass"],
                     violations=fc["violations"], metrics=fc["sim_results_dict"])
        if fc["pass"]:
            self.report = RefineReport(self.cid, True, did, fc["sim_results_dict"], fc["violations"], None, len(self.evals))
            self.terminated = "spec_met"
        viol = {k: v for k, v in fc["violations"].items() if v > 0}
        return {**fc, "stage_gain_hf_db_at_fc": s3.get("stage_gain_hf_db_at_fc"),
                "summary": f"{did} pass={fc['pass']} violations={ {k: round(v, 2) for k, v in viol.items()} }"}

    def t_impedance_matching(self, nf_headroom_db: float, gain_require_db: float | None = None) -> dict:
        old = self.s.candidates[self.cid]
        r = self.s.tool_impedance_matching(old.power_ratio_list, old.active["config_id"], nf_headroom_db,
                                           gain_require_db, origin="refine")
        self.s.event("refiner", "impedance_matching", **r)
        self._stage2_infeasible = not r["stage2_feasible"]
        if r["stage2_feasible"]:
            self.cid = r["cid"]
            self.gain_req_list = None
        return {**r, "became_current": r["stage2_feasible"],
                "summary": f"{r['cid']} feasible={r['stage2_feasible']} nf_cp={r['nf_cp_db']} gain_cp={r['gain_cp_db']}"}

    def t_finish(self, success: bool, did: str | None = None, bottleneck: str | None = None,
                 reason: str | None = None) -> dict:
        ev = {s3fc[1]["did"]: s3fc for s3fc in self.evals}
        if did is not None and did not in ev:
            raise ActionError(f"did {did!r} was not evaluated in this refinement; evaluated: {sorted(ev)}")
        if success and (did is None or not ev[did][1]["pass"]):
            raise ActionError("success=true needs the did of a design whose fullchain_evaluation passed")
        self.report = self._report(did, bottleneck, reason or "")
        self.terminated = "finish"
        return {"report": self.report.to_dict(), "summary": f"finish success={success} did={did}"}

    def _best(self) -> tuple[dict, dict] | None:
        if not self.evals:
            return None
        if self.report_best:
            return min(self.evals, key=lambda e: _norm_viol(e[1]["violations"]))
        return self.evals[-1]

    def _report(self, did: str | None, bottleneck: str | None, reason: str) -> RefineReport:
        ev = {e[1]["did"]: e for e in self.evals}
        pick = ev.get(did) if did else self._best()
        if pick is None:
            bott = bottleneck or ("stage2_infeasible" if self._stage2_infeasible else "budget")
            return RefineReport(self.cid, False, None, None, None, bott, len(self.evals), reason)
        fc = pick[1]
        v = fc["violations"]
        if fc["pass"]:
            return RefineReport(self.cid, True, fc["did"], fc["sim_results_dict"], v, None, len(self.evals), reason)
        if not bottleneck:
            worst = min(fc["compression_stages"], key=lambda k: fc["compression_stages"][k]["ip1db_dbm_if_alone"])
            bottleneck = f"ip1db:{worst}" if v["ip1db"] > 0 else max(v, key=v.get)
        return RefineReport(self.cid, False, fc["did"], fc["sim_results_dict"], v, bottleneck, len(self.evals), reason)

    def result(self) -> RefineReport:
        if self.report is None:              # ended without finish: report what this refinement evaluated
            self.report = self._report(None, None, f"refiner terminated: {self.terminated}")
        return self.report

    def oracle(self) -> dict | None:
        if self.pending is not None:
            return {"tool": "fullchain_evaluation", "args": {"did": self.pending["did"]}}
        if self._stage2_infeasible:
            return {"tool": "finish", "args": {"success": False, "bottleneck": "stage2_infeasible",
                                               "reason": "critical stages cannot meet NF/S11 at the requested gain"}}
        if not self.evals or self._last_was_stage2:
            return {"tool": "band_planning", "args": {}}
        s3, fc = self.evals[-1]
        act = self.brain.rule.refine_action(self.s.spec, self.s.candidates[self.cid], fc,
                                            {"stage_gain_hf_db_at_fc": s3.get("stage_gain_hf_db_at_fc")}, len(self.evals) - 1)
        if act["action"] == "fail" or len(self.evals) >= 6:
            return {"tool": "finish", "args": {"success": False, "did": fc["did"],
                                               "bottleneck": act.get("bottleneck"), "reason": act.get("reason", "")}}
        if act["action"] == "rerun_stage2":
            c = self.s.candidates[self.cid]
            return {"tool": "impedance_matching", "args": {"nf_headroom_db": act.get("nf_headroom_db", c.nf_headroom_db),
                                                           "gain_require_db": act.get("gain_require_db", c.gain_require_db)}}
        args = {}
        if act.get("gain_user_db") is not None:
            args["gain_user_db"] = act["gain_user_db"]
        if act.get("gain_req_list") is not None:
            args["gain_req_list"] = act["gain_req_list"]
        return {"tool": "band_planning", "args": args}

    @property
    def _last_was_stage2(self) -> bool:
        return bool(self.history) and self.history[-1]["tool"] == "impedance_matching"


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ManagerAgent(ReActAgent):
    role = "manager"

    def __init__(self, session: DesignSession, brain: Brain, *, mode: int = 1, pdk: str | None = None,
                 kb_top_k: int = 3) -> None:
        super().__init__(session, brain)
        self.mode, self.pdk, self.kb_top_k = mode, pdk, kb_top_k
        self.queue: list[str] = []
        self.splits: list[list[float]] = []
        self.reports: list[dict] = []
        self.success: RefineReport | None = None
        self.best: RefineReport | None = None
        self.kb_loaded = False
        self.report_best = os.environ.get("ORFADC_REPORT_BEST", "0") == "1"
        self.hints = session.memory.insights(session.spec) if (session.memory is not None and mode == 2) else {}
        self._oracle_splits = brain.rule.initial_splits(session.spec, self.hints)
        self._pruned: list[list[float]] = []
        self._last_bottleneck: str | None = None

    def tools(self) -> dict[str, ToolSpec]:
        t = {
            "search_candidates": ToolSpec(self.t_search, "SEARCHCANDIDATES: run the RFAmpSearcher sub-agent (Stage 1 + "
                                          "Stage 2). Give a power_ratio_list, or omit it to let the Searcher propose one; "
                                          "nf_headroom_db and gain_cp_targets are suggestions for its Stage-2 runs.",
                                          {"power_ratio_list": ("split", False), "nf_headroom_db": ("headroom", False),
                                           "gain_cp_targets": ("targets?", False), "note": ("text?", False)}),
            "refine_candidate": ToolSpec(self.t_refine, "REFINECANDIDATE: run the RFAmpRefiner sub-agent (Stage 3/4 loop) "
                                         "on one queued candidate; returns its summary report.",
                                         {"cid": ("id", True), "note": ("text?", False)}),
            "list_candidates": ToolSpec(self.t_list, "Queued candidates with critical-stage NF / gain / IP1dB / feasibility "
                                        "and the v1 heuristic score (no cost).", {}),
            "query_memory": ToolSpec(self.t_query_memory, "Top-k Knowledge-Base design points and Experience-Base "
                                     "insights for this spec (no cost).", {"k": ("k", False)}),
            "finish": ToolSpec(self.t_finish, "Stop the design and report the best result.", {"summary": ("text?", False)}),
        }
        if self.mode == 2:
            t["load_kb_candidates"] = ToolSpec(self.t_load_kb, "Mode 2: preload the top-k KB design points as candidates "
                                               "(re-synthesises their Stage 2; costs critical-stage simulations).",
                                               {"k": ("k", False)})
        return t

    def task(self) -> dict:
        best = self.best.to_dict() if self.best else None
        return {"spec": self.s.spec.__dict__, "mode": self.mode, "eb_hints": self.hints or None,
                "queue": [self.s.candidates[c].brief() for c in self.queue][:12],
                "splits_tried": self.splits, "refine_reports": [r for r in self.reports][-4:],
                "best_failed_report": best, "kb_loaded": self.kb_loaded}

    # -- tools --
    def t_search(self, power_ratio_list: list[float] | None = None, nf_headroom_db: float = 0.2,
                 gain_cp_targets: list | None = None, note: str | None = None) -> dict:
        if power_ratio_list is not None:
            power_ratio_list = _normalise_split(power_ratio_list)
            if any(_same_split(power_ratio_list, t) for t in self.splits):
                raise ActionError(f"power_ratio_list {power_ratio_list} was already searched")
        self.s.counts["search"] += 1
        instr = {"power_ratio_list": power_ratio_list, "nf_headroom_db": nf_headroom_db,
                 "gain_cp_targets": gain_cp_targets if gain_cp_targets is not None
                 else self.brain.rule.gain_cp_targets(self.s.spec, self.hints), "note": note}
        sub = SearcherAgent(self.s, self.brain, instr, tried_before=list(self.splits), splits_log=self.splits)
        reason = sub.run()
        new = [c for c in sub.result() if c not in self.queue]
        self.queue.extend(new)
        self.s.event("manager", "search_report", terminated=reason, new=new)
        return {"terminated_reason": reason, "new_candidates": [self.s.candidates[c].brief() for c in new],
                "summary": f"searcher {reason}: {len(new)} new candidates {new}"}

    def t_refine(self, cid: str, note: str | None = None) -> dict:
        if cid not in self.s.candidates:
            raise ActionError(f"unknown candidate {cid!r}; queue: {self.queue}")
        if cid in self.queue:
            self.queue.remove(cid)
        self.s.counts["refine"] += 1
        cand = self.s.candidates[cid]
        self.s.event("manager", "refine_candidate", **cand.brief())
        sub = RefinerAgent(self.s, self.brain, cid, note, report_best=self.report_best)
        reason = sub.run()
        rep = sub.result()
        self.s.event("manager", "refine_report", terminated=reason, **rep.to_dict())
        self._remember(rep)
        d = {**rep.to_dict(), "terminated_reason": reason}
        self.reports.append(d)
        self._last_bottleneck = rep.bottleneck
        if rep.success:
            self.success = rep
            self.terminated = "spec_met"
        else:
            key = _norm_viol if self.report_best else (lambda v: sum(v.values()))
            if rep.violations and (self.best is None or key(rep.violations) < key(self.best.violations)):
                self.best = rep
            if rep.bottleneck and (rep.bottleneck.startswith("ip1db:stage") or rep.bottleneck == "power"):
                self._pruned.append(cand.power_ratio_list)
        return {**d, "summary": f"{cid}: success={rep.success} bottleneck={rep.bottleneck} ({reason})"}

    def t_list(self) -> dict:
        return {"queue": [self.s.candidates[c].brief() for c in self.queue], "summary": f"{len(self.queue)} queued"}

    def t_query_memory(self, k: int = 3) -> dict:
        mem = self.s.memory
        if mem is None:
            return {"kb": [], "eb": {"n": 0}, "note": "memory disabled (mode 1 without --memory)", "summary": "no memory"}
        rows = [{"spec": r["spec"].get("id"), "pass": r.get("pass"), "power_ratio_list": r.get("power_ratio_list"),
                 "config_id": r.get("config_id"), "nf_db": r.get("nf_db"), "ip1db_dbm": r.get("ip1db_dbm"),
                 "gain_min_db": r.get("gain_min_db"), "gain_distribution_db": r.get("gain_distribution_db")}
                for r in mem.retrieve(self.s.spec, k=k)]
        return {"kb": rows, "eb": mem.insights(self.s.spec), "summary": f"{len(rows)} KB rows"}

    def t_load_kb(self, k: int = 3) -> dict:
        if self.kb_loaded:
            raise ActionError("KB candidates were already loaded")
        self.kb_loaded = True
        mem, loaded = self.s.memory, []
        for row in (mem.retrieve(self.s.spec, k=k) if mem is not None else []):
            r = self.s.tool_impedance_matching(row["power_ratio_list"], row["config_id"], row.get("nf_headroom_db", 0.2),
                                               row.get("gain_require_db"), origin="kb")
            cand = self.s.candidates[r["cid"]]
            cand.stage3_x0 = _scale_stage3_x0(row.get("stage3_x"), row["spec"], self.s.spec)
            cand.score = self.brain.rule.score(self.s.spec, cand)
            self.queue.append(r["cid"])
            loaded.append(cand.brief())
            self.s.event("manager", "kb_preload", from_spec=row["spec"].get("id"), **r)
        return {"loaded": loaded, "summary": f"{len(loaded)} KB candidates loaded"}

    def t_finish(self, summary: str | None = None) -> dict:
        self.terminated = "finish"
        return {"summary": f"finish: {summary or ''}"[:160]}

    # -- memory (same records as v1 RFAmpManager._remember, plus implementation/PDK labels) --
    def _remember(self, rep: RefineReport) -> None:
        mem = self.s.memory
        if mem is None or rep.did is None or rep.metrics is None:
            return
        cand = self.s.candidates[rep.cid]
        d = self.s.designs[rep.did]
        g = d["stage3"]["cal_gain_dict"]["stage_gain_hf_db_at_fc"]
        comp = d.get("fullchain", {}).get("compression_stages", {})
        ip = [round(comp[k]["ip1db_dbm_if_alone"], 2) for k in ("stage1", "stage2", "stage3")] if comp else None
        labels = {"agent_impl": AGENT_IMPL, "pdk": self.pdk}
        rec = {"pass": rep.success, "power_ratio_list": cand.power_ratio_list, "config_id": cand.active["config_id"],
               "nf_headroom_db": cand.nf_headroom_db, "gain_require_db": cand.gain_require_db,
               "gain_distribution_db": g, "nf1_db": cand.stage2["sim_result_cpstages"]["nf_db"],
               "nf_db": rep.metrics["nf_fc_db"], "ip1_stages_dbm": ip, "ip1db_dbm": rep.metrics["ip1db_dbm"],
               "gain_min_db": rep.metrics["gain_min_db"], "stage2_x": cand.stage2["passive_params_cpstages"],
               "stage3_x": d["stage3"]["_x"], **labels}
        mem.add_design(self.s.spec, rec)
        text = (f"{rec['nf1_db']:.2f} dB NF1 and {g[0] if g else float('nan'):.1f} dB gain1 leads to {rec['nf_db']:.2f} dB NF. "
                f"The headroom was {cand.nf_headroom_db} dB. IP1 per stage {ip} and gains {g} lead to IP1 of {rec['ip1db_dbm']:.1f} dBm.")
        mem.add_experience(self.s.spec, {"pass": rep.success, "text": text, "nf_headroom_db": cand.nf_headroom_db,
                                         "gain_cp_db": cand.stage2["sim_result_cpstages"]["gain_cp_db"],
                                         "power_ratio_list": cand.power_ratio_list, "bottleneck": rep.bottleneck, **labels})

    # -- oracle (scripted transport only) --
    def oracle(self) -> dict | None:
        if self.mode == 2 and not self.kb_loaded and self.s.memory is not None:
            return {"tool": "load_kb_candidates", "args": {"k": self.kb_top_k}}
        live = [c for c in self.queue if self.s.candidates[c].origin == "kb"
                or not any(_same_split(self.s.candidates[c].power_ratio_list, p) for p in self._pruned)]
        if live:
            best = max(live, key=lambda c: self.brain.rule.score(self.s.spec, self.s.candidates[c]))
            return {"tool": "refine_candidate", "args": {"cid": best}}
        while self._oracle_splits:
            split = self._oracle_splits.pop(0)
            if not any(_same_split(split, t) for t in self.splits):
                break
        else:
            split, seen = None, list(self.splits)
            for _ in range(50):          # v1 moves may leave the v2 range (0.1 floor): skip those
                split = self.brain.rule.next_split(self.s.spec, seen, self._last_bottleneck)
                if split is None or _valid_split(split, V2_SPLIT_RANGE):
                    break
                seen.append(split)
                split = None
        if split is None:
            return {"tool": "finish", "args": {"summary": "no further allocation"}}
        return {"tool": "search_candidates", "args": {"power_ratio_list": split,
                                                      "nf_headroom_db": self.brain.rule.nf_headroom(self.s.spec, self.hints),
                                                      "gain_cp_targets": self.brain.rule.gain_cp_targets(self.s.spec, self.hints)}}

    # -- result in the v1 run_design format --
    def result(self) -> dict:
        s = self.s
        final = self.success or self.best
        return {
            "spec": s.spec.id, "seed": s.seed, "mode": self.mode, "policy": None, "success": self.success is not None,
            "report": final.to_dict() if final else None, "sims": s.ctx.counter.to_dict(),
            "n_search": s.counts["search"], "n_refine": s.counts["refine"], "splits_tried": self.splits,
            "design": s.designs[final.did]["design"].summary() if final and final.did else None,
            "sweep": s.designs[final.did]["fullchain"]["_sweep"] if final and final.did and "fullchain" in s.designs[final.did] else None,
            "agent_impl": AGENT_IMPL, "terminated_reason": self.terminated,
        }


# ---------------------------------------------------------------------------
# transports and entry point
# ---------------------------------------------------------------------------

class ScriptedReActTransport:
    """Offline transport.  ``script`` items are consumed first (str = raw answer, dict = action,
    Exception = transport failure, callable(system, user) -> str); when it is empty (or has no entry
    for the calling role when given as {role: [...]}) the agent's rule oracle answers."""

    wants_oracle = True

    def __init__(self, script: list | dict | None = None) -> None:
        self.script = script if isinstance(script, dict) else list(script or [])
        self.role: str = ""
        self.pending: dict | None = None
        self.n_calls = 0

    def _next_scripted(self) -> Any:
        if isinstance(self.script, dict):
            q = self.script.get(self.role) or []
            return q.pop(0) if q else None
        return self.script.pop(0) if self.script else None

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        self.n_calls += 1
        item = self._next_scripted()
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(system, user)
        if item is None:
            if self.pending is None:
                raise RuntimeError(f"scripted transport: no oracle action for {self.role}")
            item = self.pending
        text = _render_action(item) if isinstance(item, dict) else str(item)
        return text, {"prompt_tokens": (len(system) + len(user)) // 4, "completion_tokens": len(text) // 4}


def make_transport(kind: str) -> Any:
    if kind == "scripted":
        return ScriptedReActTransport()
    from . import llm
    if kind == "anthropic":
        return llm.AnthropicTransport()
    if kind == "openai":
        return llm.OpenAICompatTransport()
    if kind == "claude-cli":
        from .llm_cli import ClaudeCLITransport
        return ClaudeCLITransport()
    if kind == "codex-mcp":
        from .llm_cli import CodexMCPTransport
        return CodexMCPTransport()
    raise ValueError(f"agent implementation v2 needs an LLM policy (scripted, claude-cli, codex-mcp, anthropic, "
                     f"openai), got {kind!r}")


def run_design_v2(spec: Spec, seed: int = 0, *, mode: int = 1, memory_dir: Path | None = None,
                  budget_equiv_s: float = 3600.0, transport: Any = None, policy_name: str = "scripted",
                  backend: T.Backend | None = None, pdk: str | None = None, max_calls: int | None = None) -> dict:
    mem = MemoryStore(memory_dir) if memory_dir else None
    session = DesignSession(spec, seed=seed, budget_equiv_s=budget_equiv_s, memory=mem, backend=backend)
    brain = Brain(transport if transport is not None else make_transport(policy_name), max_calls=max_calls)
    mgr = ManagerAgent(session, brain, mode=mode, pdk=pdk)
    session.event("manager", "plan", mode=mode, hints=mgr.hints, policy=policy_name, agent_impl=AGENT_IMPL)
    mgr.run()
    out = mgr.result()
    out["policy"] = policy_name
    out["trace"] = session.trace
    out["backend"] = session.ctx.backend.name
    out["llm_usage"] = brain.usage.__dict__
    out["llm_log"] = brain.log
    out["_session"] = session
    if hasattr(brain.transport, "close"):
        try:
            brain.transport.close()
        except Exception:
            pass
    return out
