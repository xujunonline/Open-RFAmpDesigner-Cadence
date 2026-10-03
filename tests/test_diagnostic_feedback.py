from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents import diagnostic_feedback as feedback
from orfadc.agents import reconcile_pending_feedback as reconciler
from orfadc.agents import finalize_feedback_trace as finalizer
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.config_loader import write_json
from orfadc.experiments import audit_diagnostic_feedback_agent as auditor
from orfadc.experiments import run_diagnostic_feedback_agent as module
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "validated")
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_remote_config", lambda path: RemoteCadenceConfig(
        host="example.org", user="student",
    ))


def _fake_backend(root: Path, spec: Spec, candidate: Candidate, run_id: str) -> tuple[Path, dict]:
    run_dir = root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / run_id
    run_dir.mkdir(parents=True)
    result = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
        "timeout_seconds": 30,
        "metrics": {"s21_db": 0.0},
    }
    write_json(run_dir / "metrics.json", result)
    write_json(run_dir / "candidate.json", candidate.to_dict())
    (run_dir / "netlist.scs").write_text("mock netlist\n", encoding="ascii")
    (run_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="ascii")
    write_evidence_manifest(run_dir, {
        "metrics": "metrics.json", "candidate": "candidate.json",
        "netlist": "netlist.scs", "spectre_log": "spectre.log",
    })
    return run_dir, result


def _invoke(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "runs"
    root.mkdir(exist_ok=True)
    return module.run_diagnostic_feedback_agent(
        tmp_path / "config", tmp_path / "specs", root, root / "feedback",
        template=tmp_path / "template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=250, vbias_v=0.67,
    )


def test_searcher_preflight_does_not_consume_a_search() -> None:
    refiner = feedback.DiagnosticFeedbackRefiner(template=Path("unused"), template_sha256="0" * 64)
    searcher = feedback.DiagnosticFeedbackSearcher(refiner, rd_ohm=250, vbias_v=0.67)
    initial = searcher.initial_candidate(_spec(), 0)
    assert searcher.search_calls == 0
    assert searcher.search(_spec(), 0)[0] == initial
    assert searcher.search(_spec(), 0) == []
    with pytest.raises(ValueError, match="RD"):
        feedback.DiagnosticFeedbackSearcher(refiner, rd_ohm=1001, vbias_v=0.67)


def test_two_round_feedback_binds_raw_evidence_and_never_accepts_lna(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare(monkeypatch)
    monkeypatch.setattr(module, "run_active_diagnostic_candidate", lambda config, root, spec, candidate, **kw: (
        _fake_backend(root, spec, candidate, kw["run_id"])
    ))
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda run_dir, **kw: json.loads(
        (run_dir / "metrics.json").read_text(encoding="utf-8")
    ))
    monkeypatch.setattr(feedback, "audit_active_diagnostic_candidate", module.audit_active_diagnostic_candidate)
    trace_dir, report = _invoke(tmp_path)
    assert report["status"] == "verified_two_run_diagnostic_feedback"
    assert report["searches_used"] == report["evaluations_used"] == 2
    assert report["spec_pass"] is None and report["not_lna_result"] is True
    assert [item["rd_ohm"] for item in report["results"]] == [250.0, 275.0]
    root = tmp_path / "runs"
    audit = inspect_journal(trace_dir, candidate_runs_root=root)
    assert audit.disposition == "complete" and audit.candidate_bindings_verified
    assert audit.candidate_snapshots_verified and audit.remote_identity_verified
    events = json.loads((trace_dir / "agent_trace.json").read_text(encoding="utf-8"))["events"]
    assert [item["action"] for item in events] == [
        "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
        "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop",
    ]
    assert events[3]["status"] == "diagnostic_refinement_proposed"
    monkeypatch.setattr(auditor, "_require_private_path", lambda path: None)
    monkeypatch.setattr(auditor, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(auditor, "audit_active_diagnostic_candidate", module.audit_active_diagnostic_candidate)
    kwargs = {
        "template": tmp_path / "template", "template_sha256": "0" * 64,
        "specs_path": tmp_path / "specs",
    }
    assert auditor.audit_diagnostic_feedback_agent(trace_dir, root, **kwargs) == report
    monkeypatch.setattr(auditor, "load_specs", lambda path: [
        Spec("S1", 10.0, 0.2, 10.0, 12.0, 3.0, -15.0)
    ])
    with pytest.raises(ValueError, match="spec snapshot differs"):
        auditor.audit_diagnostic_feedback_agent(trace_dir, root, **kwargs)
    monkeypatch.setattr(auditor, "load_specs", lambda path: [_spec()])
    summary = trace_dir / "diagnostic_feedback_summary.json"
    saved = summary.read_text(encoding="utf-8")
    altered = json.loads(saved)
    altered["results"][1]["s21_db"] = 99.0
    write_json(summary, altered)
    with pytest.raises(ValueError, match="summary differs"):
        auditor.audit_diagnostic_feedback_agent(trace_dir, root, **kwargs)
    summary.write_text(saved, encoding="utf-8")
    second = root / "S1" / "seed0" / report["results"][1]["candidate_id"] / report["results"][1]["run_id"]
    with (second / "metrics.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        auditor.audit_diagnostic_feedback_agent(trace_dir, root, **kwargs)


def test_raw_audit_failure_prevents_second_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare(monkeypatch)
    monkeypatch.setattr(module, "run_active_diagnostic_candidate", lambda config, root, spec, candidate, **kw: (
        _fake_backend(root, spec, candidate, kw["run_id"])
    ))

    def failed_audit(*args, **kwargs):
        raise ValueError("raw source mismatch")

    monkeypatch.setattr(feedback, "audit_active_diagnostic_candidate", failed_audit)
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", failed_audit)
    trace_dir, report = _invoke(tmp_path)
    assert report["status"] == "diagnostic_feedback_incomplete"
    assert report["evaluations_used"] == 1
    assert report["results"][0]["source_status"] == "invalid"
    assert inspect_journal(trace_dir, candidate_runs_root=tmp_path / "runs").disposition == "complete"


def test_uncertain_second_dispatch_remains_pending_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare(monkeypatch)
    calls: list[str] = []

    def backend(config: Path, root: Path, spec: Spec, candidate: Candidate, **kw):
        calls.append(kw["run_id"])
        if len(calls) == 2:
            raise RemoteEvaluationUncertain("controller disconnected")
        return _fake_backend(root, spec, candidate, kw["run_id"])

    monkeypatch.setattr(module, "run_active_diagnostic_candidate", backend)
    monkeypatch.setattr(feedback, "audit_active_diagnostic_candidate", lambda run_dir, **kw: json.loads(
        (run_dir / "metrics.json").read_text(encoding="utf-8")
    ))
    trace_dir, report = _invoke(tmp_path)
    assert len(calls) == 2 and report["evaluations_used"] == 2
    assert report["status"] == "pending_remote_evaluation"
    assert report["pending_run_id"] == calls[-1]
    assert report["spec_pass"] is None
    assert not (trace_dir / "agent_trace.json").exists()
    assert inspect_journal(trace_dir, candidate_runs_root=tmp_path / "runs").disposition == "reconcile_pending_evaluation"


def _second_round_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Candidate, str]:
    _prepare(monkeypatch)
    pending: list[tuple[Candidate, str]] = []

    def backend(config: Path, root: Path, spec: Spec, candidate: Candidate, **kw):
        if candidate.candidate_id.endswith("feedback1"):
            pending.append((candidate, kw["run_id"]))
            raise RemoteEvaluationUncertain("controller disconnected")
        return _fake_backend(root, spec, candidate, kw["run_id"])

    monkeypatch.setattr(module, "run_active_diagnostic_candidate", backend)
    monkeypatch.setattr(feedback, "audit_active_diagnostic_candidate", lambda run_dir, **kw: json.loads(
        (run_dir / "metrics.json").read_text(encoding="utf-8")
    ))
    trace_dir, report = _invoke(tmp_path)
    assert report["status"] == "pending_remote_evaluation" and len(pending) == 1
    return trace_dir, tmp_path / "runs", pending[0][0], pending[0][1]


def _patch_reconcile_auditors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconciler, "_require_private_path", lambda path: None)
    monkeypatch.setattr(reconciler, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(reconciler, "audit_active_diagnostic_candidate", lambda run_dir, **kw: json.loads(
        (run_dir / "metrics.json").read_text(encoding="utf-8")
    ))
    monkeypatch.setattr(auditor, "_require_private_path", lambda path: None)
    monkeypatch.setattr(auditor, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(auditor, "audit_active_diagnostic_candidate", reconciler.audit_active_diagnostic_candidate)


def _reconcile(trace_dir: Path, root: Path, tmp_path: Path) -> dict:
    return reconciler.reconcile_pending_feedback(
        trace_dir, root, _spec(), seed=0,
        template=tmp_path / "template", template_sha256="0" * 64,
        specs_path=tmp_path / "specs",
    )


def test_second_round_adopts_existing_archive_once_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir, root, candidate, run_id = _second_round_pending(tmp_path, monkeypatch)
    _fake_backend(root, _spec(), candidate, run_id)
    _patch_reconcile_auditors(monkeypatch)
    report = _reconcile(trace_dir, root, tmp_path)
    assert report["status"] == "reconciled_existing_second_feedback_archive"
    assert report["second_run_id"] == run_id
    assert report["refiner_status"] == "needs_evaluation"
    assert report["spectre_dispatched_by_reconciliation"] is False
    assert report["not_lna_result"] is True and report["spec_pass"] is None
    assert inspect_journal(trace_dir, candidate_runs_root=root).disposition == "complete"
    summary = auditor.audit_diagnostic_feedback_agent(
        trace_dir, root, template=tmp_path / "template", template_sha256="0" * 64,
        specs_path=tmp_path / "specs",
    )
    assert summary["status"] == "verified_two_run_diagnostic_feedback"
    with pytest.raises(ValueError, match="not an eligible"):
        _reconcile(trace_dir, root, tmp_path)


def test_second_round_missing_archive_leaves_planned_journal_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir, root, _, run_id = _second_round_pending(tmp_path, monkeypatch)
    _patch_reconcile_auditors(monkeypatch)
    original = (trace_dir / "agent_events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="archive is absent"):
        _reconcile(trace_dir, root, tmp_path)
    assert (trace_dir / "agent_events.jsonl").read_bytes() == original
    assert inspect_journal(trace_dir, candidate_runs_root=root).pending_run_id == run_id
    assert not (trace_dir / "agent_trace.json").exists()


def test_second_round_rejects_changed_first_source_without_journal_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir, root, candidate, run_id = _second_round_pending(tmp_path, monkeypatch)
    _fake_backend(root, _spec(), candidate, run_id)
    _patch_reconcile_auditors(monkeypatch)
    original = (trace_dir / "agent_events.jsonl").read_bytes()
    first_run = next((root / "S1" / "seed0" / "S1_seed0_oa_feedback0").iterdir())
    with (first_run / "metrics.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        _reconcile(trace_dir, root, tmp_path)
    assert (trace_dir / "agent_events.jsonl").read_bytes() == original
    assert not (trace_dir / "agent_trace.json").exists()


def test_second_round_rejects_spec_file_drift_before_journal_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir, root, candidate, run_id = _second_round_pending(tmp_path, monkeypatch)
    _fake_backend(root, _spec(), candidate, run_id)
    _patch_reconcile_auditors(monkeypatch)
    monkeypatch.setattr(reconciler, "load_specs", lambda path: [
        Spec("S1", 10.0, 0.2, 10.0, 12.0, 3.0, -15.0)
    ])
    original = (trace_dir / "agent_events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="spec file differs"):
        _reconcile(trace_dir, root, tmp_path)
    assert (trace_dir / "agent_events.jsonl").read_bytes() == original
    assert not (trace_dir / "agent_trace.json").exists()


def test_completed_real_feedback_trace_is_not_eligible_for_reconciliation() -> None:
    trace_dir = Path("results/runs/agent_diagnostic_feedback/20260927T165301Z_288868af")
    if not trace_dir.is_dir():
        pytest.skip("private completed feedback trace is unavailable")
    root = Path("results/runs")
    spec = next(item for item in module.load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    before = (trace_dir / "agent_events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="not an eligible"):
        reconciler.reconcile_pending_feedback(
            trace_dir, root, spec, seed=0,
            template=Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"),
            template_sha256="9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814",
            specs_path=Path("config/specs_table_iii.yaml"),
        )
    assert (trace_dir / "agent_events.jsonl").read_bytes() == before


def _refined_second_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stop_written: bool,
    trace_written: bool = False,
) -> tuple[Path, Path]:
    trace_dir, root, candidate, run_id = _second_round_pending(tmp_path, monkeypatch)
    second_archive, _ = _fake_backend(root, _spec(), candidate, run_id)
    _patch_reconcile_auditors(monkeypatch)
    events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    manager = Manager(max_searches=2, max_evaluations=2)
    manager.context = ("S1", 0)
    manager.searches_used = manager.evaluations_used = 2
    manager.seen_ids = {"S1_seed0_oa_feedback0", candidate.candidate_id}
    manager.pending = {candidate.candidate_id: candidate}
    manager.pending_run_ids = {candidate.candidate_id: run_id}
    manager.trace = events
    manager.attach_journal_for_resume(trace_dir)
    try:
        assert manager.record_result(candidate, second_archive, _spec()).status == "needs_evaluation"
        if stop_written:
            manager._record("Stop", status="budget_exhausted")
    finally:
        manager.close_journal()
    if trace_written:
        assert stop_written
        manager.save_trace(trace_dir)
    assert inspect_journal(trace_dir, candidate_runs_root=root).disposition == (
        "complete" if trace_written else "terminal_snapshot_missing" if stop_written else "interrupted"
    )
    return trace_dir, root


@pytest.mark.parametrize(("stop_written", "trace_written"), [
    (False, False), (True, False), (True, True),
])
def test_terminal_feedback_refinement_finalizes_without_reevaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_written: bool, trace_written: bool,
) -> None:
    trace_dir, root = _refined_second_round(
        tmp_path, monkeypatch, stop_written=stop_written, trace_written=trace_written,
    )
    monkeypatch.setattr(finalizer, "_require_private_path", lambda path: None)
    monkeypatch.setattr(finalizer, "load_specs", lambda path: [_spec()])
    report = finalizer.finalize_feedback_trace(
        trace_dir, root, _spec(), seed=0, template=tmp_path / "template",
        template_sha256="0" * 64, specs_path=tmp_path / "specs",
    )
    assert report["status"] == "finalized_existing_second_feedback_refinement"
    assert report["spectre_dispatched_by_recovery"] is False
    assert report["spec_pass"] is None and report["not_lna_result"] is True
    assert inspect_journal(trace_dir, candidate_runs_root=root).disposition == "complete"
    with pytest.raises(ValueError, match="not eligible"):
        finalizer.finalize_feedback_trace(
            trace_dir, root, _spec(), seed=0, template=tmp_path / "template",
            template_sha256="0" * 64, specs_path=tmp_path / "specs",
        )


def test_terminal_feedback_refinement_rejects_changed_source_without_journal_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir, root = _refined_second_round(tmp_path, monkeypatch, stop_written=False)
    monkeypatch.setattr(finalizer, "_require_private_path", lambda path: None)
    monkeypatch.setattr(finalizer, "load_specs", lambda path: [_spec()])
    original = (trace_dir / "agent_events.jsonl").read_bytes()
    second = next((root / "S1" / "seed0" / "S1_seed0_oa_feedback1").iterdir())
    with (second / "metrics.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        finalizer.finalize_feedback_trace(
            trace_dir, root, _spec(), seed=0, template=tmp_path / "template",
            template_sha256="0" * 64, specs_path=tmp_path / "specs",
        )
    assert (trace_dir / "agent_events.jsonl").read_bytes() == original
    assert not (trace_dir / "agent_trace.json").exists()
