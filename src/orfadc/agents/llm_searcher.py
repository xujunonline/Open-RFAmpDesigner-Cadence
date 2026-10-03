from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from threading import local
from typing import Protocol

from ..schemas import Candidate, Spec
from .memory import VerifiedFailureKB
from .tool_registry import AgentToolRegistry


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_PROMPT_PATH = Path(__file__).parent / "prompts" / "searcher.md"


class ModelTransport(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str: ...


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("model response contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant: {value}")


class LLMSearcher:
    """Accept one bounded model proposal; only the tool registry can interpret it."""

    def __init__(
        self, transport: ModelTransport, *, timeout_seconds: int = 30,
        memory: VerifiedFailureKB | None = None,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValueError("model timeout must be an integer in 1..120 seconds")
        if memory is not None and not isinstance(memory, VerifiedFailureKB):
            raise TypeError("model memory must be a verified failure KB")
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.memory = memory
        self._call_state = local()

    def last_call_id(self) -> str | None:
        return getattr(self._call_state, "call_id", None)

    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        self._call_state.call_id = None
        if not isinstance(spec, Spec) or not _SAFE_ID.fullmatch(spec.id):
            raise ValueError("LLM search needs a safe validated spec")
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        observation = {"spec": asdict(spec), "seed": seed}
        if self.memory is not None:
            observation["diagnostic_failure_context"] = self.memory.retrieve_failure_context(spec)
        user_prompt = json.dumps(observation, sort_keys=True, allow_nan=False)
        getter = getattr(self.transport, "last_call_id", None)
        previous_call_id = getter() if callable(getter) else None
        try:
            raw = self.transport.complete(
                system_prompt=prompt, user_prompt=user_prompt, timeout_seconds=self.timeout_seconds,
            )
        finally:
            current_call_id = getter() if callable(getter) else None
            self._call_state.call_id = current_call_id if current_call_id != previous_call_id else None
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
            raise ValueError("model response must be a bounded JSON string")
        request = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
            raise ValueError("model must return one tool request")
        if request["tool"] != "active_sizing":
            raise ValueError("LLM Searcher may only propose active_sizing")
        args = request["arguments"]
        if not isinstance(args, dict) or set(args) != {"power_ratio_list", "total_current_ma"}:
            raise ValueError("model returned invalid active_sizing arguments")
        ratios = args["power_ratio_list"]
        if (
            not isinstance(ratios, list) or len(ratios) != 3
            or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in ratios)
            or not math.isclose(math.fsum(ratios), 1.0, rel_tol=0, abs_tol=1e-6)
        ):
            raise ValueError("model must return three positive ratios summing to one")
        sizing = AgentToolRegistry(spec).invoke(request)
        canonical = json.dumps(
            {"ratios": [float(value) for value in ratios], "total_current_ma": float(args["total_current_ma"])},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        proposal_hash = hashlib.sha256(canonical.encode("ascii")).hexdigest()
        candidate = Candidate(
            candidate_id=f"{spec.id[:20]}_s{seed}_{proposal_hash[:12]}",
            spec_id=spec.id,
            seed=seed,
            power_ratio_list=[float(value) for value in ratios],
            active_params={"stages": sizing["stages"], "proposal_sha256": proposal_hash},
            status=sizing["status"],
        )
        return [candidate]
