from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..schemas import Candidate, Spec
from .llm_searcher import ModelTransport, _reject_constant, _unique_object


_PROMPT_PATH = Path(__file__).parent / "prompts" / "manager.md"


class LLMManagerPolicy:
    """Choose only the next queued candidate; the executor owns every transition."""

    def __init__(self, transport: ModelTransport, *, timeout_seconds: int = 30) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValueError("manager model timeout must be 1..120 seconds")
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def choose(
        self, spec: Spec, seed: int, queue: list[Candidate], *,
        searches_used: int, max_searches: int,
        evaluations_used: int, max_evaluations: int,
    ) -> tuple[str, str, str | None]:
        if len(queue) < 2:
            raise ValueError("model priority requires at least two queued candidates")
        fallback = queue[0].candidate_id
        if len(queue) > 32:
            return fallback, "fallback", None
        if any(candidate.spec_id != spec.id or candidate.seed != seed
               for candidate in queue):
            raise ValueError("manager model queue has mixed spec or seed")
        observation = {
            "spec": asdict(spec), "seed": seed,
            "budget": {
                "searches_used": searches_used, "max_searches": max_searches,
                "evaluations_used": evaluations_used, "max_evaluations": max_evaluations,
            },
            "candidate_options": [
                {"candidate_id": candidate.candidate_id,
                 "power_ratio_list": candidate.power_ratio_list,
                 "status": candidate.status}
                for candidate in queue
            ],
        }
        def call_id() -> str | None:
            getter = getattr(self.transport, "last_call_id", None)
            return getter() if callable(getter) else None

        previous_call_id = call_id()
        try:
            raw = self.transport.complete(
                system_prompt=_PROMPT_PATH.read_text(encoding="utf-8"),
                user_prompt=json.dumps(observation, sort_keys=True, allow_nan=False),
                timeout_seconds=self.timeout_seconds,
            )
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1024:
                raise ValueError("manager response is not bounded JSON")
            proposal = json.loads(raw, object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant)
            allowed = {candidate.candidate_id for candidate in queue}
            if (
                not isinstance(proposal, dict)
                or set(proposal) != {"action", "candidate_id"}
                or proposal["action"] != "EvaluateCandidate"
                or type(proposal["candidate_id"]) is not str
                or proposal["candidate_id"] not in allowed
            ):
                raise ValueError("manager proposed an unavailable candidate or action")
        except Exception:
            current_call_id = call_id()
            return fallback, "fallback", current_call_id if current_call_id != previous_call_id else None
        current_call_id = call_id()
        return proposal["candidate_id"], "model", current_call_id if current_call_id != previous_call_id else None
