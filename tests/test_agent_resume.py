from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orfadc.agents.executor import resume_manager_after_search
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import write_spec_snapshot
from orfadc.schemas import Candidate, Spec


def _spec(power_ma: float = 10.0) -> Spec:
    return Spec("S1", 10.0, 0.2, power_ma, 10.0, 3.0, -15.0)


def _search_checkpoint(run_dir: Path, *, pending: bool = False, planned: bool = False) -> None:
    spec = _spec()
    manager = Manager(max_searches=1, max_evaluations=1)
    manager.enable_journal(run_dir)
    try:
        manager.context = (spec.id, 0)
        manager._record(
            "RunStarted", spec_id=spec.id, seed=0, max_searches=1, max_evaluations=1,
            spec_sha256=write_spec_snapshot(run_dir, spec),
            **({"dispatch_mode": "planned"} if planned else {}),
        )
        manager.search_candidates(spec)
        if pending:
            manager.pop_candidate()
    finally:
        manager.close_journal()


def test_resume_after_recorded_search_uses_original_candidate_once(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path)
    before = inspect_journal(tmp_path)
    assert before.disposition == "interrupted"
    assert before.spec_verified and before.candidate_snapshots_verified
    observed: list[str] = []

    def evaluator(candidate: Candidate) -> Path:
        observed.append(candidate.candidate_id)
        return tmp_path / "missing_evidence"

    outcome = resume_manager_after_search(_spec(), evaluator, tmp_path)
    assert outcome.status == "budget_exhausted"
    assert observed == ["S1_seed0_search0"]
    assert outcome.searches_used == outcome.evaluations_used == 1
    after = inspect_journal(tmp_path)
    assert after.disposition == "complete" and after.trace_verified
    assert not after.safe_to_auto_resume
    with pytest.raises(ValueError, match="eligible"):
        resume_manager_after_search(_spec(), evaluator, tmp_path)
    assert observed == ["S1_seed0_search0"]


def test_resume_rejects_pending_without_replaying_evaluator(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path, pending=True)
    assert inspect_journal(tmp_path).disposition == "reconcile_pending_evaluation"
    with pytest.raises(ValueError, match="eligible"):
        resume_manager_after_search(_spec(), lambda _: (_ for _ in ()).throw(AssertionError()), tmp_path)


def test_resume_rejects_spec_change_or_tampered_snapshot(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path)
    with pytest.raises(ValueError, match="context"):
        resume_manager_after_search(_spec(11.0), lambda _: tmp_path, tmp_path)
    path = tmp_path / "agent_spec.json"
    payload = json.loads(path.read_text(encoding="ascii"))
    payload["power_ma"] = 11.0
    path.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(ValueError, match="digest"):
        resume_manager_after_search(_spec(), lambda _: tmp_path, tmp_path)
    assert not (tmp_path / "agent_trace.json").exists()


def test_resume_rejects_writer_lock_contention(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path)
    with agent_run_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already owned"):
            resume_manager_after_search(_spec(), lambda _: tmp_path, tmp_path)
    assert inspect_journal(tmp_path).disposition == "interrupted"


def test_writer_lock_excludes_another_process(tmp_path: Path) -> None:
    code = (
        "import sys; from pathlib import Path; "
        "from orfadc.agents.run_lock import agent_run_lock; "
        "lock = agent_run_lock(Path(sys.argv[1])); "
        "lock.__enter__(); lock.__exit__(None, None, None)"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    with agent_run_lock(tmp_path):
        competing = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            env=environment, capture_output=True, text=True, timeout=10, check=False,
        )
    assert competing.returncode != 0
    assert "already owned by another writer" in competing.stderr
    available = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env=environment, capture_output=True, text=True, timeout=10, check=False,
    )
    assert available.returncode == 0


def test_legacy_journal_remains_auditable_but_not_resumable(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path)
    journal = tmp_path / "agent_events.jsonl"
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    del events[0]["spec_sha256"]
    journal.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    (tmp_path / "agent_spec.json").unlink()
    audit = inspect_journal(tmp_path)
    assert not audit.spec_verified
    with pytest.raises(ValueError, match="eligible"):
        resume_manager_after_search(_spec(), lambda _: tmp_path, tmp_path)


def test_legacy_resume_does_not_downgrade_planned_dispatch(tmp_path: Path) -> None:
    _search_checkpoint(tmp_path, planned=True)
    assert inspect_journal(tmp_path).disposition == "interrupted"
    with pytest.raises(ValueError, match="context"):
        resume_manager_after_search(_spec(), lambda _: tmp_path, tmp_path)
