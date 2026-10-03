from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, TextIO

from ..cadence.evidence import read_evidenced_metrics
from ..schemas import Candidate, Spec
from .refiner import Refiner
from .searcher import Searcher
from .candidate_snapshots import serialize_search_snapshot
from .llm_manager import LLMManagerPolicy


class Manager:
    def __init__(
        self,
        searcher: Searcher | None = None,
        *,
        refiner: Refiner | None = None,
        priority_policy: LLMManagerPolicy | None = None,
        max_searches: int = 1,
        max_evaluations: int = 1,
    ) -> None:
        if any(type(limit) is not int or limit < 0 for limit in (max_searches, max_evaluations)):
            raise ValueError("search and evaluation budgets must be nonnegative integers")
        if refiner is not None and not isinstance(refiner, Refiner):
            raise TypeError("manager refiner must implement the Refiner contract")
        if priority_policy is not None and not isinstance(priority_policy, LLMManagerPolicy):
            raise TypeError("manager priority policy must implement the bounded model contract")
        self.searcher = searcher or Searcher()
        self.refiner = refiner or Refiner()
        self.priority_policy = priority_policy
        self.queue: list[Candidate] = []
        self.max_searches = max_searches
        self.max_evaluations = max_evaluations
        self.searches_used = 0
        self.evaluations_used = 0
        self.pending: dict[str, Candidate] = {}
        self.pending_run_ids: dict[str, str] = {}
        self.seen_ids: set[str] = set()
        self.trace: list[dict] = []
        self.context: tuple[str, int] | None = None
        self._journal: TextIO | None = None
        self._candidate_journal: BinaryIO | None = None

    def enable_journal(self, run_dir: Path) -> Path:
        if self._journal is not None or self._candidate_journal is not None or self.trace:
            raise ValueError("journal must be enabled before the first manager action")
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise ValueError("journal directory must be an existing non-symlink directory")
        path = run_dir / "agent_events.jsonl"
        candidate_path = run_dir / "agent_candidates.jsonl"
        if path.exists() or path.is_symlink() or candidate_path.exists() or candidate_path.is_symlink():
            raise FileExistsError("agent journal or candidate snapshot already exists")
        self._journal = path.open("x", encoding="utf-8")
        try:
            self._candidate_journal = candidate_path.open("xb")
        except Exception:
            self._journal.close()
            self._journal = None
            raise
        return path

    def close_journal(self) -> None:
        if self._journal is not None:
            self._journal.close()
            self._journal = None
        if self._candidate_journal is not None:
            self._candidate_journal.close()
            self._candidate_journal = None

    def attach_journal_for_resume(self, run_dir: Path) -> None:
        if self._journal is not None or self._candidate_journal is not None:
            raise ValueError("manager journal is already open")
        event_path = run_dir / "agent_events.jsonl"
        candidate_path = run_dir / "agent_candidates.jsonl"
        if any(not path.is_file() or path.is_symlink() for path in (event_path, candidate_path)):
            raise ValueError("resume journal files are missing or unsafe")
        self._journal = event_path.open("a", encoding="utf-8")
        try:
            self._candidate_journal = candidate_path.open("ab")
        except Exception:
            self._journal.close()
            self._journal = None
            raise

    def search_candidates(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if self.context is not None and self.context != (spec.id, seed):
            raise ValueError("manager cannot mix spec/seed contexts")
        if self.searches_used >= self.max_searches:
            return []
        candidates = self.searcher.search(spec, seed)
        if not isinstance(candidates, list):
            raise ValueError("searcher must return a candidate list")
        if any(
            not isinstance(candidate, Candidate)
            or not isinstance(candidate.candidate_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", candidate.candidate_id)
            or candidate.spec_id != spec.id
            or candidate.seed != seed
            for candidate in candidates
        ):
            raise ValueError("searcher returned a candidate with mismatched context")
        getter = getattr(self.searcher, "last_call_id", None)
        model_call_id = getter() if callable(getter) else None
        if model_call_id is not None and (
            not isinstance(model_call_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", model_call_id)
        ):
            raise ValueError("searcher model call ID is unsafe")
        new_candidates = []
        new_ids: set[str] = set()
        for candidate in candidates:
            if candidate.candidate_id not in self.seen_ids and candidate.candidate_id not in new_ids:
                new_ids.add(candidate.candidate_id)
                new_candidates.append(candidate)
        snapshot_digest = None
        if self._candidate_journal is not None:
            snapshot = serialize_search_snapshot(len(self.trace) + 1, new_candidates, spec.id, seed)
            if self._candidate_journal.tell() + len(snapshot) > 10_000_000:
                raise ValueError("candidate snapshot sidecar is too large")
            self._candidate_journal.write(snapshot)
            self._candidate_journal.flush()
            os.fsync(self._candidate_journal.fileno())
            snapshot_digest = hashlib.sha256(snapshot).hexdigest()
        self.seen_ids.update(new_ids)
        self.queue.extend(new_candidates)
        self.searches_used += 1
        self.context = (spec.id, seed)
        fields = {
            "count": len(new_candidates),
            "candidate_ids": [candidate.candidate_id for candidate in new_candidates],
        }
        if model_call_id is not None:
            fields["model_call_id"] = model_call_id
        if snapshot_digest is not None:
            fields["candidate_snapshot_sha256"] = snapshot_digest
        self._record("SearchCandidates", **fields)
        return new_candidates

    def next_action(self) -> str:
        if self.pending:
            return "AwaitEvaluation"
        if self.queue and self.evaluations_used < self.max_evaluations:
            return "EvaluateCandidate"
        if not self.queue and self.searches_used < self.max_searches:
            return "SearchCandidates"
        return "Stop"

    def pop_candidate(self, *, run_id: str | None = None) -> Candidate:
        if self.next_action() != "EvaluateCandidate":
            raise RuntimeError("no evaluation slot is available")
        if run_id is not None and (
            not isinstance(run_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id)
        ):
            raise ValueError("planned evaluation run ID is unsafe")
        candidate = self.queue.pop(0)
        self.pending[candidate.candidate_id] = candidate
        if run_id is not None:
            self.pending_run_ids[candidate.candidate_id] = run_id
        self.evaluations_used += 1
        fields = {"candidate_id": candidate.candidate_id}
        if run_id is not None:
            fields["run_id"] = run_id
        self._record("EvaluateCandidate", **fields)
        return candidate

    def prioritize_candidate(self, candidate_id: str, *, source: str,
                             model_call_id: str | None = None) -> None:
        if (
            self.next_action() != "EvaluateCandidate" or len(self.queue) < 2
            or source not in {"model", "fallback"}
            or not isinstance(candidate_id, str)
            or candidate_id not in {item.candidate_id for item in self.queue}
            or (source == "fallback" and candidate_id != self.queue[0].candidate_id)
            or (self.trace and self.trace[-1]["action"] == "QueuePriority")
            or (model_call_id is not None and (
                not isinstance(model_call_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", model_call_id)
            ))
        ):
            raise ValueError("manager priority choice is unavailable")
        index = next(i for i, item in enumerate(self.queue) if item.candidate_id == candidate_id)
        self.queue.insert(0, self.queue.pop(index))
        fields = {"candidate_id": candidate_id, "source": source}
        if model_call_id is not None:
            fields["model_call_id"] = model_call_id
        self._record("QueuePriority", **fields)

    def record_result(
        self, candidate: Candidate, run_dir: Path, spec: Spec, refiner: Refiner | None = None
    ) -> Candidate:
        if self.pending.get(candidate.candidate_id) is not candidate or candidate.spec_id != spec.id:
            raise ValueError("candidate is not awaiting this evaluation")
        planned_run_id = self.pending_run_ids.get(candidate.candidate_id)
        if planned_run_id is not None and run_dir.name != planned_run_id:
            raise ValueError("evaluator returned a run other than the planned dispatch")
        bound_run_id = None
        bound_manifest_sha256 = None
        try:
            manifest_path = run_dir / "evidence_manifest.json"
            manifest_before = manifest_path.read_bytes()
            evidence = read_evidenced_metrics(run_dir)
            manifest_after = manifest_path.read_bytes()
        except (OSError, TypeError, ValueError):
            pass
        else:
            if (
                manifest_before != manifest_after
                or evidence.get("run_id") != run_dir.name
                or evidence.get("candidate") != candidate.to_dict()
                or evidence.get("spec") != asdict(spec)
                or evidence.get("seed") != candidate.seed
            ):
                raise ValueError("evidenced run does not match the pending candidate and spec")
            bound_run_id = run_dir.name
            bound_manifest_sha256 = hashlib.sha256(manifest_before).hexdigest()
        if planned_run_id is not None and bound_run_id is None:
            raise ValueError("planned evaluation needs a complete matching evidence archive")
        selected_refiner = refiner or self.refiner
        refined = selected_refiner.refine_from_run(candidate, run_dir, spec)
        getter = getattr(selected_refiner, "last_call_id", None)
        model_call_id = getter() if callable(getter) else None
        if model_call_id is not None and (
            not isinstance(model_call_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", model_call_id)
        ):
            raise ValueError("refiner model call ID is unsafe")
        del self.pending[candidate.candidate_id]
        self.pending_run_ids.pop(candidate.candidate_id, None)
        fields = {
            "candidate_id": candidate.candidate_id, "status": refined.status,
            "run_id": bound_run_id, "evidence_manifest_sha256": bound_manifest_sha256,
        }
        if model_call_id is not None:
            fields["model_call_id"] = model_call_id
        self._record("RefineCandidate", **fields)
        return refined

    def record_evaluation_failure(self, candidate: Candidate, failure_code: str) -> Candidate:
        if self.pending.get(candidate.candidate_id) is not candidate:
            raise ValueError("candidate is not awaiting this evaluation")
        if failure_code not in {"backend_error", "backend_timeout", "invalid_run_directory"}:
            raise ValueError("unsupported evaluation failure code")
        del self.pending[candidate.candidate_id]
        self.pending_run_ids.pop(candidate.candidate_id, None)
        candidate.status = "needs_evaluation"
        self._record("EvaluationFailed", candidate_id=candidate.candidate_id, failure_code=failure_code)
        return candidate

    def save_trace(self, run_dir: Path) -> Path:
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise ValueError("trace run directory must be an existing non-symlink directory")
        run_id = None
        if (run_dir / "evidence_manifest.json").exists():
            evidence = read_evidenced_metrics(run_dir)
            if evidence["run_id"] != run_dir.name:
                raise ValueError("trace run_id disagrees with the evidence directory")
            run_id = evidence["run_id"]
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "spec_id": self.context[0] if self.context else None,
            "seed": self.context[1] if self.context else None,
            "max_searches": self.max_searches,
            "searches_used": self.searches_used,
            "max_evaluations": self.max_evaluations,
            "evaluations_used": self.evaluations_used,
            "next_action": self.next_action(),
            "queue_candidate_ids": [candidate.candidate_id for candidate in self.queue],
            "pending_candidate_ids": list(self.pending),
            "events": self.trace,
        }
        path = run_dir / "agent_trace.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        return path

    def _record(self, action: str, **fields: object) -> None:
        event = {"step": len(self.trace) + 1, "action": action, **fields}
        if self._journal is not None:
            self._journal.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            self._journal.flush()
            os.fsync(self._journal.fileno())
        self.trace.append(event)
