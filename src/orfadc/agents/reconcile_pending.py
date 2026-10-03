from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.audit_failed_active_diagnostic import (
    FAILURE_RECOVERY_MODE, audit_failed_active_diagnostic,
)
from orfadc.schemas import Candidate, Spec


def _verify_pending_evaluation_snapshot(
    trace_dir: Path, spec: Spec, seed: int, candidate: Candidate, run_id: str,
) -> None:
    path = trace_dir / "agent_evaluation.json"
    if not path.exists() and not path.is_symlink():
        return  # Older interrupted planned runs did not publish this index.
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError("pending evaluation snapshot is unsafe")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("pending evaluation snapshot is invalid") from exc
    expected = {
        "schema_version": 1,
        "scope": "deterministic single-candidate OA diagnostic agent loop; not an LNA design agent",
        "spec_id": spec.id, "seed": seed, "candidate_id": candidate.candidate_id,
        "execution_status": "pending_remote_evaluation",
        "searches_used": 1, "evaluations_used": 1,
        "candidate_run_id": run_id,
        "candidate_run_relative": (
            PurePosixPath(spec.id) / f"seed{seed}" / candidate.candidate_id / run_id
        ).as_posix(),
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
    if saved != expected:
        raise ValueError("pending evaluation snapshot differs from the planned journal")


def reconcile_pending_diagnostic(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    template: Path, template_sha256: str,
) -> dict:
    """Adopt one completed RD/VBIAS archive; never dispatch or retry Spectre."""
    with agent_run_lock(trace_dir):
        from orfadc.agents.quarantine_pending import require_not_quarantined
        require_not_quarantined(trace_dir)
        audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            audit.disposition != "reconcile_pending_evaluation"
            or not audit.spec_verified or not audit.candidate_snapshots_verified
            or audit.pending_run_id is None or audit.pending_candidate_id is None
            or audit.spec_id != spec.id or audit.seed != seed
            or audit.searches_used != 1 or audit.evaluations_used != 1
            or (trace_dir / "agent_trace.json").exists()
            or (trace_dir / "agent_reconciliation.json").exists()
        ):
            raise ValueError("agent pending diagnostic run is not eligible for archive reconciliation")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(encoding="utf-8").splitlines()]
        start = events[0]
        if (
            start.get("dispatch_mode") != "planned"
            or start["max_searches"] != 1 or start["max_evaluations"] != 1
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        ):
            raise ValueError("agent pending run lacks a matching planned dispatch context")
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 1 or len(snapshots[0]["candidates"]) != 1:
            raise ValueError("agent pending diagnostic does not have one candidate snapshot")
        candidate = Candidate(**snapshots[0]["candidates"][0])
        if candidate.candidate_id != audit.pending_candidate_id:
            raise ValueError("agent pending candidate differs from its snapshot")
        _verify_pending_evaluation_snapshot(
            trace_dir, spec, seed, candidate, audit.pending_run_id,
        )
        if not isinstance(runs_root, Path) or not runs_root.is_dir() or runs_root.is_symlink():
            raise ValueError("candidate runs root is missing or unsafe")
        root = runs_root.resolve()
        parts = (spec.id, f"seed{seed}", candidate.candidate_id, audit.pending_run_id)
        cursor = runs_root
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("pending candidate run path contains a symlink")
        run_dir = cursor
        if not run_dir.is_dir() or not run_dir.resolve().is_relative_to(root):
            raise ValueError("planned candidate archive is absent")
        envelope = read_evidenced_metrics(run_dir)
        auditor = (
            audit_failed_active_diagnostic
            if envelope.get("recovery_mode") == FAILURE_RECOVERY_MODE
            else audit_active_diagnostic_candidate
        )
        evidence = auditor(run_dir, template=template, template_sha256=template_sha256)
        if evidence.get("spec") != asdict(spec) or evidence.get("candidate") != candidate.to_dict():
            raise ValueError("planned candidate archive differs from the pending proposal")
        if evidence.get("recovery_mode") in {"remote_quiescent_download_v1", FAILURE_RECOVERY_MODE}:
            if not audit.remote_identity_verified:
                raise ValueError("recovered archive lacks a verified remote identity binding")
            identity_digest = start.get("remote_identity_sha256")
            identity = read_remote_identity_snapshot(trace_dir, identity_digest)
            remote_name = (
                f"rf_active_{spec.id}_seed{seed}_{candidate.candidate_id}_{audit.pending_run_id}"
            )
            remote_dir = str(PurePosixPath(identity["remote_root"]) / remote_name)
            provenance = json.loads((run_dir / "recovery_provenance.json").read_text(encoding="utf-8"))
            if (
                provenance["trace_id"] != trace_dir.name
                or provenance["remote_identity_sha256"] != identity_digest
                or provenance["remote_dir_sha256"] != hashlib.sha256(remote_dir.encode("utf-8")).hexdigest()
            ):
                raise ValueError("recovered archive provenance differs from the planned dispatch")
        manager = Manager(max_searches=1, max_evaluations=1)
        manager.context = (spec.id, seed)
        manager.searches_used = 1
        manager.evaluations_used = 1
        manager.seen_ids = {candidate.candidate_id}
        manager.pending = {candidate.candidate_id: candidate}
        manager.pending_run_ids = {candidate.candidate_id: audit.pending_run_id}
        manager.trace = events
        manager.attach_journal_for_resume(trace_dir)
        try:
            refined = manager.record_result(candidate, run_dir, spec)
            manager._record("Stop", status="budget_exhausted")
        finally:
            manager.close_journal()
        manager.save_trace(trace_dir)
        final_audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if not (
            final_audit.disposition == "complete" and final_audit.trace_verified
            and final_audit.candidate_bindings_verified and final_audit.candidate_snapshots_verified
            and final_audit.spec_verified and final_audit.pending_run_id is None
        ):
            raise ValueError("reconciled agent journal did not pass final audit")
        manifest_digest = hashlib.sha256((run_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        report = {
            "schema_version": 1,
            "status": (
                "reconciled_terminal_diagnostic_failure"
                if evidence.get("recovery_mode") == FAILURE_RECOVERY_MODE
                else "reconciled_existing_diagnostic_archive"
            ),
            "spec_id": spec.id, "seed": seed, "candidate_id": candidate.candidate_id,
            "candidate_run_id": run_dir.name,
            "candidate_run_relative": run_dir.relative_to(runs_root).as_posix(),
            "candidate_evidence_manifest_sha256": manifest_digest,
            "refiner_status": refined.status,
            "spectre_dispatched_by_reconciliation": False,
            "recovery_mode": evidence.get("recovery_mode"),
            "simulation_status": evidence.get("simulation_status"),
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "agent_reconciliation.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Adopt one completed planned OA diagnostic archive without rerunning Spectre")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=Path("results/runs"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown spec ID")
    try:
        result = reconcile_pending_diagnostic(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            template=args.template, template_sha256=args.template_sha256,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"pending reconciliation rejected: {type(exc).__name__}")
    print(f"status={result['status']} run_id={result['candidate_run_id']} refiner={result['refiner_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
