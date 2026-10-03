from __future__ import annotations

import json

import pytest

from orfadc.agents.llm_searcher import LLMSearcher
from orfadc.agents.manager import Manager
from orfadc.schemas import Spec


class FakeModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _proposal(ratios=None, current=9.0) -> str:
    return json.dumps({"tool": "active_sizing", "arguments": {
        "power_ratio_list": ratios or [0.4, 0.3, 0.3], "total_current_ma": current,
    }})


def test_model_proposal_uses_registry_without_claiming_simulation() -> None:
    model = FakeModel(_proposal())
    searcher = LLMSearcher(model, timeout_seconds=7)
    first = searcher.search(_spec(), seed=2)[0]
    second = searcher.search(_spec(), seed=2)[0]
    assert first.candidate_id == second.candidate_id
    assert first.status == "needs_verified_active_lookup"
    assert first.sim_result is None
    assert [stage["current_ma"] for stage in first.active_params["stages"]] == pytest.approx([3.6, 2.7, 2.7])
    assert len(first.active_params["proposal_sha256"]) == 64
    assert model.calls[0]["timeout_seconds"] == 7
    assert json.loads(model.calls[0]["user_prompt"])["seed"] == 2
    manager = Manager(searcher, max_searches=1, max_evaluations=1)
    assert manager.search_candidates(_spec(), seed=2)[0].candidate_id == first.candidate_id


@pytest.mark.parametrize("response", [
    "not JSON", "```json\n{}\n```", "{\"tool\":\"active_sizing\",\"tool\":\"active_sizing\",\"arguments\":{}}",
    _proposal(current=11.0), _proposal(ratios=[0.4, 0.3, 0.2]),
    _proposal(ratios=[True, 0.3, 0.7]),
    json.dumps({"tool": "fullchain_eval", "arguments": {"candidate_id": "x"}}),
    json.dumps({"tool": "active_sizing", "arguments": {
        "power_ratio_list": [0.4, 0.3, 0.3], "total_current_ma": 9.0}, "spec_pass": True}),
    " " * 4097,
])
def test_model_cannot_escape_proposal_contract(response: str) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        LLMSearcher(FakeModel(response)).search(_spec())


def test_transport_and_context_fail_closed() -> None:
    with pytest.raises(ValueError):
        LLMSearcher(FakeModel(_proposal()), timeout_seconds=0)
    with pytest.raises(ValueError):
        LLMSearcher(FakeModel(_proposal())).search(_spec(), seed=-1)
    with pytest.raises(ValueError):
        LLMSearcher(FakeModel(None)).search(_spec())


def test_searcher_does_not_reuse_a_prior_model_call_id() -> None:
    class PriorCallModel:
        def last_call_id(self) -> str:
            return "c" * 32

        def complete(self, **kwargs) -> str:
            return _proposal()

    searcher = LLMSearcher(PriorCallModel())
    assert len(searcher.search(_spec())) == 1
    assert searcher.last_call_id() is None
