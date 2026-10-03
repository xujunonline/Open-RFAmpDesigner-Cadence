from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.agents.journal import inspect_journal
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.config_loader import write_json
from orfadc.experiments import run_agent_diagnostic as module
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def test_diagnostic_searcher_only_emits_whitelisted_candidate() -> None:
    proposed = module.DiagnosticSearcher(130, 0.67).search(_spec(), 2)
    assert len(proposed) == 1
    assert proposed[0].active_params == {"rd_ohm": 130.0, "vbias_v": 0.67}
    assert proposed[0].seed == 2
    with pytest.raises(ValueError, match="whitelist"):
        module.DiagnosticSearcher(49, 0.67)
    with pytest.raises(ValueError, match="finite"):
        module.DiagnosticSearcher(float("nan"), 0.67)


def test_diagnostic_agent_links_mock_backend_evidence_without_accepting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    trace_root = runs_root / "agent"
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "validated")
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_remote_config", lambda path: RemoteCadenceConfig(
        host="example.org", user="student",
    ))

    def fake_backend(config_path: Path, root: Path, spec: Spec, candidate: Candidate, **kwargs):
        run_dir = root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / kwargs["run_id"]
        run_dir.mkdir(parents=True)
        payload = {
            "schema_version": 1, "status": "spectre_failed", "simulation_status": "failed",
            "circuit_class": "active_common_source_smoke", "not_lna_result": True,
            "spec_pass": None, "run_id": run_dir.name, "spec": asdict(spec),
            "candidate": candidate.to_dict(), "seed": candidate.seed, "timeout_seconds": 30,
        }
        write_json(run_dir / "metrics.json", payload)
        write_json(run_dir / "candidate.json", candidate.to_dict())
        write_evidence_manifest(run_dir, {"metrics": "metrics.json", "candidate": "candidate.json"})
        return run_dir, payload

    monkeypatch.setattr(module, "run_active_diagnostic_candidate", fake_backend)
    trace_dir, index = module.run_diagnostic_agent(
        tmp_path / "unused_config", tmp_path / "unused_specs", runs_root, trace_root,
        template=tmp_path / "unused_template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=130, vbias_v=0.67,
    )
    assert index["candidate_evidence_status"] == "verified"
    assert index["candidate_binding_status"] == "verified"
    assert index["candidate_snapshot_status"] == "verified"
    assert index["spec_snapshot_status"] == "verified"
    assert index["remote_identity_status"] == "verified"
    assert index["agent_remote_snapshot"] == "agent_remote.json"
    assert index["agent_candidate_snapshots"] == "agent_candidates.jsonl"
    assert index["agent_spec_snapshot"] == "agent_spec.json"
    assert index["candidate_backend_status"] == "spectre_failed"
    assert index["candidate_simulation_status"] == "failed"
    assert index["candidate_run_relative"] == f"S1/seed0/S1_seed0_oa_diag/{index['candidate_run_id']}"
    assert index["spec_pass"] is None
    assert index["searches_used"] == index["evaluations_used"] == 1
    trace = json.loads((trace_dir / "agent_trace.json").read_text(encoding="utf-8"))
    assert [event["action"] for event in trace["events"]] == [
        "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop"
    ]
    assert trace["events"][0]["dispatch_mode"] == "planned"
    assert trace["events"][2]["run_id"] == index["candidate_run_id"]
    assert trace["events"][-2]["status"] == "needs_evaluation"
    assert trace["events"][-2]["run_id"] == index["candidate_run_id"]
    assert len(trace["events"][-2]["evidence_manifest_sha256"]) == 64
    audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    assert (audit.candidate_bindings_verified and audit.candidate_snapshots_verified
            and audit.spec_verified and audit.remote_identity_verified)
    candidate_metrics = runs_root / index["candidate_run_relative"] / "metrics.json"
    candidate_metrics.write_text(candidate_metrics.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        inspect_journal(trace_dir, candidate_runs_root=runs_root)


def test_diagnostic_agent_memory_gate_prevents_trace_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    trace_root = runs_root / "agent"
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "validated")
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    with pytest.raises(RuntimeError, match="memory gate"):
        module.run_diagnostic_agent(
            tmp_path / "unused_config", tmp_path / "unused_specs", runs_root, trace_root,
            template=tmp_path / "unused_template", template_sha256="0" * 64,
            spec_id="S1", seed=0, rd_ohm=130, vbias_v=0.67,
        )
    assert not trace_root.exists()


def test_diagnostic_agent_reports_pending_dispatch_without_terminal_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "validated")
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_remote_config", lambda path: RemoteCadenceConfig(
        host="example.org", user="student",
    ))
    dispatched: list[str] = []

    def uncertain_backend(config_path: Path, root: Path, spec: Spec, candidate: Candidate, **kwargs):
        assert kwargs["preserve_uncertain_dispatch"] is True
        dispatched.append(kwargs["run_id"])
        raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain")

    monkeypatch.setattr(module, "run_active_diagnostic_candidate", uncertain_backend)
    trace_dir, index = module.run_diagnostic_agent(
        tmp_path / "config", tmp_path / "specs", runs_root, runs_root / "agent",
        template=tmp_path / "template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=130, vbias_v=0.67,
    )
    assert len(dispatched) == 1
    assert index["execution_status"] == "pending_remote_evaluation"
    assert index["candidate_run_id"] == dispatched[0]
    assert index["candidate_evidence_status"] == "pending"
    assert index["agent_trace"] is None
    assert index["spec_pass"] is None
    assert not (trace_dir / "agent_trace.json").exists()
    assert inspect_journal(trace_dir).disposition == "reconcile_pending_evaluation"
    assert json.loads((trace_dir / "agent_evaluation.json").read_text()) == index


def test_diagnostic_agent_does_not_accept_hash_only_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "validated")
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_remote_config", lambda path: RemoteCadenceConfig(
        host="example.org", user="student",
    ))

    def fake_backend(config_path: Path, root: Path, spec: Spec, candidate: Candidate, **kwargs):
        run_dir = root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / kwargs["run_id"]
        run_dir.mkdir(parents=True)
        payload = {
            "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
            "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
            "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
            "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
            "timeout_seconds": 30, "metrics": {"s21_db": 0.0},
        }
        write_json(run_dir / "metrics.json", payload)
        write_json(run_dir / "candidate.json", candidate.to_dict())
        (run_dir / "netlist.scs").write_text("mock netlist\n", encoding="ascii")
        (run_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="ascii")
        write_evidence_manifest(run_dir, {
            "metrics": "metrics.json", "candidate": "candidate.json",
            "netlist": "netlist.scs", "spectre_log": "spectre.log",
        })
        return run_dir, payload

    monkeypatch.setattr(module, "run_active_diagnostic_candidate", fake_backend)
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda *a, **k: (_ for _ in ()).throw(
        ValueError("raw PSFASCII audit failed")
    ))
    trace_dir, index = module.run_diagnostic_agent(
        tmp_path / "unused_config", tmp_path / "unused_specs", runs_root, runs_root / "agent",
        template=tmp_path / "unused_template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=130, vbias_v=0.67,
    )
    assert index["candidate_backend_status"] is None
    assert index["candidate_evidence_status"] == "invalid"
    assert inspect_journal(trace_dir, candidate_runs_root=runs_root).disposition == "complete"


@pytest.mark.parametrize(("backend_status", "exit_code"), [("spectre_failed", 1), ("ok_with_warnings", 0)])
def test_cli_exit_code_requires_successful_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_status: str, exit_code: int
) -> None:
    monkeypatch.setattr(module, "run_diagnostic_agent", lambda *args, **kwargs: (
        tmp_path, {"execution_status": "budget_exhausted", "candidate_evidence_status": "verified",
                   "candidate_binding_status": "verified", "candidate_backend_status": backend_status},
    ))
    monkeypatch.setattr(sys, "argv", ["run_agent_diagnostic", "--template", "unused",
                                      "--template-sha256", "0" * 64,
                                      "--rd-ohm", "130", "--vbias-v", "0.67"])
    assert module.main() == exit_code
