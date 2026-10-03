from __future__ import annotations

import argparse
import json
from pathlib import Path

from orfadc.agents.executor import _run_loop
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.agents.teaching_three_stage_feedback import (
    TeachingThreeStageRefiner, TeachingThreeStageSearcher,
)
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback, build_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage_candidate import run_teaching_three_stage_candidate
from orfadc.experiments.run_teaching_three_stage_refinement import (
    _proposal, _require_candidate_location, _source,
)
from orfadc.schemas import Candidate, Spec


def _pending_report(trace_dir: Path, journal: object, spec: Spec, seed: int) -> dict:
    return {
        "schema_version": 1, "status": "pending_remote_evaluation",
        "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
        "pending_candidate_id": journal.pending_candidate_id,
        "pending_run_id": journal.pending_run_id,
        "searches_used": journal.searches_used,
        "evaluations_used": journal.evaluations_used,
        "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
    }


def _audited_source(
    runs_root: Path, spec: Spec, candidate: Candidate, run_id: str, identity: dict,
) -> tuple[Path, dict]:
    path = _source(
        runs_root, f"{spec.id}/seed{candidate.seed}/{candidate.candidate_id}/{run_id}",
    )
    _require_candidate_location(path, runs_root, candidate)
    observation = observe_teaching_three_stage_candidate(path, spec, candidate)
    plan = json.loads((path / "dispatch_plan.json").read_text(encoding="utf-8"))
    probe = json.loads((path / "probe_status.json").read_text(encoding="utf-8"))
    if (
        probe.get("dispatch_protocol_version") not in {3, 4}
        or read_remote_identity_snapshot(path, plan["remote_identity_sha256"]) != identity
        or observation["run_id"] != run_id
        or ((path / "dispatch_uncertain.json").exists()
            and probe["dispatch_protocol_version"] != 4)
    ):
        raise ValueError("pending three-stage source does not match its planned identity")
    return path, observation


def reconcile_pending_teaching_three_stage(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    config_path: Path, specs_path: Path, runner: RemoteRunner | None = None,
) -> dict:
    """Adopt a recovered planned run; only a new second candidate may be dispatched."""
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    if {item.id: item for item in load_specs(specs_path)}.get(spec.id) != spec:
        raise ValueError("current spec differs from the planned three-stage spec")
    config = load_remote_config(config_path)
    active_runner = runner or RemoteRunner(config)
    if remote_identity(active_runner.config) != remote_identity(config):
        raise ValueError("reconciliation runner differs from the configured remote identity")
    with agent_run_lock(trace_dir):
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition != "reconcile_pending_evaluation"
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified
            or journal.spec_id != spec.id or journal.seed != seed
            or journal.searches_used not in {1, 2}
            or journal.evaluations_used != journal.searches_used
            or journal.pending_run_id is None or journal.pending_candidate_id is None
            or any((trace_dir / name).exists() or (trace_dir / name).is_symlink() for name in (
                "agent_trace.json", "feedback_summary.json", "feedback_reconciliation.json",
                "feedback_incomplete.json",
            ))
        ):
            raise ValueError("trace is not an eligible planned three-stage pending evaluation")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        first_pending = journal.evaluations_used == 1
        expected_actions = (
            ["RunStarted", "SearchCandidates", "EvaluateCandidate"] if first_pending else
            ["RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
             "SearchCandidates", "EvaluateCandidate"]
        )
        start = events[0]
        if (
            [event.get("action") for event in events] != expected_actions
            or start.get("dispatch_mode") != "planned"
            or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
            or remote_identity(config) != read_remote_identity_snapshot(
                trace_dir, start["remote_identity_sha256"]
            )
        ):
            raise ValueError("pending three-stage journal context differs from its snapshots")
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != journal.searches_used or any(
            len(item.get("candidates", [])) != 1 for item in snapshots
        ):
            raise ValueError("pending three-stage candidate snapshots are incomplete")
        first = Candidate(**snapshots[0]["candidates"][0])
        if first.to_dict() != TeachingThreeStageSearcher.initial_candidate(spec, seed).to_dict():
            raise ValueError("pending first candidate is not the bounded teaching seed")
        if events[2].get("candidate_id") != first.candidate_id:
            raise ValueError("first planned evaluation candidate differs")
        candidates = [first]
        if not first_pending:
            second = Candidate(**snapshots[1]["candidates"][0])
            candidates.append(second)
            if (
                not journal.candidate_bindings_verified
                or events[3].get("status") != "teaching_refinement_proposed"
                or events[3].get("candidate_id") != first.candidate_id
                or events[3].get("run_id") != events[2].get("run_id")
                or events[5].get("candidate_id") != second.candidate_id
            ):
                raise ValueError("second planned candidate lacks its first-source binding")
        pending = candidates[-1]
        if (
            pending.candidate_id != journal.pending_candidate_id
            or events[-1].get("run_id") != journal.pending_run_id
        ):
            raise ValueError("pending candidate or planned run ID differs")
        pending_file = trace_dir / "feedback_pending.json"
        if (
            not pending_file.is_file() or pending_file.is_symlink()
            or json.loads(pending_file.read_text(encoding="utf-8")) != _pending_report(
                trace_dir, journal, spec, seed
            )
        ):
            raise ValueError("pending three-stage uncertainty report differs from journal")
        identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        first_dir, first_observation = _audited_source(
            runs_root, spec, first, events[2]["run_id"], identity,
        )
        proposed, _, proposal = _proposal(first_dir, runs_root, spec, seed)
        if not first_pending:
            if (
                candidates[1].to_dict() != proposed.to_dict()
                or events[3].get("evidence_manifest_sha256")
                != first_observation["evidence_manifest_sha256"]
            ):
                raise ValueError("second candidate is not the raw-audited first refinement")
        pending_dir, pending_observation = (
            (first_dir, first_observation) if first_pending else
            _audited_source(runs_root, spec, pending, journal.pending_run_id, identity)
        )
        refiner = TeachingThreeStageRefiner(runs_root)
        searcher = TeachingThreeStageSearcher(refiner)
        searcher.search_calls = journal.searches_used
        if not first_pending:
            refiner.proposals_created = 1
            refiner.parent_manifest_sha256 = proposal["first_manifest_sha256"]
            searcher.used_proposal = pending
        manager = Manager(searcher=searcher, refiner=refiner, max_searches=2, max_evaluations=2)
        manager.context = (spec.id, seed)
        manager.searches_used = journal.searches_used
        manager.evaluations_used = journal.evaluations_used
        manager.seen_ids = {candidate.candidate_id for candidate in candidates}
        manager.pending = {pending.candidate_id: pending}
        manager.pending_run_ids = {pending.candidate_id: journal.pending_run_id}
        manager.trace = events
        manager.attach_journal_for_resume(trace_dir)
        try:
            manager.record_result(pending, pending_dir, spec)
            if first_pending:
                def evaluate(candidate: Candidate, run_id: str) -> Path:
                    result, _ = run_teaching_three_stage_candidate(
                        config_path, runs_root, spec, candidate, run_id=run_id,
                        runner=active_runner,
                    )
                    return result

                try:
                    _run_loop(manager, spec, None, seed, planned_evaluator=evaluate)
                except RemoteEvaluationUncertain:
                    manager.close_journal()
                    next_journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
                    if next_journal.disposition != "reconcile_pending_evaluation":
                        raise ValueError("second dispatch uncertainty lacks a planned journal") from None
                    report = _pending_report(trace_dir, next_journal, spec, seed)
                    write_json(pending_file, report)
                    return report
            else:
                manager._record("Stop", status="budget_exhausted")
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
            "schema_version": 1,
            "status": "reconciled_existing_first_then_new_second" if first_pending
            else "reconciled_existing_second_archive",
            "trace_id": trace_dir.name,
            "adopted_run_id": pending_dir.name,
            "adopted_manifest_sha256": pending_observation["evidence_manifest_sha256"],
            "adopted_run_redispatched": False,
            "new_second_dispatched": first_pending,
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_reconciliation.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile a planned three-stage Manager run without duplicate dispatch")
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching three-stage spec")
    try:
        report = reconcile_pending_teaching_three_stage(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            config_path=args.config, specs_path=args.specs,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, IndexError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_id={report['trace_id']} not_lna_result=true")
    return 0 if report["status"].startswith("reconciled_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
