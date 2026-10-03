from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents import reconcile_pending as module
from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _pending(trace_dir: Path) -> tuple[str, Candidate]:
    captured: list[tuple[str, Candidate]] = []

    def interrupted(candidate: Candidate, run_id: str) -> Path:
        captured.append((run_id, candidate))
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(Manager(), _spec(), interrupted, trace_dir)
    return captured[0]


def _archive(runs_root: Path, run_id: str, candidate: Candidate) -> Path:
    run_dir = runs_root / "S1" / "seed0" / candidate.candidate_id / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "spec": asdict(_spec()), "candidate": candidate.to_dict(), "seed": 0,
        "timeout_seconds": 30, "metrics": {"s21_db": 0.0},
    }
    write_json(run_dir / "metrics.json", payload)
    write_json(run_dir / "candidate.json", candidate.to_dict())
    (run_dir / "netlist.scs").write_text("diagnostic mock\n", encoding="ascii")
    (run_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="ascii")
    write_evidence_manifest(run_dir, {
        "metrics": "metrics.json", "candidate": "candidate.json",
        "netlist": "netlist.scs", "spectre_log": "spectre.log",
    })
    return run_dir


def test_reconcile_adopts_only_planned_complete_archive_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    run_id, candidate = _pending(trace_dir)
    archived = _archive(runs_root, run_id, candidate)
    calls: list[Path] = []

    def trusted_audit(path: Path, **_: object) -> dict:
        calls.append(path)
        return read_evidenced_metrics(path)

    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", trusted_audit)
    report = module.reconcile_pending_diagnostic(
        trace_dir, runs_root, _spec(), seed=0, template=tmp_path / "unused", template_sha256="0" * 64,
    )
    assert calls == [archived]
    assert report["candidate_run_id"] == run_id
    assert report["spectre_dispatched_by_reconciliation"] is False
    assert report["spec_pass"] is None and report["not_lna_result"] is True
    audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    assert audit.disposition == "complete" and audit.candidate_bindings_verified
    assert audit.spec_verified and audit.pending_run_id is None
    events = json.loads((trace_dir / "agent_trace.json").read_text())["events"]
    assert [item["action"] for item in events] == [
        "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop",
    ]
    with pytest.raises(ValueError, match="not eligible"):
        module.reconcile_pending_diagnostic(
            trace_dir, runs_root, _spec(), seed=0, template=tmp_path / "unused", template_sha256="0" * 64,
        )
    assert calls == [archived]


def test_reconcile_rejects_missing_planned_archive_without_journal_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    run_id, candidate = _pending(trace_dir)
    _archive(runs_root, "unrelated_run", candidate)
    before = (trace_dir / "agent_events.jsonl").read_bytes()
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda *a, **k: pytest.fail("audit must not run"))
    with pytest.raises(ValueError, match="planned candidate archive is absent"):
        module.reconcile_pending_diagnostic(
            trace_dir, runs_root, _spec(), seed=0, template=tmp_path / "unused", template_sha256="0" * 64,
        )
    assert (trace_dir / "agent_events.jsonl").read_bytes() == before
    assert inspect_journal(trace_dir).pending_run_id == run_id


def test_reconcile_rejects_unverified_archive_without_journal_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    run_id, candidate = _pending(trace_dir)
    _archive(runs_root, run_id, candidate)
    before = (trace_dir / "agent_events.jsonl").read_bytes()

    def reject(*args: object, **kwargs: object) -> dict:
        raise ValueError("raw PSFASCII audit failed")

    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", reject)
    with pytest.raises(ValueError, match="raw PSFASCII"):
        module.reconcile_pending_diagnostic(
            trace_dir, runs_root, _spec(), seed=0, template=tmp_path / "unused", template_sha256="0" * 64,
        )
    assert (trace_dir / "agent_events.jsonl").read_bytes() == before
    assert inspect_journal(trace_dir).pending_run_id == run_id


def test_real_reconciled_archive_reaudits_without_spectre() -> None:
    trace_dir = Path("results/runs/agent_diagnostic/20260927T010857Z_0b8f0e70")
    template = Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs")
    if not trace_dir.is_dir() or not template.is_file():
        pytest.skip("private reconciled OA diagnostic archive is unavailable")
    audit = inspect_journal(trace_dir, candidate_runs_root=Path("results/runs"))
    assert audit.disposition == "complete" and audit.candidate_bindings_verified
    assert audit.candidate_snapshots_verified and audit.spec_verified
    report = json.loads((trace_dir / "agent_reconciliation.json").read_text(encoding="utf-8"))
    assert report["candidate_run_id"] == "20260927T010857Z_d04f3583"
    assert report["spectre_dispatched_by_reconciliation"] is False
    assert report["spec_pass"] is None and report["not_lna_result"] is True
    from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate

    source = Path("results/runs") / report["candidate_run_relative"]
    evidence = audit_active_diagnostic_candidate(
        source, template=template,
        template_sha256="9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814",
    )
    assert evidence["points"] == 47 and evidence["not_lna_result"] is True
