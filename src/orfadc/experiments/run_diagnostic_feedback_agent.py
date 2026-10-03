from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.agents.diagnostic_feedback import DiagnosticFeedbackRefiner, DiagnosticFeedbackSearcher
from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
    render_active_diagnostic_netlist, run_active_diagnostic_candidate,
)
from orfadc.schemas import Candidate


def run_diagnostic_feedback_agent(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path, *,
    template: Path, template_sha256: str, spec_id: str, seed: int,
    rd_ohm: float, vbias_v: float,
) -> tuple[Path, dict]:
    for path in (runs_root, trace_root, template):
        _require_private_path(path)
    specs = {item.id: item for item in load_specs(specs_path)}
    if spec_id not in specs:
        raise ValueError("unknown diagnostic spec ID")
    spec = specs[spec_id]
    refiner = DiagnosticFeedbackRefiner(template=template, template_sha256=template_sha256)
    searcher = DiagnosticFeedbackSearcher(refiner, rd_ohm=rd_ohm, vbias_v=vbias_v)
    initial = searcher.initial_candidate(spec, seed)
    render_active_diagnostic_netlist(initial, template, template_sha256)
    if available_physical_memory_gb() < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before feedback agent")
    remote_config = load_remote_config(config_path)
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    trace_dir.mkdir(exist_ok=False)
    evaluated: list[Path] = []

    def evaluate(candidate: Candidate, run_id: str) -> Path:
        run_dir, _ = run_active_diagnostic_candidate(
            config_path, runs_root, spec, candidate,
            template=template, template_sha256=template_sha256,
            run_id=run_id, remote_config=remote_config,
            preserve_uncertain_dispatch=True,
        )
        evaluated.append(run_dir)
        return run_dir

    try:
        outcome = execute_manager_planned(
            Manager(searcher=searcher, refiner=refiner, max_searches=2, max_evaluations=2),
            spec, evaluate, trace_dir, seed=seed, remote_config=remote_config,
        )
    except RemoteEvaluationUncertain:
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition != "reconcile_pending_evaluation"
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified or not journal.pending_run_id
        ):
            raise ValueError("feedback agent uncertainty lacks a verified pending journal") from None
        report = {
            "schema_version": 1, "status": "pending_remote_evaluation",
            "trace_id": trace_dir.name, "pending_run_id": journal.pending_run_id,
            "evaluations_used": journal.evaluations_used,
            "recovery_status": "manual_reconciliation_required_no_automatic_retry",
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_pending.json", report)
        return trace_dir, report
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if (
        journal.disposition != "complete" or not journal.trace_verified
        or not journal.spec_verified or not journal.candidate_snapshots_verified
        or not journal.remote_identity_verified
    ):
        raise ValueError("feedback agent journal is incomplete or unbound")
    results = []
    for run_dir in evaluated:
        try:
            evidence = audit_active_diagnostic_candidate(
                run_dir, template=template, template_sha256=template_sha256,
            )
        except (OSError, ValueError, TypeError, KeyError):
            results.append({"run_id": run_dir.name, "source_status": "invalid"})
        else:
            results.append({
                "run_id": run_dir.name, "source_status": "raw_audited",
                "candidate_id": evidence["candidate"]["candidate_id"],
                "rd_ohm": evidence["candidate"]["active_params"]["rd_ohm"],
                "vbias_v": evidence["candidate"]["active_params"]["vbias_v"],
                "s21_db": evidence["metrics"]["s21_db"],
                "manifest_sha256": hashlib.sha256(
                    (run_dir / "evidence_manifest.json").read_bytes()
                ).hexdigest(),
                "not_lna_result": evidence["not_lna_result"],
                "spec_pass": evidence["spec_pass"],
            })
    linked = (
        len(results) == 2
        and all(row.get("source_status") == "raw_audited" and row["not_lna_result"] is True
                and row["spec_pass"] is None for row in results)
        and searcher.used_proposal is not None
        and searcher.used_proposal.parent_run_id == results[0]["run_id"]
        and searcher.used_proposal.parent_manifest_sha256 == results[0]["manifest_sha256"]
        and searcher.used_proposal.rd_ohm == results[1]["rd_ohm"]
        and searcher.used_proposal.vbias_v == results[1]["vbias_v"]
        and results[1]["rd_ohm"] > results[0]["rd_ohm"]
        and journal.candidate_bindings_verified
        and outcome.searches_used == outcome.evaluations_used == 2
    )
    report = {
        "schema_version": 1,
        "status": "verified_two_run_diagnostic_feedback" if linked else "diagnostic_feedback_incomplete",
        "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
        "searches_used": outcome.searches_used,
        "evaluations_used": outcome.evaluations_used,
        "candidate_bindings_verified": journal.candidate_bindings_verified,
        "parent_run_id": searcher.used_proposal.parent_run_id if searcher.used_proposal else None,
        "parent_manifest_sha256": (
            searcher.used_proposal.parent_manifest_sha256 if searcher.used_proposal else None
        ),
        "results": results,
        "not_lna_result": True, "spec_pass": None,
    }
    write_json(trace_dir / "diagnostic_feedback_summary.json", report)
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two evidence-gated OA common-source diagnostic agent rounds")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "agent_diagnostic_feedback")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    try:
        trace_dir, report = run_diagnostic_feedback_agent(
            args.config, args.specs, args.runs_root, args.trace_root,
            template=args.template, template_sha256=args.template_sha256,
            spec_id=args.spec, seed=args.seed, rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(
        f"trace_dir={trace_dir.resolve()} status={report['status']} "
        f"evaluations={report['evaluations_used']}"
    )
    return 0 if report["status"] == "verified_two_run_diagnostic_feedback" else 1


if __name__ == "__main__":
    raise SystemExit(main())
