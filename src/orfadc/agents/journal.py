from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..cadence.evidence import read_evidenced_metrics
from .candidate_snapshots import verify_search_snapshots
from .remote_identity import read_remote_identity_snapshot
from .spec_snapshots import read_spec_snapshot


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_STATUS = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_CALL_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_JOURNAL_BYTES = 10_000_000


@dataclass(frozen=True)
class JournalAudit:
    disposition: str
    spec_id: str
    seed: int
    searches_used: int
    evaluations_used: int
    queued_candidate_ids: tuple[str, ...]
    pending_candidate_id: str | None
    trace_verified: bool
    safe_to_auto_resume: bool = False
    candidate_bindings_verified: bool = False
    candidate_snapshots_verified: bool = False
    spec_verified: bool = False
    pending_run_id: str | None = None
    remote_identity_verified: bool = False
    model_call_bindings_verified: bool = False
    model_call_bindings: tuple[tuple[str, str, str | None, str], ...] = ()
    search_call_bindings_verified: bool = False
    search_call_bindings: tuple[tuple[str, tuple[str, ...], str], ...] = ()
    refiner_call_bindings_verified: bool = False
    refiner_call_bindings: tuple[tuple[str, str, str | None, str], ...] = ()


def _exact(event: dict, *fields: str) -> None:
    if set(event) != {"step", "action", *fields}:
        raise ValueError("journal event has unexpected fields")


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("journal contains an invalid identifier")
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("journal contains an invalid counter")
    return value


def inspect_journal(run_dir: Path, *, candidate_runs_root: Path | None = None) -> JournalAudit:
    """Validate an executor journal without replaying tools or trusting it as simulation evidence."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("journal directory must be an existing non-symlink directory")
    path = run_dir / "agent_events.jsonl"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > _MAX_JOURNAL_BYTES:
        raise ValueError("journal is missing, unsafe, or too large")
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.endswith("\n"):
            raise ValueError("journal has an incomplete final record")
        events = [json.loads(line) for line in raw.splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("journal is unreadable or malformed") from exc
    if not events:
        raise ValueError("journal has no events")
    for step, event in enumerate(events, 1):
        if not isinstance(event, dict) or type(event.get("step")) is not int or event["step"] != step:
            raise ValueError("journal steps are not consecutive")
    start = events[0]
    if start.get("action") != "RunStarted":
        raise ValueError("journal lacks executor context; legacy audit cannot be resumed")
    remote_identity_verified = False
    if "spec_sha256" in start:
        fields = ["spec_id", "seed", "max_searches", "max_evaluations", "spec_sha256"]
        if "dispatch_mode" in start:
            fields.append("dispatch_mode")
            if start["dispatch_mode"] != "planned":
                raise ValueError("journal dispatch mode is invalid")
        if "remote_identity_sha256" in start:
            if start.get("dispatch_mode") != "planned":
                raise ValueError("remote identity requires a planned dispatch")
            fields.append("remote_identity_sha256")
        _exact(start, *fields)
        spec_verified = read_spec_snapshot(run_dir, start["spec_sha256"]).id == start["spec_id"]
        if not spec_verified:
            raise ValueError("agent spec snapshot ID differs from journal")
        if "remote_identity_sha256" in start:
            read_remote_identity_snapshot(run_dir, start["remote_identity_sha256"])
            remote_identity_verified = True
        elif (run_dir / "agent_remote.json").exists() or (run_dir / "agent_remote.json").is_symlink():
            raise ValueError("unbound agent remote identity snapshot is unsafe")
    else:
        _exact(start, "spec_id", "seed", "max_searches", "max_evaluations")
        if (run_dir / "agent_spec.json").exists() or (run_dir / "agent_spec.json").is_symlink():
            raise ValueError("unbound agent spec snapshot is unsafe")
        if (run_dir / "agent_remote.json").exists() or (run_dir / "agent_remote.json").is_symlink():
            raise ValueError("unbound agent remote identity snapshot is unsafe")
        spec_verified = False
    spec_id = _identifier(start["spec_id"])
    seed = _nonnegative_int(start["seed"])
    max_searches = _nonnegative_int(start["max_searches"])
    max_evaluations = _nonnegative_int(start["max_evaluations"])

    queue: list[str] = []
    seen: set[str] = set()
    pending: str | None = None
    pending_run_id: str | None = None
    priority_pending: str | None = None
    searches = evaluations = 0
    search_failed = stopped = False
    bindings: list[tuple[str, str, str]] = []
    unbound_refinements = 0
    search_events: list[dict] = []
    model_priorities: list[dict] = []
    model_searches: list[dict] = []
    model_refinements: list[dict] = []
    for event in events[1:]:
        action = event.get("action")
        if stopped or (search_failed and action != "Stop"):
            raise ValueError("journal has actions after a terminal event")
        if priority_pending is not None and action != "EvaluateCandidate":
            raise ValueError("journal priority choice was not followed by evaluation")
        if action == "SearchCandidates":
            fields = ["count", "candidate_ids"]
            if "candidate_snapshot_sha256" in event:
                fields.append("candidate_snapshot_sha256")
                if (not isinstance(event["candidate_snapshot_sha256"], str)
                        or not _SHA256.fullmatch(event["candidate_snapshot_sha256"])):
                    raise ValueError("journal candidate snapshot digest is invalid")
            if "model_call_id" in event:
                fields.append("model_call_id")
                if (not isinstance(event["model_call_id"], str)
                        or not _MODEL_CALL_ID.fullmatch(event["model_call_id"])):
                    raise ValueError("journal Searcher model call ID is invalid")
                model_searches.append(event)
            _exact(event, *fields)
            ids = event["candidate_ids"]
            if (
                pending is not None or queue or searches >= max_searches
                or not isinstance(ids, list)
                or type(event["count"]) is not int or event["count"] != len(ids)
            ):
                raise ValueError("journal search transition is invalid")
            validated = [_identifier(value) for value in ids]
            if len(set(validated)) != len(validated) or any(value in seen for value in validated):
                raise ValueError("journal contains duplicate candidates")
            queue.extend(validated)
            seen.update(validated)
            searches += 1
            search_events.append(event)
        elif action == "QueuePriority":
            if "model_call_id" in event:
                _exact(event, "candidate_id", "source", "model_call_id")
                if (not isinstance(event["model_call_id"], str)
                        or not _MODEL_CALL_ID.fullmatch(event["model_call_id"])):
                    raise ValueError("journal model call ID is invalid")
                model_priorities.append(event)
            else:
                _exact(event, "candidate_id", "source")
            selected = _identifier(event["candidate_id"])
            if (
                pending is not None or len(queue) < 2 or evaluations >= max_evaluations
                or selected not in queue or event["source"] not in {"model", "fallback"}
                or (event["source"] == "fallback" and selected != queue[0])
            ):
                raise ValueError("journal priority transition is invalid")
            queue.insert(0, queue.pop(queue.index(selected)))
            priority_pending = selected
        elif action == "EvaluateCandidate":
            if "run_id" in event:
                _exact(event, "candidate_id", "run_id")
                planned_run_id = _identifier(event["run_id"])
            else:
                _exact(event, "candidate_id")
                planned_run_id = None
            if (start.get("dispatch_mode") == "planned") != (planned_run_id is not None):
                raise ValueError("journal evaluation lacks its planned run ID")
            candidate_id = _identifier(event["candidate_id"])
            if (pending is not None or evaluations >= max_evaluations or not queue
                    or queue[0] != candidate_id
                    or (priority_pending is not None and candidate_id != priority_pending)):
                raise ValueError("journal evaluation transition is invalid")
            queue.pop(0)
            pending = candidate_id
            pending_run_id = planned_run_id
            priority_pending = None
            evaluations += 1
        elif action == "RefineCandidate":
            if set(event) == {"step", "action", "candidate_id", "status"}:
                unbound_refinements += 1  # Legacy journal, not sufficient for candidate binding.
            else:
                fields = ["candidate_id", "status", "run_id", "evidence_manifest_sha256"]
                if "model_call_id" in event:
                    fields.append("model_call_id")
                    if (not isinstance(event["model_call_id"], str)
                            or not _MODEL_CALL_ID.fullmatch(event["model_call_id"])):
                        raise ValueError("journal Refiner model call ID is invalid")
                    model_refinements.append(event)
                _exact(event, *fields)
                event_run_id = event["run_id"]
                digest = event["evidence_manifest_sha256"]
                if (event_run_id is None) != (digest is None):
                    raise ValueError("journal has an incomplete candidate evidence binding")
                if event_run_id is None:
                    unbound_refinements += 1
                elif not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                    raise ValueError("journal candidate evidence digest is invalid")
                else:
                    bindings.append((_identifier(event["candidate_id"]), _identifier(event_run_id), digest))
            if (
                _identifier(event["candidate_id"]) != pending
                or not isinstance(event["status"], str)
                or not _STATUS.fullmatch(event["status"])
                or event["status"] == "accepted"
                or (pending_run_id is not None and event.get("run_id") != pending_run_id)
            ):
                raise ValueError("journal refinement transition is invalid")
            pending = None
            pending_run_id = None
        elif action == "EvaluationFailed":
            _exact(event, "candidate_id", "failure_code")
            if _identifier(event["candidate_id"]) != pending or event["failure_code"] not in {
                "backend_error", "backend_timeout", "invalid_run_directory"
            }:
                raise ValueError("journal failure transition is invalid")
            pending = None
            pending_run_id = None
        elif action == "SearchFailed":
            if "model_call_id" in event:
                _exact(event, "failure_code", "model_call_id")
                if (not isinstance(event["model_call_id"], str)
                        or not _MODEL_CALL_ID.fullmatch(event["model_call_id"])):
                    raise ValueError("journal Searcher model call ID is invalid")
                model_searches.append(event)
            else:
                _exact(event, "failure_code")
            if event["failure_code"] != "search_error" or pending is not None or queue or searches >= max_searches:
                raise ValueError("journal search failure transition is invalid")
            search_failed = True
        elif action == "Stop":
            _exact(event, "status")
            status = event["status"]
            if status not in {"budget_exhausted", "no_candidates", "search_failed", "pending_evaluation"}:
                raise ValueError("journal has an invalid stop status")
            if search_failed != (status == "search_failed"):
                raise ValueError("journal stop disagrees with search failure")
            if status == "pending_evaluation":
                if pending is None:
                    raise ValueError("journal has no pending evaluation")
            elif pending is not None:
                raise ValueError("journal stopped with an unresolved evaluation")
            if status == "no_candidates" and (queue or evaluations or not searches):
                raise ValueError("journal no-candidates status is inconsistent")
            if status in {"budget_exhausted", "no_candidates"} and (
                (queue and evaluations < max_evaluations)
                or (not queue and searches < max_searches)
            ):
                raise ValueError("journal stopped before the next available action")
            stopped = True
        else:
            raise ValueError("journal contains an unknown action")

    next_action = (
        "AwaitEvaluation" if pending is not None else
        "EvaluateCandidate" if queue and evaluations < max_evaluations else
        "SearchCandidates" if not queue and searches < max_searches else "Stop"
    )
    candidate_snapshots_verified = verify_search_snapshots(
        run_dir / "agent_candidates.jsonl", search_events, spec_id, seed,
    )
    model_call_bindings: list[tuple[str, str, str | None, str]] = []
    search_call_bindings: list[tuple[str, tuple[str, ...], str]] = []
    refiner_call_bindings: list[tuple[str, str, str | None, str]] = []
    if model_priorities or model_searches or model_refinements or (run_dir / "model_calls").exists():
        from .model_call_evidence import audit_model_calls

        model_report = audit_model_calls(run_dir)
        completed_calls = {call["call_id"]: call for call in model_report["calls"]}
        pending_calls = {call["call_id"]: call for call in model_report["pending_calls"]}
        used_call_ids: set[str] = set()
        for priority in model_priorities:
            call_id = priority["model_call_id"]
            if call_id in used_call_ids:
                raise ValueError("journal repeats a model call ID")
            used_call_ids.add(call_id)
            call = completed_calls.get(call_id)
            if call is not None:
                if (call["role"] != "Manager"
                        or call["journal_before_step"] != priority["step"] - 1
                        or call["journal_after_step"] != priority["step"] - 1
                        or (priority["source"] == "model"
                            and call["event"]["outcome"] != "completed")):
                    raise ValueError("journal priority differs from its completed model call")
            else:
                call = pending_calls.get(call_id)
                if (call is None or priority["source"] != "fallback"
                        or call["role"] != "Manager"
                        or call["journal_before_step"] != priority["step"] - 1):
                    raise ValueError("journal priority lacks a matching model call intent")
            following = events[priority["step"]] if priority["step"] < len(events) else None
            run_id = following.get("run_id") if following is not None else None
            model_call_bindings.append((call_id, priority["candidate_id"], run_id, priority["source"]))
        if stopped:
            manager_call_ids = {
                call["call_id"] for call in [*model_report["calls"], *model_report["pending_calls"]]
                if call["role"] == "Manager"
            }
            if manager_call_ids != used_call_ids:
                raise ValueError("terminal journal has an unbound Manager model call")
        used_search_call_ids: set[str] = set()
        for search_event in model_searches:
            call_id = search_event["model_call_id"]
            if call_id in used_search_call_ids:
                raise ValueError("journal repeats a Searcher model call ID")
            used_search_call_ids.add(call_id)
            call = completed_calls.get(call_id)
            if call is not None:
                if (call["role"] != "Searcher"
                        or call["journal_before_step"] != search_event["step"] - 1
                        or call["journal_after_step"] != search_event["step"] - 1
                        or (search_event["action"] == "SearchCandidates"
                            and call["event"]["outcome"] != "completed")):
                    raise ValueError("journal search differs from its completed model call")
            else:
                call = pending_calls.get(call_id)
                if (call is None or search_event["action"] != "SearchFailed"
                        or call["role"] != "Searcher"
                        or call["journal_before_step"] != search_event["step"] - 1):
                    raise ValueError("journal search lacks a matching model call intent")
            candidate_ids = tuple(search_event["candidate_ids"]) if search_event["action"] == "SearchCandidates" else ()
            search_call_bindings.append((call_id, candidate_ids, search_event["action"]))
        if stopped:
            searcher_call_ids = {
                call["call_id"] for call in [*model_report["calls"], *model_report["pending_calls"]]
                if call["role"] == "Searcher"
            }
            if searcher_call_ids != used_search_call_ids:
                raise ValueError("terminal journal has an unbound Searcher model call")
        used_refiner_call_ids: set[str] = set()
        for refinement in model_refinements:
            call_id = refinement["model_call_id"]
            if call_id in used_refiner_call_ids:
                raise ValueError("journal repeats a Refiner model call ID")
            used_refiner_call_ids.add(call_id)
            call = completed_calls.get(call_id)
            if call is not None:
                if (call["role"] != "Refiner"
                        or call["journal_before_step"] != refinement["step"] - 1
                        or call["journal_after_step"] != refinement["step"] - 1):
                    raise ValueError("journal refinement differs from its completed model call")
            else:
                call = pending_calls.get(call_id)
                if (call is None or call["role"] != "Refiner"
                        or call["journal_before_step"] != refinement["step"] - 1):
                    raise ValueError("journal refinement lacks a matching model call intent")
            refiner_call_bindings.append((
                call_id, refinement["candidate_id"], refinement["run_id"], refinement["status"],
            ))
        if stopped:
            refiner_call_ids = {
                call["call_id"] for call in [*model_report["calls"], *model_report["pending_calls"]]
                if call["role"] == "Refiner"
            }
            if refiner_call_ids != used_refiner_call_ids:
                raise ValueError("terminal journal has an unbound Refiner model call")
    trace_path = run_dir / "agent_trace.json"
    trace_verified = False
    if trace_path.exists() or trace_path.is_symlink():
        if not stopped or not trace_path.is_file() or trace_path.is_symlink():
            raise ValueError("trace is unsafe or has no terminal journal event")
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("trace is unreadable or malformed") from exc
        expected = {
            "schema_version": 1, "spec_id": spec_id, "seed": seed,
            "max_searches": max_searches, "searches_used": searches,
            "max_evaluations": max_evaluations, "evaluations_used": evaluations,
            "next_action": next_action, "queue_candidate_ids": queue,
            "pending_candidate_ids": [pending] if pending else [], "events": events,
        }
        if (
            not isinstance(trace, dict) or set(trace) != {*expected, "run_id"}
            or any(trace.get(key) != value for key, value in expected.items())
        ):
            raise ValueError("trace disagrees with the journal")
        if (run_dir / "evidence_manifest.json").exists():
            evidence = read_evidenced_metrics(run_dir)
            if evidence["run_id"] != run_dir.name or trace.get("run_id") != run_dir.name:
                raise ValueError("trace run_id disagrees with evidence")
        elif trace.get("run_id") is not None:
            raise ValueError("trace claims a run_id without evidence")
        trace_verified = True

    candidate_bindings_verified = False
    if candidate_runs_root is not None:
        if not isinstance(candidate_runs_root, Path) or not candidate_runs_root.is_dir() or candidate_runs_root.is_symlink():
            raise ValueError("candidate runs root is missing or unsafe")
        root = candidate_runs_root.resolve()
        for candidate_id, candidate_run_id, digest in bindings:
            candidate_dir = root / spec_id / f"seed{seed}" / candidate_id / candidate_run_id
            cursor = root
            for part in (spec_id, f"seed{seed}", candidate_id, candidate_run_id):
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError("candidate run path contains a symlink")
            if not candidate_dir.is_dir() or not candidate_dir.resolve().is_relative_to(root):
                raise ValueError("bound candidate run directory is missing or unsafe")
            manifest = candidate_dir / "evidence_manifest.json"
            if not manifest.is_file() or manifest.is_symlink():
                raise ValueError("bound candidate evidence manifest is missing or unsafe")
            if hashlib.sha256(manifest.read_bytes()).hexdigest() != digest:
                raise ValueError("bound candidate evidence manifest has changed")
            evidence = read_evidenced_metrics(candidate_dir)
            candidate = evidence.get("candidate")
            spec = evidence.get("spec")
            if (
                evidence.get("run_id") != candidate_run_id
                or evidence.get("seed") != seed
                or not isinstance(candidate, dict)
                or candidate.get("candidate_id") != candidate_id
                or candidate.get("seed") != seed
                or not isinstance(spec, dict)
                or spec.get("id") != spec_id
            ):
                raise ValueError("bound candidate evidence context disagrees with journal")
        candidate_bindings_verified = bool(bindings) and unbound_refinements == 0

    disposition = (
        "complete" if trace_verified else
        "terminal_snapshot_missing" if stopped else
        "reconcile_pending_evaluation" if pending is not None else "interrupted"
    )
    return JournalAudit(
        disposition, spec_id, seed, searches, evaluations,
        tuple(queue), pending, trace_verified,
        False, candidate_bindings_verified, candidate_snapshots_verified, spec_verified, pending_run_id,
        remote_identity_verified, bool(model_priorities), tuple(model_call_bindings),
        bool(model_searches), tuple(search_call_bindings),
        bool(model_refinements), tuple(refiner_call_bindings),
    )
