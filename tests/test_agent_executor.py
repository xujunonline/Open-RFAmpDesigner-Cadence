from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.agents.executor import execute_manager, execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def test_executor_runs_bounded_mock_loop_and_saves_trace(tmp_path: Path) -> None:
    manager = Manager(max_searches=1, max_evaluations=1)
    outcome = execute_manager(manager, _spec(), lambda _: tmp_path / "missing", tmp_path)
    assert outcome.status == "budget_exhausted"
    assert outcome.searches_used == outcome.evaluations_used == 1
    saved = json.loads(outcome.trace_path.read_text(encoding="utf-8"))
    assert [event["action"] for event in saved["events"]] == [
        "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop"
    ]
    assert saved["events"][-2]["status"] == "needs_evaluation"
    assert saved["pending_candidate_ids"] == []
    journal = [json.loads(line) for line in (tmp_path / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    assert journal == saved["events"]
    fresh_trace_dir = tmp_path / "another_trace"
    fresh_trace_dir.mkdir()
    with pytest.raises(ValueError, match="fresh manager"):
        execute_manager(manager, _spec(), lambda _: tmp_path, fresh_trace_dir)


@pytest.mark.parametrize(
    ("exc", "failure_code"),
    [(RuntimeError("private /model/path"), "backend_error"),
     (TimeoutError("private /model/path"), "backend_timeout")],
)
def test_executor_redacts_backend_failures(
    tmp_path: Path, exc: Exception, failure_code: str
) -> None:
    def failed_evaluator(_: Candidate) -> Path:
        raise exc

    manager = Manager(max_searches=1, max_evaluations=1)
    outcome = execute_manager(manager, _spec(), failed_evaluator, tmp_path)
    content = outcome.trace_path.read_text(encoding="utf-8")
    assert "private" not in content
    assert manager.trace[-2]["failure_code"] == failure_code
    assert manager.pending == {}


def test_executor_empty_search_ends_without_evaluation(tmp_path: Path) -> None:
    class EmptySearcher:
        def search(self, spec: Spec, seed: int) -> list[Candidate]:
            return []

    def forbidden(_: Candidate) -> Path:
        raise AssertionError("empty queue cannot evaluate")

    manager = Manager(searcher=EmptySearcher(), max_searches=3)
    outcome = execute_manager(manager, _spec(), forbidden, tmp_path)
    assert outcome.status == "no_candidates"
    assert outcome.searches_used == 3
    assert outcome.evaluations_used == 0


def test_executor_invalid_search_result_is_terminal_and_redacted(tmp_path: Path) -> None:
    class BadSearcher:
        def search(self, spec: Spec, seed: int) -> str:
            raise ValueError("private /model/path")

    outcome = execute_manager(Manager(searcher=BadSearcher()), _spec(), lambda _: tmp_path, tmp_path)
    assert outcome.status == "search_failed"
    assert outcome.searches_used == 0
    assert "private" not in outcome.trace_path.read_text(encoding="utf-8")


def test_executor_bad_run_directory_fails_closed(tmp_path: Path) -> None:
    manager = Manager(max_searches=1, max_evaluations=1)
    outcome = execute_manager(manager, _spec(), lambda _: 42, tmp_path)  # type: ignore[return-value]
    assert outcome.evaluations_used == 1
    assert manager.trace[-2]["failure_code"] == "invalid_run_directory"
    assert manager.pending == {}


def test_executor_refuses_missing_or_existing_trace_location(tmp_path: Path) -> None:
    manager = Manager(max_searches=1, max_evaluations=1)
    with pytest.raises(ValueError, match="trace directory"):
        execute_manager(manager, _spec(), lambda _: tmp_path, tmp_path / "missing")
    assert manager.trace == []
    (tmp_path / "agent_trace.json").write_text("existing", encoding="ascii")
    with pytest.raises(FileExistsError, match="already exists"):
        execute_manager(manager, _spec(), lambda _: tmp_path, tmp_path)
    assert manager.trace == []
    journal_dir = tmp_path / "existing_journal"
    journal_dir.mkdir()
    (journal_dir / "agent_events.jsonl").write_text("existing\n", encoding="ascii")
    with pytest.raises(FileExistsError, match="already exists"):
        execute_manager(manager, _spec(), lambda _: tmp_path, journal_dir)
    assert manager.trace == []


def test_executor_preserves_incremental_journal_on_interruption(tmp_path: Path) -> None:
    def interrupted(_: Candidate) -> Path:
        raise KeyboardInterrupt()

    manager = Manager(max_searches=1, max_evaluations=1)
    with pytest.raises(KeyboardInterrupt):
        execute_manager(manager, _spec(), interrupted, tmp_path)
    events = [json.loads(line) for line in (tmp_path / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    assert [event["action"] for event in events] == [
        "RunStarted", "SearchCandidates", "EvaluateCandidate"
    ]
    assert not (tmp_path / "agent_trace.json").exists()
    assert manager.pending


def test_planned_dispatch_records_run_id_before_interrupted_backend(tmp_path: Path) -> None:
    seen: list[str] = []

    def interrupted(_: Candidate, run_id: str) -> Path:
        seen.append(run_id)
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(Manager(), _spec(), interrupted, tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "reconcile_pending_evaluation"
    assert audit.pending_run_id == seen[0]
    assert audit.spec_verified and audit.candidate_snapshots_verified
    assert not (tmp_path / "agent_trace.json").exists()


def test_planned_uncertain_remote_keeps_journal_pending(tmp_path: Path) -> None:
    dispatched: list[str] = []

    def uncertain(_: Candidate, run_id: str) -> Path:
        dispatched.append(run_id)
        raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain")

    with pytest.raises(RemoteEvaluationUncertain):
        execute_manager_planned(Manager(max_searches=1, max_evaluations=1), _spec(), uncertain, tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "reconcile_pending_evaluation"
    assert audit.pending_run_id == dispatched[0]
    assert audit.evaluations_used == 1
    assert not (tmp_path / "agent_trace.json").exists()
    assert not any(event.get("action") in {"EvaluationFailed", "Stop"} for event in (
        json.loads(line) for line in (tmp_path / "agent_events.jsonl").read_text().splitlines()
    ))


@pytest.mark.parametrize("wrong_dir", [True, False])
def test_planned_dispatch_rejects_wrong_or_incomplete_archive(tmp_path: Path, wrong_dir: bool) -> None:
    dispatched: list[str] = []

    def evaluator(_: Candidate, run_id: str) -> Path:
        dispatched.append(run_id)
        return tmp_path / ("different_run" if wrong_dir else run_id)

    outcome = execute_manager_planned(Manager(), _spec(), evaluator, tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete"
    assert audit.evaluations_used == 1 and audit.pending_run_id is None
    assert outcome.status == "budget_exhausted"
    assert [event["action"] for event in json.loads(outcome.trace_path.read_text())["events"]][-2] == "EvaluationFailed"
    assert dispatched
