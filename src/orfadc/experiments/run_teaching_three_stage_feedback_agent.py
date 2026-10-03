from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.remote_identity import remote_identity
from orfadc.agents.teaching_three_stage_feedback import (
    TeachingThreeStageRefiner, TeachingThreeStageSearcher,
)
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback, build_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)
from orfadc.experiments.run_teaching_three_stage_candidate import run_teaching_three_stage_candidate
from orfadc.schemas import Candidate


def run_teaching_three_stage_feedback_agent(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path, *,
    spec_id: str = "S1", seed: int = 0, runner: RemoteRunner | None = None,
) -> tuple[Path, dict]:
    """Execute two planned small-signal teaching rounds; never accept an LNA pass."""
    for path in (runs_root, trace_root):
        _require_private_path(path)
    specs = {item.id: item for item in load_specs(specs_path)}
    if spec_id not in specs:
        raise ValueError("unknown teaching three-stage spec")
    spec = specs[spec_id]
    initial = TeachingThreeStageSearcher.initial_candidate(spec, seed)
    render_teaching_three_stage(
        output_tune_ff=initial.passive_params["output_tune_ff"],
        output_secondary_nh=initial.passive_params["output_secondary_nh"],
    )
    if available_physical_memory_gb() < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before three-stage agent")
    config = load_remote_config(config_path)
    active_runner = runner or RemoteRunner(config)
    if remote_identity(active_runner.config) != remote_identity(config):
        raise ValueError("three-stage agent runner differs from its planned remote identity")
    refiner = TeachingThreeStageRefiner(runs_root)
    searcher = TeachingThreeStageSearcher(refiner)
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    trace_dir.mkdir(exist_ok=False)

    def evaluate(candidate: Candidate, run_id: str) -> Path:
        run_dir, _ = run_teaching_three_stage_candidate(
            config_path, runs_root, spec, candidate, run_id=run_id, runner=active_runner,
        )
        return run_dir

    try:
        outcome = execute_manager_planned(
            Manager(searcher=searcher, refiner=refiner, max_searches=2, max_evaluations=2),
            spec, evaluate, trace_dir, seed=seed, remote_config=config,
        )
    except RemoteEvaluationUncertain:
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition != "reconcile_pending_evaluation"
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified or journal.pending_run_id is None
            or journal.pending_candidate_id is None
        ):
            raise ValueError("three-stage agent uncertainty lacks a bound planned journal") from None
        report = {
            "schema_version": 1, "status": "pending_remote_evaluation",
            "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
            "pending_candidate_id": journal.pending_candidate_id,
            "pending_run_id": journal.pending_run_id,
            "searches_used": journal.searches_used,
            "evaluations_used": journal.evaluations_used,
            "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_pending.json", report)
        return trace_dir, report
    try:
        report = build_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    except (OSError, ValueError, TypeError, KeyError):
        report = {
            "schema_version": 1, "status": "teaching_agent_incomplete",
            "trace_id": trace_dir.name, "spec_id": spec.id, "seed": seed,
            "searches_used": outcome.searches_used,
            "evaluations_used": outcome.evaluations_used,
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_incomplete.json", report)
        return trace_dir, report
    write_json(trace_dir / "feedback_summary.json", report)
    audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two planned public MOS1 three-stage teaching agent rounds")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_agent_feedback")
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        trace_dir, report = run_teaching_three_stage_feedback_agent(
            args.config, args.specs, args.runs_root, args.trace_root,
            spec_id=args.spec, seed=args.seed,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_dir={trace_dir.resolve()} not_lna_result=true")
    return 0 if report["status"] == "verified_two_run_teaching_agent_feedback" else 1


if __name__ == "__main__":
    raise SystemExit(main())
