from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.agents.executor import execute_manager, resume_manager_after_search
import orfadc.agents.llm_manager as manager_module
from orfadc.agents.journal import inspect_journal
from orfadc.agents.llm_manager import LLMManagerPolicy
from orfadc.agents.manager import Manager
from orfadc.agents.searcher import Searcher
from orfadc.agents.spec_snapshots import write_spec_snapshot
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _searcher() -> Searcher:
    return Searcher([[0.4, 0.3, 0.3], [0.3, 0.4, 0.3]])


class _Model:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(self, **kwargs) -> object:
        self.calls.append(kwargs)
        return self.response


def _response(candidate_id: str) -> str:
    return json.dumps({"action": "EvaluateCandidate", "candidate_id": candidate_id})


def test_model_manager_prioritizes_existing_candidate_with_audited_trace(tmp_path: Path) -> None:
    model = _Model(_response("S1_seed0_search1"))
    manager = Manager(_searcher(), priority_policy=LLMManagerPolicy(model),
                      max_searches=1, max_evaluations=2)
    observed: list[str] = []

    def evaluator(candidate: Candidate) -> Path:
        observed.append(candidate.candidate_id)
        return tmp_path / "missing"

    outcome = execute_manager(manager, _spec(), evaluator, tmp_path)
    assert outcome.status == "budget_exhausted"
    assert observed == ["S1_seed0_search1", "S1_seed0_search0"]
    assert len(model.calls) == 1
    prompt = json.loads(model.calls[0]["user_prompt"])
    assert [item["candidate_id"] for item in prompt["candidate_options"]] == [
        "S1_seed0_search0", "S1_seed0_search1",
    ]
    assert "netlist" not in model.calls[0]["user_prompt"].lower()
    assert [(event["candidate_id"], event["source"]) for event in manager.trace
            if event["action"] == "QueuePriority"] == [("S1_seed0_search1", "model")]
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete" and audit.trace_verified


@pytest.mark.parametrize("response", (
    "not json",
    _response("invented_candidate"),
    json.dumps({"action": "Stop", "candidate_id": "S1_seed0_search1"}),
    json.dumps({"action": "EvaluateCandidate", "candidate_id": "S1_seed0_search1",
                "spec_pass": True}),
    '{"action":"EvaluateCandidate","candidate_id":"S1_seed0_search1",'
    '"candidate_id":"S1_seed0_search0"}',
    " " * 1025,
))
def test_model_manager_invalid_response_falls_back_to_fifo(
    tmp_path: Path, response: str,
) -> None:
    model = _Model(response)
    manager = Manager(_searcher(), priority_policy=LLMManagerPolicy(model),
                      max_searches=1, max_evaluations=1)
    observed: list[str] = []

    def evaluator(candidate: Candidate) -> Path:
        observed.append(candidate.candidate_id)
        return tmp_path / "missing"

    execute_manager(manager, _spec(), evaluator, tmp_path)
    assert observed == ["S1_seed0_search0"]
    priority = next(event for event in manager.trace if event["action"] == "QueuePriority")
    assert priority["source"] == "fallback"
    assert priority["candidate_id"] == observed[0]
    assert inspect_journal(tmp_path).trace_verified


def test_model_manager_transport_error_is_redacted(tmp_path: Path) -> None:
    class _FailingModel:
        def complete(self, **kwargs) -> str:
            raise TimeoutError("private /model/secret")

    manager = Manager(_searcher(), priority_policy=LLMManagerPolicy(_FailingModel()),
                      max_searches=1, max_evaluations=1)
    execute_manager(manager, _spec(), lambda _: tmp_path / "missing", tmp_path)
    assert "private" not in (tmp_path / "agent_trace.json").read_text(encoding="utf-8")
    assert inspect_journal(tmp_path).trace_verified


def test_prompt_read_failure_does_not_reuse_prior_model_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PriorCallModel:
        def last_call_id(self) -> str:
            return "a" * 32

        def complete(self, **kwargs) -> str:
            raise AssertionError("request must not be sent")

    monkeypatch.setattr(manager_module, "_PROMPT_PATH", tmp_path / "missing_prompt.md")
    queue = _searcher().search(_spec())
    choice = LLMManagerPolicy(PriorCallModel()).choose(
        _spec(), 0, queue, searches_used=1, max_searches=1,
        evaluations_used=0, max_evaluations=1,
    )
    assert choice == (queue[0].candidate_id, "fallback", None)


def test_priority_checkpoint_resumes_without_asking_model_again(tmp_path: Path) -> None:
    spec = _spec()
    manager = Manager(_searcher(), max_searches=1, max_evaluations=2)
    manager.enable_journal(tmp_path)
    try:
        manager.context = (spec.id, 0)
        manager._record("RunStarted", spec_id=spec.id, seed=0,
                        max_searches=1, max_evaluations=2,
                        spec_sha256=write_spec_snapshot(tmp_path, spec))
        manager.search_candidates(spec)
        manager.prioritize_candidate("S1_seed0_search1", source="model")
    finally:
        manager.close_journal()
    before = inspect_journal(tmp_path)
    assert before.disposition == "interrupted"
    assert before.queued_candidate_ids == ("S1_seed0_search1", "S1_seed0_search0")
    observed: list[str] = []

    def evaluator(candidate: Candidate) -> Path:
        observed.append(candidate.candidate_id)
        return tmp_path / "missing"

    outcome = resume_manager_after_search(spec, evaluator, tmp_path)
    assert outcome.status == "budget_exhausted"
    assert observed == ["S1_seed0_search1", "S1_seed0_search0"]
    assert inspect_journal(tmp_path).trace_verified


@pytest.mark.parametrize("mutation", ("unknown", "false_fallback", "extra_event"))
def test_priority_journal_rejects_tampering(tmp_path: Path, mutation: str) -> None:
    spec = _spec()
    manager = Manager(_searcher(), max_searches=1, max_evaluations=1)
    manager.enable_journal(tmp_path)
    try:
        manager.context = (spec.id, 0)
        manager._record("RunStarted", spec_id=spec.id, seed=0,
                        max_searches=1, max_evaluations=1,
                        spec_sha256=write_spec_snapshot(tmp_path, spec))
        manager.search_candidates(spec)
        manager.prioritize_candidate("S1_seed0_search1", source="model")
    finally:
        manager.close_journal()
    path = tmp_path / "agent_events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if mutation == "unknown":
        events[-1]["candidate_id"] = "unseen"
    elif mutation == "false_fallback":
        events[-1]["source"] = "fallback"
    else:
        events.append({"step": len(events) + 1, "action": "Stop", "status": "budget_exhausted"})
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_journal(tmp_path)
