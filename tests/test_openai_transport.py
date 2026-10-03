from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from orfadc.agents.llm_searcher import LLMSearcher
from orfadc.agents.openai_transport import OpenAIResponsesTransport
from orfadc.schemas import Spec


class FakeResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _transport(response):
    responses = FakeResponses(response)
    return OpenAIResponsesTransport(SimpleNamespace(responses=responses), model="mock-model-1"), responses


def test_openai_transport_and_searcher_use_fake_client_only() -> None:
    proposal = '{"tool":"active_sizing","arguments":{"power_ratio_list":[0.4,0.3,0.3],"total_current_ma":9}}'
    transport, responses = _transport(SimpleNamespace(status="completed", output_text=proposal))
    spec = Spec("S1", 10, 0.2, 10, 10, 3, -15)
    candidate = LLMSearcher(transport, timeout_seconds=8).search(spec)[0]
    assert candidate.sim_result is None
    assert candidate.status == "needs_verified_active_lookup"
    call = responses.calls[0]
    assert call["model"] == "mock-model-1"
    assert call["store"] is False
    assert call["timeout"] == 8
    assert call["max_output_tokens"] == 512
    assert "S1" in call["input"]
    assert "active_sizing" in call["instructions"]


@pytest.mark.parametrize("response", [
    SimpleNamespace(status="incomplete", output_text="{}"),
    SimpleNamespace(status="completed", output_text=""),
    SimpleNamespace(status="completed", output_text=None),
])
def test_noncompleted_or_empty_response_fails_closed(response) -> None:
    transport, _ = _transport(response)
    with pytest.raises(ValueError):
        transport.complete(system_prompt="p", user_prompt="s", timeout_seconds=5)


def test_missing_key_and_invalid_configuration(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        OpenAIResponsesTransport.from_environment(model="mock-model-1")
    with pytest.raises(ValueError):
        OpenAIResponsesTransport(SimpleNamespace(responses=object()), model="bad/model")
    transport, _ = _transport(SimpleNamespace(status="completed", output_text="{}"))
    with pytest.raises(ValueError):
        transport.complete(system_prompt="p", user_prompt="s", timeout_seconds=0)
    assert transport.drain_usage_events() == []


def test_usage_event_records_only_response_metadata_and_can_be_drained() -> None:
    response = SimpleNamespace(
        status="completed", output_text="private response", model="mock-model-2",
        usage=SimpleNamespace(
            input_tokens=120, output_tokens=30, total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=10),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )
    transport, _ = _transport(response)
    assert transport.complete(system_prompt="private prompt", user_prompt="private netlist", timeout_seconds=5) == "private response"
    events = transport.drain_usage_events()
    assert len(events) == 1
    assert events[0]["model_requested"] == "mock-model-1"
    assert events[0]["model_reported"] == "mock-model-2"
    assert events[0]["outcome"] == "completed"
    assert events[0]["latency_seconds"] >= 0
    assert {key: events[0][key] for key in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens", "total_tokens",
    )} == {
        "input_tokens": 120, "cached_input_tokens": 20, "cache_write_input_tokens": 10,
        "output_tokens": 30,
        "reasoning_output_tokens": 5, "total_tokens": 150,
    }
    assert "private" not in json.dumps(events)
    assert transport.drain_usage_events() == []


def test_missing_or_inconsistent_usage_is_unknown_not_zero() -> None:
    response = SimpleNamespace(
        status="completed", output_text="{}", model="unsafe/model",
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=3, total_tokens=99,
            input_tokens_details=SimpleNamespace(cached_tokens=11),
            output_tokens_details=SimpleNamespace(reasoning_tokens=4),
        ),
    )
    transport, _ = _transport(response)
    transport.complete(system_prompt="p", user_prompt="s", timeout_seconds=5)
    event = transport.drain_usage_events()[0]
    assert event["model_reported"] is None
    assert event["input_tokens"] == 10
    assert event["cached_input_tokens"] is None
    assert event["output_tokens"] == 3
    assert event["reasoning_output_tokens"] is None
    assert event["total_tokens"] is None


def test_response_rejection_and_transport_error_do_not_leak_text() -> None:
    transport, _ = _transport(SimpleNamespace(status="incomplete", output_text="secret", usage=None))
    with pytest.raises(ValueError, match="did not complete"):
        transport.complete(system_prompt="secret", user_prompt="secret", timeout_seconds=5)
    event = transport.drain_usage_events()[0]
    assert event["outcome"] == "incomplete_response"
    assert event["input_tokens"] is None
    assert "secret" not in json.dumps(event)

    class RaisingResponses:
        def create(self, **kwargs):
            raise RuntimeError("secret remote error body")

    failing = OpenAIResponsesTransport(SimpleNamespace(responses=RaisingResponses()), model="mock-model-1")
    with pytest.raises(RuntimeError, match="secret remote error"):
        failing.complete(system_prompt="secret", user_prompt="secret", timeout_seconds=5)
    event = failing.drain_usage_events()[0]
    assert event["outcome"] == "transport_error"
    assert event["total_tokens"] is None
    assert "secret" not in json.dumps(event)
