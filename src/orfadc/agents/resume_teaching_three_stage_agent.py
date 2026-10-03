from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from orfadc.agents.executor import _run_loop
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.reconcile_pending_teaching_three_stage import (
    _audited_source, _pending_report,
)
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.agents.teaching_three_stage_feedback import (
    TeachingThreeStageRefiner, TeachingThreeStageSearcher,
)
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback, build_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)
from orfadc.experiments.run_teaching_three_stage_candidate import run_teaching_three_stage_candidate
from orfadc.experiments.run_teaching_three_stage_refinement import _proposal
from orfadc.schemas import Candidate, Spec


_FIRST_ACTIONS = (
    "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
)


@dataclass(frozen=True)
class _ResumeContext:
    events: list[dict]
    first: Candidate
    proposed: Candidate
    second_queued: bool
    first_run_id: str
    first_manifest_sha256: str


def _verify_resume_context(
    trace_dir: Path, runs_root: Path, spec: Spec, seed: int, identity: dict,
) -> _ResumeContext:
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if (
        journal.disposition != "interrupted"
        or not journal.spec_verified or not journal.candidate_snapshots_verified
        or not journal.remote_identity_verified or not journal.candidate_bindings_verified
        or journal.pending_candidate_id is not None
        or journal.spec_id != spec.id or journal.seed != seed
        or journal.evaluations_used != 1 or journal.searches_used not in {1, 2}
        or (trace_dir / "agent_trace.json").exists()
    ):
        raise ValueError("teaching trace is not eligible for pre-second-evaluation resume")
    events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    actions = tuple(item.get("action") for item in events)
    queued = actions == (*_FIRST_ACTIONS, "SearchCandidates")
    if (
        actions not in {_FIRST_ACTIONS, (*_FIRST_ACTIONS, "SearchCandidates")}
        or journal.searches_used != (2 if queued else 1)
        or events[3].get("status") != "teaching_refinement_proposed"
    ):
        raise ValueError("teaching resume journal differs from first-round feedback")
    start = events[0]
    if (
        start.get("dispatch_mode") != "planned"
        or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
        or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        or read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"]) != identity
    ):
        raise ValueError("teaching resume lacks the original planned context")
    snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
        encoding="ascii"
    ).splitlines()]
    if len(snapshots) != journal.searches_used or any(
        len(item.get("candidates", [])) != 1 for item in snapshots
    ):
        raise ValueError("teaching resume candidate snapshots are incomplete")
    first = Candidate(**snapshots[0]["candidates"][0])
    if first.to_dict() != TeachingThreeStageSearcher.initial_candidate(spec, seed).to_dict():
        raise ValueError("teaching resume first candidate differs from bounded search")
    first_dir, observation = _audited_source(
        runs_root, spec, first, events[2]["run_id"], identity,
    )
    proposed, _, proposal = _proposal(first_dir, runs_root, spec, seed)
    if (
        events[2].get("candidate_id") != first.candidate_id
        or events[3].get("candidate_id") != first.candidate_id
        or events[3].get("run_id") != first_dir.name
        or events[3].get("evidence_manifest_sha256")
        != observation["evidence_manifest_sha256"]
        or proposal["first_manifest_sha256"] != observation["evidence_manifest_sha256"]
    ):
        raise ValueError("teaching resume first source differs from its journal binding")
    if queued:
        second = Candidate(**snapshots[1]["candidates"][0])
        if (
            second.to_dict() != proposed.to_dict()
            or events[4].get("candidate_ids") != [second.candidate_id]
            or journal.queued_candidate_ids != (second.candidate_id,)
        ):
            raise ValueError("queued teaching second candidate differs from first raw result")
    pending_path = trace_dir / "feedback_pending.json"
    if pending_path.exists() or pending_path.is_symlink():
        expected = {
            "schema_version": 1, "status": "pending_remote_evaluation",
            "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
            "pending_candidate_id": first.candidate_id,
            "pending_run_id": first_dir.name,
            "searches_used": 1, "evaluations_used": 1,
            "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
        }
        if (
            not pending_path.is_file() or pending_path.is_symlink()
            or json.loads(pending_path.read_text(encoding="utf-8")) != expected
        ):
            raise ValueError("historical first pending report differs from its journal")
    return _ResumeContext(
        events, first, proposed, queued, first_dir.name,
        observation["evidence_manifest_sha256"],
    )


def resume_teaching_three_stage_agent(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    config_path: Path, specs_path: Path, runner: RemoteRunner | None = None,
) -> dict:
    """Resume only before the second dispatch; never repeat the first evaluation."""
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    if {item.id: item for item in load_specs(specs_path)}.get(spec.id) != spec:
        raise ValueError("current spec differs from the planned teaching spec")
    config = load_remote_config(config_path)
    active_runner = runner or RemoteRunner(config)
    identity = remote_identity(config)
    if remote_identity(active_runner.config) != identity:
        raise ValueError("teaching resume runner differs from planned remote identity")
    if available_physical_memory_gb() < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before teaching resume")
    with agent_run_lock(trace_dir):
        if any((trace_dir / name).exists() or (trace_dir / name).is_symlink() for name in (
            "feedback_summary.json", "feedback_incomplete.json", "feedback_reconciliation.json",
            "feedback_terminal_intent.json", "feedback_terminal_recovery.json",
            "feedback_search_resume.json",
        )):
            raise ValueError("teaching resume trace has an incompatible terminal artifact")
        context = _verify_resume_context(trace_dir, runs_root, spec, seed, identity)
        intent_path = trace_dir / "feedback_search_resume_intent.json"
        intent = {
            "schema_version": 1, "status": "first_source_audited_before_second_dispatch",
            "trace_id": trace_dir.name,
            "first_run_id": context.first_run_id,
            "first_manifest_sha256": context.first_manifest_sha256,
            "second_candidate": context.proposed.to_dict(),
            "first_redispatched": False, "not_lna_result": True, "spec_pass": None,
        }
        if intent_path.exists() or intent_path.is_symlink():
            if (
                not intent_path.is_file() or intent_path.is_symlink()
                or json.loads(intent_path.read_text(encoding="utf-8")) != intent
            ):
                raise ValueError("teaching resume intent changed")
        else:
            write_json(intent_path, intent)
        refiner = TeachingThreeStageRefiner(runs_root)
        refiner.proposals_created = 1
        refiner.parent_manifest_sha256 = context.first_manifest_sha256
        searcher = TeachingThreeStageSearcher(refiner)
        searcher.search_calls = 2 if context.second_queued else 1
        if context.second_queued:
            searcher.used_proposal = context.proposed
        else:
            refiner._pending_proposal = context.proposed
        manager = Manager(searcher=searcher, refiner=refiner, max_searches=2, max_evaluations=2)
        manager.context = (spec.id, seed)
        manager.searches_used = 2 if context.second_queued else 1
        manager.evaluations_used = 1
        manager.seen_ids = {context.first.candidate_id}
        if context.second_queued:
            manager.seen_ids.add(context.proposed.candidate_id)
            manager.queue = [context.proposed]
        manager.trace = context.events
        manager.attach_journal_for_resume(trace_dir)

        def evaluate(candidate: Candidate, run_id: str) -> Path:
            result, _ = run_teaching_three_stage_candidate(
                config_path, runs_root, spec, candidate, run_id=run_id,
                runner=active_runner,
            )
            return result

        try:
            try:
                _run_loop(manager, spec, None, seed, planned_evaluator=evaluate)
            except RemoteEvaluationUncertain:
                manager.close_journal()
                journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
                if journal.disposition != "reconcile_pending_evaluation":
                    raise ValueError("resumed second dispatch uncertainty lacks its planned journal") from None
                report = _pending_report(trace_dir, journal, spec, seed)
                write_json(trace_dir / "feedback_pending.json", report)
                return report
        finally:
            manager.close_journal()
        manager.save_trace(trace_dir)
        try:
            summary = build_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
        except (OSError, ValueError, TypeError, KeyError):
            report = {
                "schema_version": 1, "status": "teaching_agent_incomplete",
                "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
                "searches_used": manager.searches_used,
                "evaluations_used": manager.evaluations_used,
                "not_lna_result": True, "spec_pass": None,
            }
            write_json(trace_dir / "feedback_incomplete.json", report)
            return report
        write_json(trace_dir / "feedback_summary.json", summary)
        audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
        report = {
            "schema_version": 1, "status": "resumed_existing_first_then_new_second",
            "trace_id": trace_dir.name,
            "first_run_id": context.first_run_id,
            "second_run_relative": summary["second_run_relative"],
            "first_redispatched": False, "new_second_dispatched": True,
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_search_resume.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a three-stage teaching agent only before its second dispatch")
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching spec")
    try:
        report = resume_teaching_three_stage_agent(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            config_path=args.config, specs_path=args.specs,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, IndexError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_id={report['trace_id']} not_lna_result=true")
    return 0 if report["status"].startswith("resumed_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
