from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import re
from typing import Callable
from uuid import uuid4

from ..cadence.remote_runner import RemoteCadenceConfig
from ..schemas import Candidate, Spec
from .journal import inspect_journal
from .manager import Manager
from .run_lock import agent_run_lock
from .remote_identity import write_remote_identity_snapshot
from .spec_snapshots import read_spec_snapshot, write_spec_snapshot
from .uncertainty import RemoteEvaluationUncertain


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    searches_used: int
    evaluations_used: int
    trace_path: Path


def execute_manager(
    manager: Manager,
    spec: Spec,
    evaluator: Callable[[Candidate], Path],
    trace_dir: Path,
    *,
    seed: int = 0,
) -> ExecutionOutcome:
    """Run a bounded policy loop; evaluator owns its run archive and timeout."""
    return _execute_fresh(manager, spec, evaluator, trace_dir, seed=seed)


def execute_manager_planned(
    manager: Manager,
    spec: Spec,
    evaluator: Callable[[Candidate, str], Path],
    trace_dir: Path,
    *,
    seed: int = 0,
    remote_config: RemoteCadenceConfig | None = None,
) -> ExecutionOutcome:
    """Persist a unique candidate run ID before each evaluator dispatch."""
    return _execute_fresh(
        manager, spec, None, trace_dir, seed=seed,
        planned_evaluator=evaluator, remote_config=remote_config,
    )


def _execute_fresh(
    manager: Manager,
    spec: Spec,
    evaluator: Callable[[Candidate], Path] | None,
    trace_dir: Path,
    *,
    seed: int,
    planned_evaluator: Callable[[Candidate, str], Path] | None = None,
    remote_config: RemoteCadenceConfig | None = None,
) -> ExecutionOutcome:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", spec.id):
        raise ValueError("executor spec ID must be a safe identifier")
    if type(seed) is not int or seed < 0:
        raise ValueError("executor seed must be a nonnegative integer")
    if not isinstance(trace_dir, Path) or not trace_dir.is_dir() or trace_dir.is_symlink():
        raise ValueError("trace directory must be an existing non-symlink directory")
    if remote_config is not None and (
        planned_evaluator is None or not isinstance(remote_config, RemoteCadenceConfig)
    ):
        raise ValueError("remote identity binding requires a planned evaluator and validated config")
    with agent_run_lock(trace_dir):
        if any((trace_dir / name).exists() or (trace_dir / name).is_symlink()
               for name in ("agent_trace.json", "agent_events.jsonl", "agent_candidates.jsonl",
                            "agent_spec.json", "agent_remote.json")):
            raise FileExistsError("agent trace, journal, candidate, or spec snapshot already exists")
        if (
            manager.trace or manager.context is not None or manager.pending or manager.queue
            or manager.pending_run_ids or manager.searches_used or manager.evaluations_used or manager.seen_ids
        ):
            raise ValueError("executor requires a fresh manager")
        manager.enable_journal(trace_dir)
        try:
            spec_digest = write_spec_snapshot(trace_dir, spec)
            remote_digest = (
                write_remote_identity_snapshot(trace_dir, remote_config)
                if remote_config is not None else None
            )
            manager.context = (spec.id, seed)
            manager._record(
                "RunStarted", spec_id=spec.id, seed=seed,
                max_searches=manager.max_searches,
                max_evaluations=manager.max_evaluations,
                spec_sha256=spec_digest,
                **({"dispatch_mode": "planned"} if planned_evaluator is not None else {}),
                **({"remote_identity_sha256": remote_digest} if remote_digest is not None else {}),
            )
            status = _run_loop(manager, spec, evaluator, seed, planned_evaluator=planned_evaluator)
        finally:
            manager.close_journal()
        trace_path = manager.save_trace(trace_dir)
        return ExecutionOutcome(status, manager.searches_used, manager.evaluations_used, trace_path)


def resume_manager_after_search(
    spec: Spec, evaluator: Callable[[Candidate], Path], trace_dir: Path, *, seed: int = 0,
) -> ExecutionOutcome:
    """Resume only a fully recorded search before its first evaluator dispatch."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", spec.id) or type(seed) is not int or seed < 0:
        raise ValueError("resume spec ID or seed is invalid")
    with agent_run_lock(trace_dir):
        audit = inspect_journal(trace_dir)
        if (
            audit.disposition != "interrupted" or audit.pending_candidate_id is not None
            or audit.evaluations_used != 0 or not audit.candidate_snapshots_verified
            or not audit.spec_verified or not audit.queued_candidate_ids
            or (trace_dir / "agent_trace.json").exists()
        ):
            raise ValueError("agent run is not eligible for pre-evaluation resume")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(encoding="utf-8").splitlines()]
        start = events[0]
        if (
            audit.spec_id != spec.id or audit.seed != seed
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
            or audit.searches_used != start["max_searches"]
            or start["max_evaluations"] < 1
            or start.get("dispatch_mode") is not None
        ):
            raise ValueError("resume context or completed search budget differs")
        candidates: list[Candidate] = []
        for line in (trace_dir / "agent_candidates.jsonl").read_text(encoding="ascii").splitlines():
            candidates.extend(Candidate(**data) for data in json.loads(line)["candidates"])
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        if (len(by_id) != len(candidates)
                or len(candidates) != len(audit.queued_candidate_ids)
                or set(by_id) != set(audit.queued_candidate_ids)):
            raise ValueError("resume queue differs from candidate snapshots")
        manager = Manager(max_searches=start["max_searches"], max_evaluations=start["max_evaluations"])
        manager.context = (spec.id, seed)
        manager.queue = [by_id[candidate_id] for candidate_id in audit.queued_candidate_ids]
        manager.seen_ids = {candidate.candidate_id for candidate in candidates}
        manager.searches_used = audit.searches_used
        manager.trace = events
        manager.attach_journal_for_resume(trace_dir)
        try:
            status = _run_loop(manager, spec, evaluator, seed)
        finally:
            manager.close_journal()
        trace_path = manager.save_trace(trace_dir)
        return ExecutionOutcome(status, manager.searches_used, manager.evaluations_used, trace_path)


def _run_loop(
    manager: Manager, spec: Spec, evaluator: Callable[[Candidate], Path] | None, seed: int,
    *, planned_evaluator: Callable[[Candidate, str], Path] | None = None,
) -> str:
    status = "budget_exhausted"
    while True:
        action = manager.next_action()
        if action == "SearchCandidates":
            try:
                manager.search_candidates(spec, seed)
            except Exception:
                fields = {"failure_code": "search_error"}
                getter = getattr(manager.searcher, "last_call_id", None)
                model_call_id = getter() if callable(getter) else None
                if model_call_id is not None:
                    if not isinstance(model_call_id, str) or not re.fullmatch(r"[0-9a-f]{32}", model_call_id):
                        raise ValueError("searcher model call ID is unsafe")
                    fields["model_call_id"] = model_call_id
                manager._record("SearchFailed", **fields)
                status = "search_failed"
                break
        elif action == "EvaluateCandidate":
            if manager.priority_policy is not None and len(manager.queue) > 1:
                candidate_id, source, model_call_id = manager.priority_policy.choose(
                    spec, seed, manager.queue,
                    searches_used=manager.searches_used, max_searches=manager.max_searches,
                    evaluations_used=manager.evaluations_used,
                    max_evaluations=manager.max_evaluations,
                )
                manager.prioritize_candidate(candidate_id, source=source,
                                             model_call_id=model_call_id)
            planned_run_id = (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
                if planned_evaluator is not None else None
            )
            candidate = manager.pop_candidate(run_id=planned_run_id)
            try:
                run_dir = (
                    planned_evaluator(candidate, planned_run_id)
                    if planned_evaluator is not None else evaluator(candidate)
                )
            except RemoteEvaluationUncertain:
                raise
            except TimeoutError:
                manager.record_evaluation_failure(candidate, "backend_timeout")
            except Exception:
                manager.record_evaluation_failure(candidate, "backend_error")
            else:
                if not isinstance(run_dir, Path):
                    manager.record_evaluation_failure(candidate, "invalid_run_directory")
                else:
                    try:
                        manager.record_result(candidate, run_dir, spec)
                    except Exception:
                        manager.record_evaluation_failure(candidate, "invalid_run_directory")
        elif action == "Stop":
            if manager.evaluations_used == 0 and manager.searches_used > 0:
                status = "no_candidates"
            break
        else:
            status = "pending_evaluation"
            break
    manager._record("Stop", status=status)
    return status
