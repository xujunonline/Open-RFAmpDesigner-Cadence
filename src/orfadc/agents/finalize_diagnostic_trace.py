from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.refiner import Refiner
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.schemas import Candidate, Spec


def finalize_diagnostic_trace(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    template: Path, template_sha256: str,
) -> dict:
    """Finish a journaled diagnostic refinement after independently auditing its archive."""
    with agent_run_lock(trace_dir):
        audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            audit.disposition not in {"interrupted", "terminal_snapshot_missing"}
            or not audit.spec_verified or not audit.candidate_snapshots_verified
            or not audit.candidate_bindings_verified or audit.pending_candidate_id is not None
            or audit.spec_id != spec.id or audit.seed != seed
            or audit.searches_used != 1 or audit.evaluations_used != 1
            or any((trace_dir / name).exists() or (trace_dir / name).is_symlink() for name in (
                "agent_trace.json", "agent_evaluation.json", "agent_reconciliation.json",
                "agent_terminal_recovery.json",
            ))
        ):
            raise ValueError("diagnostic journal is not eligible for terminal recovery")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        start = events[0]
        if (
            start.get("dispatch_mode") != "planned"
            or start["max_searches"] != 1 or start["max_evaluations"] != 1
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
            or [event["action"] for event in events] not in (
                ["RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate"],
                ["RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop"],
            )
            or (events[-1]["action"] == "Stop" and events[-1]["status"] != "budget_exhausted")
        ):
            raise ValueError("diagnostic journal is not a single planned refinement")
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 1 or len(snapshots[0]["candidates"]) != 1:
            raise ValueError("diagnostic journal lacks one candidate snapshot")
        candidate = Candidate(**snapshots[0]["candidates"][0])
        dispatch, refinement = events[2:4]
        if (candidate.candidate_id != dispatch["candidate_id"]
                or refinement["candidate_id"] != candidate.candidate_id
                or refinement["run_id"] != dispatch["run_id"]):
            raise ValueError("refined candidate differs from planned dispatch")
        if not runs_root.is_dir() or runs_root.is_symlink():
            raise ValueError("candidate runs root is missing or unsafe")
        root = runs_root.resolve()
        parts = (spec.id, f"seed{seed}", candidate.candidate_id, dispatch["run_id"])
        cursor = runs_root
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("bound candidate run path contains a symlink")
        run_dir = cursor
        if not run_dir.is_dir() or not run_dir.resolve().is_relative_to(root):
            raise ValueError("bound candidate archive is missing or unsafe")
        evidence = audit_active_diagnostic_candidate(
            run_dir, template=template, template_sha256=template_sha256,
        )
        if evidence.get("spec") != asdict(spec) or evidence.get("candidate") != candidate.to_dict():
            raise ValueError("diagnostic archive differs from the recorded candidate")
        manifest_digest = hashlib.sha256((run_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if manifest_digest != refinement["evidence_manifest_sha256"]:
            raise ValueError("refinement evidence digest differs from the archive")
        if Refiner().refine_from_run(candidate, run_dir, spec).status != refinement["status"]:
            raise ValueError("recorded refinement status does not match the archive")

        manager = Manager(max_searches=1, max_evaluations=1)
        manager.context = (spec.id, seed)
        manager.searches_used = 1
        manager.evaluations_used = 1
        manager.seen_ids = {candidate.candidate_id}
        manager.trace = events
        if events[-1]["action"] != "Stop":
            manager.attach_journal_for_resume(trace_dir)
            try:
                manager._record("Stop", status="budget_exhausted")
            finally:
                manager.close_journal()
        manager.save_trace(trace_dir)
        final_audit = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if not (final_audit.disposition == "complete" and final_audit.trace_verified
                and final_audit.candidate_bindings_verified and final_audit.spec_verified
                and final_audit.candidate_snapshots_verified):
            raise ValueError("recovered diagnostic trace failed final audit")
        report = {
            "schema_version": 1,
            "status": "finalized_existing_diagnostic_refinement",
            "spec_id": spec.id,
            "seed": seed,
            "candidate_id": candidate.candidate_id,
            "candidate_run_relative": run_dir.relative_to(runs_root).as_posix(),
            "candidate_evidence_manifest_sha256": manifest_digest,
            "refiner_status": refinement["status"],
            "spectre_dispatched_by_recovery": False,
            "not_lna_result": True,
            "spec_pass": None,
        }
        write_json(trace_dir / "agent_terminal_recovery.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Finish a journaled OA diagnostic refinement without rerunning Spectre")
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
        report = finalize_diagnostic_trace(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            template=args.template, template_sha256=args.template_sha256,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"terminal recovery rejected: {type(exc).__name__}")
    print(f"status={report['status']} refiner={report['refiner_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
