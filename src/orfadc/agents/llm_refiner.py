from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from threading import local

from ..schemas import Candidate, Spec
from .llm_searcher import ModelTransport, _SAFE_ID, _reject_constant, _unique_object
from .refiner import Refiner, validated_fullchain_violations


_PROMPT_PATH = Path(__file__).parent / "prompts" / "refiner.md"
_VIOLATION_ACTIONS = (
    ("nf_violation", "retry_stage2"),
    ("s11_violation", "retry_stage2"),
    ("gain_violation", "retry_stage3"),
    ("ip1db_violation", "retry_stage1_or_stage3"),
    ("power_violation", "retry_stage1"),
)


class LLMRefiner(Refiner):
    """Let a model choose a failing stage, never an unverified success state."""

    def __init__(self, transport: ModelTransport, *, timeout_seconds: int = 30) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValueError("model timeout must be an integer in 1..120 seconds")
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self._call_state = local()

    def last_call_id(self) -> str | None:
        return getattr(self._call_state, "call_id", None)

    def refine_from_run(self, candidate: Candidate, run_dir: Path, spec: Spec) -> Candidate:
        self._call_state.call_id = None
        return super().refine_from_run(candidate, run_dir, spec)

    def refine(self, candidate: Candidate, result: dict, spec: Spec) -> Candidate:
        self._call_state.call_id = None
        try:
            violations = validated_fullchain_violations(candidate, result, spec)
        except (TypeError, ValueError, KeyError):
            return super().refine(candidate, result, spec)
        allowed = sorted({action for key, action in _VIOLATION_ACTIONS if violations[key] > 0})
        if not allowed:
            return super().refine(candidate, result, spec)
        ratios = candidate.power_ratio_list
        if (
            not isinstance(candidate.candidate_id, str)
            or not _SAFE_ID.fullmatch(candidate.candidate_id)
            or not _SAFE_ID.fullmatch(spec.id)
            or type(candidate.seed) is not int or candidate.seed < 0
            or not isinstance(ratios, list) or len(ratios) != 3
            or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in ratios)
            or not math.isclose(math.fsum(ratios), 1, rel_tol=0, abs_tol=1e-6)
        ):
            return super().refine(candidate, result, spec)
        observation = {
            "spec": asdict(spec), "candidate_id": candidate.candidate_id,
            "seed": candidate.seed, "power_ratio_list": ratios,
            "violations": {key: violations[key] for key, _ in _VIOLATION_ACTIONS},
            "allowed_actions": allowed,
        }
        getter = getattr(self.transport, "last_call_id", None)
        previous_call_id = getter() if callable(getter) else None
        try:
            try:
                raw = self.transport.complete(
                    system_prompt=_PROMPT_PATH.read_text(encoding="utf-8"),
                    user_prompt=json.dumps(observation, sort_keys=True, allow_nan=False),
                    timeout_seconds=self.timeout_seconds,
                )
            finally:
                current_call_id = getter() if callable(getter) else None
                self._call_state.call_id = current_call_id if current_call_id != previous_call_id else None
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1024:
                raise ValueError("model response is not a bounded JSON string")
            proposal = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(proposal, dict) or set(proposal) != {"action"} or proposal["action"] not in allowed:
                raise ValueError("model chose an unavailable refinement action")
        except Exception:
            candidate.notes.append("Model refinement unavailable or invalid; deterministic rule used.")
            return super().refine(candidate, result, spec)
        candidate.status = proposal["action"]
        candidate.notes.append(f"Model selected {candidate.status} from validated failing constraints.")
        return candidate
