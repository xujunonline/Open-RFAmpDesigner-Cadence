from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents import finalize_diagnostic_trace as module
from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _archive(runs_root: Path, run_id: str, candidate: Candidate) -> Path:
    run_dir = runs_root / "S1" / "seed0" / candidate.candidate_id / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "metrics.json", {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "spec": asdict(_spec()), "candidate": candidate.to_dict(), "seed": 0,
        "timeout_seconds": 30, "metrics": {"s21_db": 0.0},
    })
    write_json(run_dir / "candidate.json", candidate.to_dict())
    (run_dir / "netlist.scs").write_text("test fixture\n", encoding="ascii")
    (run_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="ascii")
    write_evidence_manifest(run_dir, {
        "metrics": "metrics.json", "candidate": "candidate.json",
        "netlist": "netlist.scs", "spectre_log": "spectre.log",
    })
    return run_dir


@pytest.mark.parametrize("crash_at", ["stop", "trace"])
def test_finalize_only_audited_single_planned_refinement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash_at: str,
) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    archived: list[Path] = []

    def evaluate(candidate: Candidate, run_id: str) -> Path:
        path = _archive(runs_root, run_id, candidate)
        archived.append(path)
        return path

    if crash_at == "stop":
        original_record = Manager._record

        def crash_before_stop(self: Manager, action: str, **fields: object) -> None:
            if action == "Stop":
                raise KeyboardInterrupt()
            original_record(self, action, **fields)

        monkeypatch.setattr(Manager, "_record", crash_before_stop)
    else:
        def crash_before_trace(self: Manager, run_dir: Path) -> Path:
            raise KeyboardInterrupt()

        monkeypatch.setattr(Manager, "save_trace", crash_before_trace)
    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(Manager(), _spec(), evaluate, trace_dir)
    monkeypatch.undo()
    assert len(archived) == 1
    before = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    assert before.disposition == ("interrupted" if crash_at == "stop" else "terminal_snapshot_missing")
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda path, **_: read_evidenced_metrics(path))
    report = module.finalize_diagnostic_trace(
        trace_dir, runs_root, _spec(), seed=0,
        template=tmp_path / "unused", template_sha256="0" * 64,
    )
    assert report["spectre_dispatched_by_recovery"] is False
    assert report["spec_pass"] is None and report["not_lna_result"] is True
    assert report["refiner_status"] == "needs_evaluation"
    after = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    assert after.disposition == "complete" and after.trace_verified
    with pytest.raises(ValueError, match="not eligible"):
        module.finalize_diagnostic_trace(
            trace_dir, runs_root, _spec(), seed=0,
            template=tmp_path / "unused", template_sha256="0" * 64,
        )


def test_finalize_rejects_raw_audit_failure_without_writing_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    def evaluate(candidate: Candidate, run_id: str) -> Path:
        return _archive(runs_root, run_id, candidate)

    monkeypatch.setattr(Manager, "save_trace", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(Manager(), _spec(), evaluate, trace_dir)
    monkeypatch.undo()
    before = (trace_dir / "agent_events.jsonl").read_bytes()
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("raw audit failed")))
    with pytest.raises(ValueError, match="raw audit failed"):
        module.finalize_diagnostic_trace(
            trace_dir, runs_root, _spec(), seed=0,
            template=tmp_path / "unused", template_sha256="0" * 64,
        )
    assert (trace_dir / "agent_events.jsonl").read_bytes() == before
    assert not (trace_dir / "agent_trace.json").exists()


def test_finalize_rejects_refiner_status_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setattr(Manager, "save_trace", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        execute_manager_planned(
            Manager(), _spec(), lambda c, r: _archive(runs_root, r, c), trace_dir,
        )
    monkeypatch.undo()
    path = trace_dir / "agent_events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    events[3]["status"] = "retry_stage2"
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda p, **_: read_evidenced_metrics(p))
    with pytest.raises(ValueError, match="refinement status"):
        module.finalize_diagnostic_trace(
            trace_dir, runs_root, _spec(), seed=0,
            template=tmp_path / "unused", template_sha256="0" * 64,
        )
    assert not (trace_dir / "agent_trace.json").exists()


def test_real_archive_terminal_recovery_reaudits_without_spectre(tmp_path: Path) -> None:
    source = Path("results/runs/agent_diagnostic/20260927T010857Z_0b8f0e70")
    template = Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs")
    runs_root = Path("results/runs")
    if not source.is_dir() or not template.is_file():
        pytest.skip("private OA diagnostic archive is unavailable")
    trace_dir = tmp_path / "interrupted_trace"
    trace_dir.mkdir()
    for name in ("agent_spec.json", "agent_candidates.jsonl", "agent_events.jsonl"):
        shutil.copyfile(source / name, trace_dir / name)
    journal = trace_dir / "agent_events.jsonl"
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [item["action"] for item in events[-2:]] == ["RefineCandidate", "Stop"]
    journal.write_text("".join(json.dumps(event) + "\n" for event in events[:-1]), encoding="utf-8")
    actual_spec = Spec(**json.loads((trace_dir / "agent_spec.json").read_text(encoding="utf-8")))
    report = module.finalize_diagnostic_trace(
        trace_dir, runs_root, actual_spec, seed=0, template=template,
        template_sha256="9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814",
    )
    assert report["status"] == "finalized_existing_diagnostic_refinement"
    assert report["candidate_run_relative"].endswith("20260927T010857Z_d04f3583")
    assert report["spec_pass"] is None and report["spectre_dispatched_by_recovery"] is False
    assert inspect_journal(trace_dir, candidate_runs_root=runs_root).disposition == "complete"
