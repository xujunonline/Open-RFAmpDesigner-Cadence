from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.reconcile_pending_feedback import (
    _audit_source, _check_recovery_provenance, _source_dir,
)
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_diagnostic_feedback_agent import (
    audit_diagnostic_feedback_agent, rebuild_diagnostic_feedback_summary,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Candidate, Spec


def finalize_feedback_trace(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    template: Path, template_sha256: str, specs_path: Path,
) -> dict:
    """Finish an already journaled second refinement without evaluator dispatch."""
    for path in (trace_dir, runs_root, template):
        _require_private_path(path)
    if {item.id: item for item in load_specs(specs_path)}.get(spec.id) != spec:
        raise ValueError("feedback terminal recovery spec file differs")
    with agent_run_lock(trace_dir):
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition not in {"interrupted", "terminal_snapshot_missing", "complete"}
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified or not journal.candidate_bindings_verified
            or journal.pending_candidate_id is not None
            or journal.spec_id != spec.id or journal.seed != seed
            or journal.searches_used != 2 or journal.evaluations_used != 2
            or any((trace_dir / name).exists() or (trace_dir / name).is_symlink() for name in (
                "diagnostic_feedback_summary.json", "feedback_reconciliation.json",
                "feedback_terminal_recovery.json",
            ))
        ):
            raise ValueError("feedback journal is not eligible for terminal snapshot recovery")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        actions = [item["action"] for item in events]
        base = [
            "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
            "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
        ]
        if (
            actions not in (base, [*base, "Stop"])
            or events[3]["status"] != "diagnostic_refinement_proposed"
            or events[6]["status"] != "needs_evaluation"
            or (actions[-1] == "Stop" and events[-1]["status"] != "budget_exhausted")
        ):
            raise ValueError("feedback terminal journal has an incompatible schedule")
        start = events[0]
        if (
            start.get("dispatch_mode") != "planned"
            or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        ):
            raise ValueError("feedback terminal journal has an incompatible spec context")
        identity_digest = start["remote_identity_sha256"]
        identity = read_remote_identity_snapshot(trace_dir, identity_digest)
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 2 or any(len(item["candidates"]) != 1 for item in snapshots):
            raise ValueError("feedback terminal journal lacks two candidate snapshots")
        first, second = (Candidate(**item["candidates"][0]) for item in snapshots)
        if (
            first.candidate_id != f"{spec.id}_seed{seed}_oa_feedback0"
            or second.candidate_id != f"{spec.id}_seed{seed}_oa_feedback1"
            or any(candidate.spec_id != spec.id or candidate.seed != seed
                   or candidate.status != "active_common_source_diagnostic"
                   or candidate.notes or candidate.power_ratio_list or candidate.passive_params
                   or candidate.sim_result is not None
                   or set(candidate.active_params) != {"rd_ohm", "vbias_v"}
                   for candidate in (first, second))
        ):
            raise ValueError("feedback terminal candidates differ from their snapshots")
        for candidate, dispatch, refinement in (
            (first, events[2], events[3]), (second, events[5], events[6]),
        ):
            if (
                dispatch["candidate_id"] != candidate.candidate_id
                or refinement["candidate_id"] != candidate.candidate_id
                or refinement["run_id"] != dispatch["run_id"]
            ):
                raise ValueError("feedback terminal candidate differs from planned dispatch")
        first_dir = _source_dir(runs_root, spec, first, events[2]["run_id"])
        second_dir = _source_dir(runs_root, spec, second, events[5]["run_id"])
        first_evidence, first_digest = _audit_source(
            first_dir, spec, first, template=template, template_sha256=template_sha256,
        )
        second_evidence, second_digest = _audit_source(
            second_dir, spec, second, template=template, template_sha256=template_sha256,
        )
        for candidate, run_dir, evidence, digest, refinement in (
            (first, first_dir, first_evidence, first_digest, events[3]),
            (second, second_dir, second_evidence, second_digest, events[6]),
        ):
            _check_recovery_provenance(
                run_dir, evidence, trace_dir, identity, identity_digest, candidate,
            )
            if refinement["evidence_manifest_sha256"] != digest:
                raise ValueError("feedback terminal source differs from its journal binding")
        gain = first_evidence["metrics"].get("s21_db")
        if (
            type(gain) not in {int, float} or not math.isfinite(gain)
            or gain >= spec.gain_db
            or second.active_params["rd_ohm"] != round(first.active_params["rd_ohm"] * 1.1, 9)
            or second.active_params["vbias_v"] != first.active_params["vbias_v"]
        ):
            raise ValueError("feedback terminal second candidate lacks first-run justification")
        manager = Manager(max_searches=2, max_evaluations=2)
        manager.context = (spec.id, seed)
        manager.searches_used = manager.evaluations_used = 2
        manager.seen_ids = {first.candidate_id, second.candidate_id}
        manager.trace = events
        if actions[-1] != "Stop":
            manager.attach_journal_for_resume(trace_dir)
            try:
                manager._record("Stop", status="budget_exhausted")
            finally:
                manager.close_journal()
        if journal.disposition != "complete":
            manager.save_trace(trace_dir)
        summary = rebuild_diagnostic_feedback_summary(
            trace_dir, runs_root, template=template,
            template_sha256=template_sha256, specs_path=specs_path,
        )
        write_json(trace_dir / "diagnostic_feedback_summary.json", summary)
        if audit_diagnostic_feedback_agent(
            trace_dir, runs_root, template=template,
            template_sha256=template_sha256, specs_path=specs_path,
        ) != summary:
            raise ValueError("terminal feedback summary differs from independent source audit")
        report = {
            "schema_version": 1, "status": "finalized_existing_second_feedback_refinement",
            "trace_id": trace_dir.name, "first_run_id": first_dir.name,
            "second_run_id": second_dir.name,
            "second_manifest_sha256": second_digest,
            "spectre_dispatched_by_recovery": False,
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_terminal_recovery.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Finish a journaled second OA feedback refinement without Spectre")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown feedback spec")
    try:
        report = finalize_feedback_trace(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            template=args.template, template_sha256=args.template_sha256,
            specs_path=args.specs,
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        parser.error(f"feedback terminal recovery rejected: {type(exc).__name__}")
    print(f"status={report['status']} run_id={report['second_run_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
