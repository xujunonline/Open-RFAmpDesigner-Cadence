from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.agents.executor import execute_manager, execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _events(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]


def _replace_events(run_dir: Path, events: list[dict]) -> None:
    (run_dir / "agent_events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def test_inspect_complete_mock_run_and_detect_trace_mismatch(tmp_path: Path) -> None:
    execute_manager(Manager(), _spec(), lambda _: tmp_path / "missing", tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete"
    assert audit.trace_verified
    assert not audit.safe_to_auto_resume
    assert audit.searches_used == audit.evaluations_used == 1
    assert audit.queued_candidate_ids == ()
    assert audit.pending_candidate_id is None
    trace_path = tmp_path / "agent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["evaluations_used"] = 0
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(ValueError, match="trace disagrees"):
        inspect_journal(tmp_path)


def test_inspect_interrupted_pending_evaluation_requires_reconciliation(tmp_path: Path) -> None:
    def interrupt(_: Candidate) -> Path:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        execute_manager(Manager(), _spec(), interrupt, tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "reconcile_pending_evaluation"
    assert audit.pending_candidate_id == "S1_seed0_search0"
    assert audit.searches_used == audit.evaluations_used == 1
    assert not audit.trace_verified and not audit.safe_to_auto_resume


def test_inspect_terminal_without_snapshot_and_search_failure(tmp_path: Path) -> None:
    class FailingSearcher:
        def search(self, spec: Spec, seed: int) -> list[Candidate]:
            raise RuntimeError("private details")

    execute_manager(Manager(searcher=FailingSearcher()), _spec(), lambda _: tmp_path, tmp_path)
    (tmp_path / "agent_trace.json").unlink()
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "terminal_snapshot_missing"
    assert audit.searches_used == audit.evaluations_used == 0
    assert not audit.safe_to_auto_resume


@pytest.mark.parametrize("mutation", ["step", "candidate", "budget", "action", "duplicate", "accepted"])
def test_inspect_rejects_inconsistent_events(tmp_path: Path, mutation: str) -> None:
    execute_manager(Manager(), _spec(), lambda _: tmp_path / "missing", tmp_path)
    (tmp_path / "agent_trace.json").unlink()
    events = _events(tmp_path)
    if mutation == "step":
        events[1]["step"] = 20
    elif mutation == "candidate":
        events[2]["candidate_id"] = "unknown"
    elif mutation == "budget":
        events[0]["max_evaluations"] = 0
    elif mutation == "action":
        events[3]["action"] = "EvaluateCandidate"
    elif mutation == "accepted":
        events[3]["status"] = "accepted"
    else:
        events[1]["candidate_ids"] *= 2
        events[1]["count"] = 2
    _replace_events(tmp_path, events)
    with pytest.raises(ValueError):
        inspect_journal(tmp_path)


def test_inspect_rejects_truncated_and_legacy_journal(tmp_path: Path) -> None:
    path = tmp_path / "agent_events.jsonl"
    path.write_text('{"step":1,"action":"RunStarted"}', encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        inspect_journal(tmp_path)
    path.write_text('{"step":1,"action":"SearchCandidates"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="lacks executor context"):
        inspect_journal(tmp_path)


def test_executor_rejects_unsafe_context_before_creating_journal(tmp_path: Path) -> None:
    unsafe_spec = Spec("../S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    with pytest.raises(ValueError, match="safe identifier"):
        execute_manager(Manager(), unsafe_spec, lambda _: tmp_path, tmp_path)
    with pytest.raises(ValueError, match="seed"):
        execute_manager(Manager(), _spec(), lambda _: tmp_path, tmp_path, seed=True)
    assert not (tmp_path / "agent_events.jsonl").exists()


def test_inspect_rejects_file_symlink_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text("{}\n", encoding="ascii")
    link = tmp_path / "agent_events.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        inspect_journal(tmp_path)


def test_planned_journal_rejects_refinement_from_other_run(tmp_path: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(
            Manager(), _spec(), lambda candidate, run_id: (_ for _ in ()).throw(KeyboardInterrupt()), tmp_path,
        )
    events = _events(tmp_path)
    events.append({
        "step": 4, "action": "RefineCandidate", "candidate_id": events[2]["candidate_id"],
        "status": "needs_evaluation", "run_id": "unrelated_run", "evidence_manifest_sha256": "0" * 64,
    })
    _replace_events(tmp_path, events)
    with pytest.raises(ValueError, match="refinement transition"):
        inspect_journal(tmp_path)
