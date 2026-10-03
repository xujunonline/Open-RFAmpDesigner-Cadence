from __future__ import annotations

import argparse
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB,
    _PRIVATE_ROOT,
    _require_private_path,
    render_active_diagnostic_netlist,
    run_active_diagnostic_candidate,
)
from orfadc.schemas import Candidate, Spec


class DiagnosticSearcher:
    """One bounded OA common-source probe, not paper resource-allocation search."""

    def __init__(self, rd_ohm: float, vbias_v: float) -> None:
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in (rd_ohm, vbias_v)):
            raise ValueError("diagnostic values must be finite numbers")
        if not 50 <= rd_ohm <= 1000 or not 0.4 <= vbias_v <= 0.8:
            raise ValueError("diagnostic RD/VBIAS are outside the backend whitelist")
        self.rd_ohm = float(rd_ohm)
        self.vbias_v = float(vbias_v)

    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        return [Candidate(
            candidate_id=f"{spec.id}_seed{seed}_oa_diag",
            spec_id=spec.id,
            seed=seed,
            power_ratio_list=[],
            active_params={"rd_ohm": self.rd_ohm, "vbias_v": self.vbias_v},
            status="active_common_source_diagnostic",
        )]


def run_diagnostic_agent(
    config_path: Path,
    specs_path: Path,
    runs_root: Path,
    trace_root: Path,
    *,
    template: Path,
    template_sha256: str,
    spec_id: str,
    seed: int,
    rd_ohm: float,
    vbias_v: float,
    runner: RemoteRunner | None = None,
) -> tuple[Path, dict]:
    _require_private_path(runs_root)
    _require_private_path(trace_root)
    specs = {item.id: item for item in load_specs(specs_path)}
    if spec_id not in specs:
        raise ValueError("unknown spec ID")
    spec = specs[spec_id]
    searcher = DiagnosticSearcher(rd_ohm, vbias_v)
    candidate = searcher.search(spec, seed)[0]
    render_active_diagnostic_netlist(candidate, template, template_sha256)
    if available_physical_memory_gb() < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before agent execution")
    remote_config = load_remote_config(config_path)
    if runner is not None and runner.config != remote_config:
        raise ValueError("injected runner differs from the bound remote config")

    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    trace_dir.mkdir(exist_ok=False)
    evaluated: list[Path] = []

    def evaluate(proposed: Candidate, planned_run_id: str) -> Path:
        run_dir, _ = run_active_diagnostic_candidate(
            config_path, runs_root, spec, proposed,
            template=template, template_sha256=template_sha256,
            run_id=planned_run_id,
            remote_config=remote_config,
            runner=runner,
            preserve_uncertain_dispatch=True,
        )
        evaluated.append(run_dir)
        return run_dir

    try:
        outcome = execute_manager_planned(
            Manager(searcher=searcher, max_searches=1, max_evaluations=1),
            spec, evaluate, trace_dir, seed=seed, remote_config=remote_config,
        )
    except RemoteEvaluationUncertain:
        pending = inspect_journal(trace_dir)
        if (
            pending.disposition != "reconcile_pending_evaluation"
            or not pending.spec_verified or not pending.candidate_snapshots_verified
            or not pending.remote_identity_verified
            or pending.pending_candidate_id != candidate.candidate_id
            or pending.pending_run_id is None
        ):
            raise ValueError("uncertain remote dispatch lacks a verified pending journal") from None
        relative = Path(spec.id) / f"seed{seed}" / candidate.candidate_id / pending.pending_run_id
        index = {
            "schema_version": 1,
            "scope": "deterministic single-candidate OA diagnostic agent loop; not an LNA design agent",
            "spec_id": spec.id, "seed": seed, "candidate_id": candidate.candidate_id,
            "execution_status": "pending_remote_evaluation",
            "searches_used": pending.searches_used,
            "evaluations_used": pending.evaluations_used,
            "candidate_run_id": pending.pending_run_id,
            "candidate_run_relative": relative.as_posix(),
            "candidate_evidence_status": "pending",
            "candidate_binding_status": "unavailable",
            "candidate_snapshot_status": "verified",
            "spec_snapshot_status": "verified",
            "remote_identity_status": "verified",
            "candidate_backend_status": None,
            "candidate_simulation_status": None,
            "agent_trace": None,
            "agent_journal": "agent_events.jsonl",
            "agent_candidate_snapshots": "agent_candidates.jsonl",
            "agent_spec_snapshot": "agent_spec.json",
            "agent_remote_snapshot": "agent_remote.json",
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "agent_evaluation.json", index)
        return trace_dir, index
    audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if (
        audit.disposition != "complete" or not audit.trace_verified
        or not audit.candidate_snapshots_verified or not audit.spec_verified
        or not audit.remote_identity_verified
    ):
        raise ValueError("agent journal/trace verification failed")
    evidence_status = "not_run"
    candidate_run_id = None
    candidate_run_relative = None
    candidate_backend_status = None
    candidate_simulation_status = None
    if evaluated:
        candidate_run_id = evaluated[0].name
        candidate_run_relative = evaluated[0].relative_to(runs_root).as_posix()
        try:
            evidence = read_evidenced_metrics(evaluated[0])
            if evidence.get("status") in {"ok", "ok_with_warnings"}:
                evidence = audit_active_diagnostic_candidate(
                    evaluated[0], template=template, template_sha256=template_sha256,
                )
        except (OSError, ValueError, TypeError, KeyError):
            evidence_status = "invalid"
        else:
            evidence_status = "verified"
            candidate_backend_status = evidence["status"]
            candidate_simulation_status = evidence["simulation_status"]
    if evidence_status == "verified" and not audit.candidate_bindings_verified:
        raise ValueError("agent journal is not bound to the verified candidate run")
    index = {
        "schema_version": 1,
        "scope": "deterministic single-candidate OA diagnostic agent loop; not an LNA design agent",
        "spec_id": spec.id,
        "seed": seed,
        "candidate_id": candidate.candidate_id,
        "execution_status": outcome.status,
        "searches_used": outcome.searches_used,
        "evaluations_used": outcome.evaluations_used,
        "candidate_run_id": candidate_run_id,
        "candidate_run_relative": candidate_run_relative,
        "candidate_evidence_status": evidence_status,
        "candidate_binding_status": "verified" if audit.candidate_bindings_verified else "unavailable",
        "candidate_snapshot_status": "verified",
        "spec_snapshot_status": "verified",
        "remote_identity_status": "verified",
        "candidate_backend_status": candidate_backend_status,
        "candidate_simulation_status": candidate_simulation_status,
        "agent_trace": "agent_trace.json",
        "agent_journal": "agent_events.jsonl",
        "agent_candidate_snapshots": "agent_candidates.jsonl",
        "agent_spec_snapshot": "agent_spec.json",
        "agent_remote_snapshot": "agent_remote.json",
        "not_lna_result": True,
        "spec_pass": None,
    }
    write_json(trace_dir / "agent_evaluation.json", index)
    return trace_dir, index


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic OA diagnostic agent round")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "agent_diagnostic")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    try:
        trace_dir, index = run_diagnostic_agent(
            args.config, args.specs, args.runs_root, args.trace_root,
            template=args.template, template_sha256=args.template_sha256,
            spec_id=args.spec, seed=args.seed, rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={index['execution_status']} backend={index['candidate_backend_status']} evidence={index['candidate_evidence_status']}")
    print(f"trace_dir={trace_dir.resolve()}")
    return 0 if (
        index["candidate_evidence_status"] == "verified"
        and index["candidate_binding_status"] == "verified"
        and index["candidate_backend_status"] in {"ok", "ok_with_warnings"}
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
