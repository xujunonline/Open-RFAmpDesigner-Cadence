from __future__ import annotations

import argparse
import json
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.reconcile_pending_teaching_three_stage import _audited_source
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.agents.teaching_three_stage_feedback import TeachingThreeStageSearcher
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback, build_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage_refinement import _proposal
from orfadc.schemas import Candidate, Spec


_BASE_ACTIONS = (
    "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
    "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
)


def finalize_teaching_three_stage_agent(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int, specs_path: Path,
) -> dict:
    """Close a journaled second refinement from its two existing source archives."""
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    if {item.id: item for item in load_specs(specs_path)}.get(spec.id) != spec:
        raise ValueError("terminal teaching spec differs from the planned spec")
    with agent_run_lock(trace_dir):
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition not in {"interrupted", "terminal_snapshot_missing", "complete"}
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified or not journal.candidate_bindings_verified
            or journal.pending_candidate_id is not None
            or journal.spec_id != spec.id or journal.seed != seed
            or journal.searches_used != 2 or journal.evaluations_used != 2
        ):
            raise ValueError("teaching trace has no eligible journaled second refinement")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        actions = tuple(item.get("action") for item in events)
        if (
            actions not in {_BASE_ACTIONS, (*_BASE_ACTIONS, "Stop")}
            or events[3].get("status") != "teaching_refinement_proposed"
            or events[6].get("status") != "needs_evaluation"
            or (actions[-1] == "Stop" and events[-1].get("status") != "budget_exhausted")
        ):
            raise ValueError("teaching terminal journal differs from two-run feedback")
        start = events[0]
        if (
            start.get("dispatch_mode") != "planned"
            or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        ):
            raise ValueError("teaching terminal journal has an incompatible planned context")
        identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 2 or any(len(item.get("candidates", [])) != 1 for item in snapshots):
            raise ValueError("teaching terminal journal lacks two bound candidate snapshots")
        first, second = (Candidate(**item["candidates"][0]) for item in snapshots)
        if first.to_dict() != TeachingThreeStageSearcher.initial_candidate(spec, seed).to_dict():
            raise ValueError("first teaching candidate differs from its bounded search")
        first_dir, first_observation = _audited_source(
            runs_root, spec, first, events[2]["run_id"], identity,
        )
        proposed, _, proposal = _proposal(first_dir, runs_root, spec, seed)
        if second.to_dict() != proposed.to_dict():
            raise ValueError("second teaching candidate lacks first-source justification")
        second_dir, second_observation = _audited_source(
            runs_root, spec, second, events[5]["run_id"], identity,
        )
        for candidate, dispatch, refinement, observed in (
            (first, events[2], events[3], first_observation),
            (second, events[5], events[6], second_observation),
        ):
            if (
                dispatch.get("candidate_id") != candidate.candidate_id
                or refinement.get("candidate_id") != candidate.candidate_id
                or refinement.get("run_id") != dispatch.get("run_id")
                or refinement.get("evidence_manifest_sha256")
                != observed["evidence_manifest_sha256"]
            ):
                raise ValueError("teaching terminal source differs from journal binding")
        if proposal["first_manifest_sha256"] != first_observation["evidence_manifest_sha256"]:
            raise ValueError("teaching terminal proposal differs from first raw source")
        intent_path = trace_dir / "feedback_terminal_intent.json"
        summary_path = trace_dir / "feedback_summary.json"
        recovery_path = trace_dir / "feedback_terminal_recovery.json"
        intent = {
            "schema_version": 1, "status": "terminal_source_audited",
            "trace_id": trace_dir.name,
            "first_run_id": first_dir.name, "second_run_id": second_dir.name,
            "first_manifest_sha256": first_observation["evidence_manifest_sha256"],
            "second_manifest_sha256": second_observation["evidence_manifest_sha256"],
            "spectre_dispatched_by_finalizer": False,
            "not_lna_result": True, "spec_pass": None,
        }
        recovery = {
            **intent, "status": "finalized_existing_second_teaching_refinement",
        }
        if intent_path.exists() or intent_path.is_symlink():
            if (
                not intent_path.is_file() or intent_path.is_symlink()
                or json.loads(intent_path.read_text(encoding="utf-8")) != intent
            ):
                raise ValueError("teaching terminal recovery intent changed")
        else:
            if any(path.exists() or path.is_symlink() for path in (summary_path, recovery_path)):
                raise ValueError("completed teaching feedback was not in terminal recovery")
            write_json(intent_path, intent)
        if actions == _BASE_ACTIONS:
            manager = Manager(max_searches=2, max_evaluations=2)
            manager.context = (spec.id, seed)
            manager.searches_used = manager.evaluations_used = 2
            manager.seen_ids = {first.candidate_id, second.candidate_id}
            manager.trace = events
            manager.attach_journal_for_resume(trace_dir)
            try:
                manager._record("Stop", status="budget_exhausted")
            finally:
                manager.close_journal()
        if journal.disposition != "complete":
            terminal_events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()]
            manager = Manager(max_searches=2, max_evaluations=2)
            manager.context = (spec.id, seed)
            manager.searches_used = manager.evaluations_used = 2
            manager.seen_ids = {first.candidate_id, second.candidate_id}
            manager.trace = terminal_events
            manager.save_trace(trace_dir)
        rebuilt = build_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
        if summary_path.exists() or summary_path.is_symlink():
            if (
                not summary_path.is_file() or summary_path.is_symlink()
                or json.loads(summary_path.read_text(encoding="utf-8")) != rebuilt
            ):
                raise ValueError("teaching terminal summary differs from original raw sources")
        else:
            write_json(summary_path, rebuilt)
        audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
        if recovery_path.exists() or recovery_path.is_symlink():
            if (
                not recovery_path.is_file() or recovery_path.is_symlink()
                or json.loads(recovery_path.read_text(encoding="utf-8")) != recovery
            ):
                raise ValueError("teaching terminal recovery report changed")
        else:
            write_json(recovery_path, recovery)
        return recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize a journaled three-stage teaching refinement without Spectre")
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching spec")
    try:
        report = finalize_teaching_three_stage_agent(
            args.trace_dir, args.runs_root, specs[args.spec],
            seed=args.seed, specs_path=args.specs,
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_id={report['trace_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
