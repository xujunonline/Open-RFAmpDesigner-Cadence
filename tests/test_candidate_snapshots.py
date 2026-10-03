from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.agents.executor import execute_manager
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.schemas import Candidate, SimResult, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _candidate(spec: Spec, seed: int, **changes) -> Candidate:
    return Candidate(
        candidate_id="proposal_1", spec_id=spec.id, seed=seed,
        power_ratio_list=[0.4, 0.3, 0.3],
        active_params=changes.get("active_params", {"width_um": 100.0}),
        sim_result=changes.get("sim_result"),
    )


class _OneProposal:
    def __init__(self, **changes) -> None:
        self.changes = changes

    def search(self, spec: Spec, seed: int) -> list[Candidate]:
        return [_candidate(spec, seed, **self.changes)]


def test_complete_run_snapshots_are_bound_to_search_event(tmp_path: Path) -> None:
    execute_manager(Manager(searcher=_OneProposal()), _spec(), lambda _: tmp_path / "missing", tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete"
    assert audit.candidate_snapshots_verified
    assert not audit.safe_to_auto_resume
    snapshots = (tmp_path / "agent_candidates.jsonl").read_text(encoding="utf-8")
    record = json.loads(snapshots)
    assert record["search_step"] == 2
    assert [item["candidate_id"] for item in record["candidates"]] == ["proposal_1"]
    assert record["candidates"][0]["sim_result"] is None
    assert "missing" not in snapshots


def test_interrupted_pending_run_has_snapshot_but_no_auto_resume(tmp_path: Path) -> None:
    def interrupt(_: Candidate) -> Path:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        execute_manager(Manager(searcher=_OneProposal()), _spec(), interrupt, tmp_path)
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "reconcile_pending_evaluation"
    assert audit.candidate_snapshots_verified
    assert audit.pending_candidate_id == "proposal_1"
    assert not audit.safe_to_auto_resume


def test_candidate_snapshot_mutation_missing_and_orphan_are_rejected(tmp_path: Path) -> None:
    execute_manager(Manager(searcher=_OneProposal()), _spec(), lambda _: tmp_path / "missing", tmp_path)
    sidecar = tmp_path / "agent_candidates.jsonl"
    original = sidecar.read_bytes()
    sidecar.write_bytes(original.replace(b"100.0", b"101.0"))
    with pytest.raises(ValueError, match="digest disagrees"):
        inspect_journal(tmp_path)
    sidecar.write_bytes(original + original)
    with pytest.raises(ValueError, match="count disagrees"):
        inspect_journal(tmp_path)
    sidecar.unlink()
    with pytest.raises(ValueError, match="sidecar is missing"):
        inspect_journal(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"active_params": {"model_path": "/private/pdk/model.scs"}},
        {"active_params": {"api_key": "opaque"}},
        {"active_params": {"bad": float("nan")}},
        {"active_params": {"oversized": "x" * 300}},
        {"sim_result": SimResult(s21_db=20.0)},
    ],
)
def test_unsafe_or_pre_scored_proposals_fail_before_evaluation(tmp_path: Path, changes: dict) -> None:
    called = False

    def evaluator(_: Candidate) -> Path:
        nonlocal called
        called = True
        return tmp_path / "candidate"

    outcome = execute_manager(Manager(searcher=_OneProposal(**changes)), _spec(), evaluator, tmp_path)
    assert outcome.status == "search_failed"
    assert not called
    assert (tmp_path / "agent_candidates.jsonl").read_bytes() == b""
    assert inspect_journal(tmp_path).candidate_snapshots_verified
    assert "/private/pdk" not in (tmp_path / "agent_events.jsonl").read_text(encoding="utf-8")


def test_existing_snapshot_sidecar_prevents_executor_reuse(tmp_path: Path) -> None:
    (tmp_path / "agent_candidates.jsonl").write_text("old\n", encoding="ascii")
    with pytest.raises(FileExistsError, match="already exists"):
        execute_manager(Manager(), _spec(), lambda _: tmp_path, tmp_path)
    assert not (tmp_path / "agent_events.jsonl").exists()


def test_legacy_real_journal_does_not_claim_candidate_snapshots() -> None:
    old = Path("results/runs/agent_diagnostic/20260926T113051Z_23447ca2")
    if not old.is_dir():
        pytest.skip("private legacy agent journal is unavailable")
    audit = inspect_journal(old)
    assert audit.disposition == "complete"
    assert not audit.candidate_snapshots_verified
    assert not audit.safe_to_auto_resume


def test_new_real_diagnostic_journal_binds_snapshot_and_candidate_evidence() -> None:
    trace = Path("results/runs/agent_diagnostic/20260926T213331Z_7b584495")
    runs = Path("results/runs")
    if not trace.is_dir():
        pytest.skip("private candidate-snapshot diagnostic archive is unavailable")
    audit = inspect_journal(trace, candidate_runs_root=runs)
    assert audit.disposition == "complete"
    assert audit.trace_verified
    assert audit.candidate_snapshots_verified
    assert audit.candidate_bindings_verified
    assert not audit.safe_to_auto_resume
