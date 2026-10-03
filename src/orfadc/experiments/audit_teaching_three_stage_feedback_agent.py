from __future__ import annotations

import argparse
import json
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.agents.teaching_three_stage_feedback import TeachingThreeStageSearcher
from orfadc.config_loader import load_specs
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage_refinement import (
    _proposal, _require_candidate_location, _source,
)
from orfadc.schemas import Candidate, Spec


_ACTIONS = (
    "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
    "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop",
)


def build_teaching_three_stage_agent_feedback(trace_dir: Path, runs_root: Path, spec: Spec) -> dict:
    """Rebuild a completed Manager trace from two independent Spectre archives."""
    _require_private_path(trace_dir)
    _require_private_path(runs_root)
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if not all((
        journal.disposition == "complete", journal.trace_verified,
        journal.spec_verified, journal.candidate_snapshots_verified,
        journal.remote_identity_verified, journal.candidate_bindings_verified,
        journal.searches_used == 2, journal.evaluations_used == 2,
        journal.spec_id == spec.id, journal.seed is not None,
    )):
        raise ValueError("three-stage agent trace lacks a complete bound two-run journal")
    events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    if tuple(item.get("action") for item in events) != _ACTIONS:
        raise ValueError("three-stage agent action sequence differs from two-run feedback")
    start = events[0]
    if (
        start.get("dispatch_mode") != "planned"
        or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
        or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        or events[3].get("status") != "teaching_refinement_proposed"
        or events[6].get("status") != "needs_evaluation"
        or events[7].get("status") != "budget_exhausted"
    ):
        raise ValueError("three-stage agent planned context or refinement status differs")
    trace_identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
        encoding="ascii"
    ).splitlines()]
    if len(snapshots) != 2 or any(len(item.get("candidates", [])) != 1 for item in snapshots):
        raise ValueError("three-stage agent lacks one candidate per search")
    first = Candidate(**snapshots[0]["candidates"][0])
    second = Candidate(**snapshots[1]["candidates"][0])
    if first.to_dict() != TeachingThreeStageSearcher.initial_candidate(spec, journal.seed).to_dict():
        raise ValueError("three-stage agent initial candidate differs from its bounded search")
    if any(
        event.get("candidate_id") != candidate.candidate_id
        for event, candidate in ((events[2], first), (events[3], first), (events[5], second), (events[6], second))
    ):
        raise ValueError("three-stage agent event candidate IDs differ from snapshots")
    source_dirs = []
    observations = []
    for candidate, event in ((first, events[2]), (second, events[5])):
        run_id = event.get("run_id")
        if not isinstance(run_id, str):
            raise ValueError("three-stage agent planned run ID is missing")
        relative = f"{spec.id}/seed{journal.seed}/{candidate.candidate_id}/{run_id}"
        run_dir = _source(runs_root, relative)
        _require_candidate_location(run_dir, runs_root, candidate)
        observation = observe_teaching_three_stage_candidate(run_dir, spec, candidate)
        probe = json.loads((run_dir / "probe_status.json").read_text(encoding="utf-8"))
        plan = json.loads((run_dir / "dispatch_plan.json").read_text(encoding="utf-8"))
        if (
            probe.get("dispatch_protocol_version") not in {3, 4}
            or read_remote_identity_snapshot(run_dir, plan["remote_identity_sha256"]) != trace_identity
            or observation["run_id"] != run_id
        ):
            raise ValueError("three-stage agent source lacks the planned remote identity")
        source_dirs.append(run_dir)
        observations.append(observation)
    expected_second, _, proposal = _proposal(source_dirs[0], runs_root, spec, journal.seed)
    if (
        second.to_dict() != expected_second.to_dict()
        or proposal["first_manifest_sha256"] != events[3].get("evidence_manifest_sha256")
        or events[6].get("evidence_manifest_sha256") != observations[1]["evidence_manifest_sha256"]
    ):
        raise ValueError("three-stage agent second candidate is not the audited refinement")
    return {
        "schema_version": 1, "status": "verified_two_run_teaching_agent_feedback",
        "trace_id": trace_dir.name, "spec_id": spec.id, "seed": journal.seed,
        "searches_used": 2, "evaluations_used": 2,
        "candidate_bindings_verified": True,
        "first_run_relative": source_dirs[0].resolve().relative_to(runs_root.resolve()).as_posix(),
        "second_run_relative": source_dirs[1].resolve().relative_to(runs_root.resolve()).as_posix(),
        "first_observation": observations[0], "second_observation": observations[1],
        "delta_s21_worst_db": observations[1]["s21_worst_db"] - observations[0]["s21_worst_db"],
        "delta_s22_worst_db": observations[1]["s22_worst_db"] - observations[0]["s22_worst_db"],
        "compression_status": "not_measured", "not_lna_result": True, "spec_pass": None,
    }


def audit_teaching_three_stage_agent_feedback(trace_dir: Path, runs_root: Path, spec: Spec) -> dict:
    rebuilt = build_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    saved = json.loads((trace_dir / "feedback_summary.json").read_text(encoding="utf-8"))
    if saved != rebuilt:
        raise ValueError("three-stage agent feedback summary differs from source-audited journal")
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit one public MOS1 three-stage planned Manager feedback trace")
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching spec")
    try:
        report = audit_teaching_three_stage_agent_feedback(args.trace_dir, args.runs_root, specs[args.spec])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_id={report['trace_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
