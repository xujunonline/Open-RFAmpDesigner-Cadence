from __future__ import annotations

import os
import re
import time
from threading import Lock, local
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .model_call_evidence import ModelCallEvidence


_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _token_count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 1_000_000_000_000 else None


def _usage_fields(response: Any) -> dict[str, int | None]:
    usage = _field(response, "usage")
    input_details = _field(usage, "input_tokens_details")
    output_details = _field(usage, "output_tokens_details")
    input_tokens = _token_count(_field(usage, "input_tokens"))
    output_tokens = _token_count(_field(usage, "output_tokens"))
    total_tokens = _token_count(_field(usage, "total_tokens"))
    cached_tokens = _token_count(_field(input_details, "cached_tokens"))
    cache_write_tokens = _token_count(_field(input_details, "cache_write_tokens"))
    reasoning_tokens = _token_count(_field(output_details, "reasoning_tokens"))
    if input_tokens is None or (cached_tokens is not None and cached_tokens > input_tokens):
        cached_tokens = None
    if input_tokens is None or (cache_write_tokens is not None and cache_write_tokens > input_tokens):
        cache_write_tokens = None
    if output_tokens is None or (reasoning_tokens is not None and reasoning_tokens > output_tokens):
        reasoning_tokens = None
    if (input_tokens is not None and output_tokens is not None
            and total_tokens != input_tokens + output_tokens):
        total_tokens = None
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_input_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


class OpenAIResponsesTransport:
    """Optional Responses API transport; proposal validation remains in LLMSearcher."""

    def __init__(self, client: Any, *, model: str,
                 usage_evidence: ModelCallEvidence | None = None) -> None:
        if not isinstance(model, str) or not _MODEL_ID.fullmatch(model):
            raise ValueError("model must be an explicit safe model identifier")
        if client is None or not hasattr(client, "responses"):
            raise ValueError("an OpenAI-compatible Responses client is required")
        self.client = client
        self.model = model
        self.usage_evidence = usage_evidence
        self._usage_events: list[dict[str, str | int | float | None]] = []
        self._usage_lock = Lock()
        self._call_state = local()

    def last_call_id(self) -> str | None:
        """Call ID for the current thread's most recent complete() attempt."""
        return getattr(self._call_state, "call_id", None)

    def drain_usage_events(self) -> list[dict[str, str | int | float | None]]:
        """Atomically take metadata only; never include prompts, responses, or errors."""
        with self._usage_lock:
            events = self._usage_events
            self._usage_events = []
        return events

    @classmethod
    def from_environment(cls, *, model: str,
                         usage_evidence: ModelCallEvidence | None = None) -> OpenAIResponsesTransport:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("the optional openai Python SDK is not installed") from exc
        return cls(OpenAI(max_retries=0), model=model, usage_evidence=usage_evidence)

    def complete(self, *, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
        self._call_state.call_id = None
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValueError("model timeout must be an integer in 1..120 seconds")
        call_id = self.usage_evidence.begin(self.model) if self.usage_evidence is not None else None
        self._call_state.call_id = call_id
        started = time.perf_counter()
        outcome = "transport_error"
        response = None
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
                timeout=timeout_seconds,
                store=False,
                max_output_tokens=512,
            )
            if getattr(response, "status", None) != "completed":
                outcome = "incomplete_response"
                raise ValueError("model response did not complete")
            output = getattr(response, "output_text", None)
            if not isinstance(output, str) or not output.strip():
                outcome = "empty_output"
                raise ValueError("model response has no text output")
            outcome = "completed"
            return output
        finally:
            reported_model = _field(response, "model")
            event: dict[str, str | int | float | None] = {
                "model_requested": self.model,
                "model_reported": reported_model if isinstance(reported_model, str)
                and _MODEL_ID.fullmatch(reported_model) else None,
                "outcome": outcome,
                "latency_seconds": max(0.0, time.perf_counter() - started),
                **_usage_fields(response),
            }
            if call_id is not None:
                self.usage_evidence.finish(call_id, event)
            with self._usage_lock:
                self._usage_events.append(event)
