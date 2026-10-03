from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from orfadc.agents.run_lock import agent_run_lock
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_CALL_ID = re.compile(r"[0-9a-f]{32}\Z")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00\Z")
_ROLES = {"Manager", "Searcher", "Refiner"}
_OUTCOMES = {"completed", "incomplete_response", "empty_output", "transport_error"}
_TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
_EVENT_FIELDS = {"model_requested", "model_reported", "outcome", "latency_seconds", *_TOKEN_FIELDS}
_INTENT_FIELDS = {
    "schema_version", "call_id", "role", "trace_id", "model_requested",
    "agent_journal_sha256_before", "started_at_utc",
}
_RESULT_FIELDS = {
    "schema_version", "call_id", "intent_sha256", "agent_journal_sha256_after",
    "completed_at_utc", "event",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _safe_run_dir(trace_dir: Path) -> Path:
    if not isinstance(trace_dir, Path) or ".." in trace_dir.parts or not trace_dir.is_dir():
        raise ValueError("model call trace directory is unavailable")
    if _PRIVATE_ROOT.is_symlink():
        raise ValueError("private model call root is symlinked")
    root = _PRIVATE_ROOT.resolve()
    if not trace_dir.resolve().is_relative_to(root):
        raise ValueError("model call evidence must stay in private results/runs")
    cursor = trace_dir
    while True:
        if cursor.is_symlink():
            raise ValueError("model call evidence path is symlinked")
        if cursor.resolve() == root:
            break
        if cursor.parent == cursor:
            raise ValueError("model call path has no private root ancestor")
        cursor = cursor.parent
    if not _ID.fullmatch(trace_dir.name):
        raise ValueError("model call trace identifier is unsafe")
    return trace_dir


def _journal_bytes(trace_dir: Path) -> bytes:
    path = trace_dir / "agent_events.jsonl"
    if not path.is_file() or path.is_symlink():
        raise ValueError("agent event journal is missing or unsafe")
    data = path.read_bytes()
    if not data or len(data) > 10_000_000 or not data.endswith(b"\n"):
        raise ValueError("agent event journal is incomplete or oversized")
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("agent event journal contains malformed JSON") from exc
        if not isinstance(event, dict) or not isinstance(event.get("action"), str):
            raise ValueError("agent event journal contains an invalid action")
    return data


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(encoded) > 4096:
        raise ValueError("model call metadata exceeds the size limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _json_object(path: Path, expected: set[str]) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("model call evidence file is missing or unsafe")
    raw = path.read_bytes()
    if not raw or len(raw) > 4096:
        raise ValueError("model call evidence file is empty or oversized")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("model call evidence has duplicate keys")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("nonfinite model call metadata")

    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                       parse_constant=reject_constant)
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("model call evidence schema differs")
    return value


def _validate_event(event: dict[str, Any]) -> None:
    if not isinstance(event, dict) or set(event) != _EVENT_FIELDS:
        raise ValueError("model call event schema differs")
    if not isinstance(event["model_requested"], str) or not _ID.fullmatch(event["model_requested"]):
        raise ValueError("model call request model is unsafe")
    reported = event["model_reported"]
    if reported is not None and (not isinstance(reported, str) or not _ID.fullmatch(reported)):
        raise ValueError("model call reported model is unsafe")
    if event["outcome"] not in _OUTCOMES:
        raise ValueError("model call outcome is invalid")
    latency = event["latency_seconds"]
    if type(latency) not in {int, float} or not math.isfinite(latency) or not 0 <= latency <= 86400:
        raise ValueError("model call latency is invalid")
    for key in _TOKEN_FIELDS:
        count = event[key]
        if count is not None and (type(count) is not int or not 0 <= count <= 1_000_000_000_000):
            raise ValueError("model call token count is invalid")
    input_count = event["input_tokens"]
    output_count = event["output_tokens"]
    if input_count is not None:
        for key in ("cached_input_tokens", "cache_write_input_tokens"):
            if event[key] is not None and event[key] > input_count:
                raise ValueError("model call input token breakdown is invalid")
        cached, written = event["cached_input_tokens"], event["cache_write_input_tokens"]
        if cached is not None and written is not None and cached + written > input_count:
            raise ValueError("model call input token categories overlap")
    if output_count is not None and event["reasoning_output_tokens"] is not None:
        if event["reasoning_output_tokens"] > output_count:
            raise ValueError("model call reasoning count exceeds output")
    total = event["total_tokens"]
    if total is not None and input_count is not None and output_count is not None:
        if total != input_count + output_count:
            raise ValueError("model call total token count differs")


class ModelCallEvidence:
    """Write-once intent/result files; a missing result remains an unknown-cost attempt."""

    def __init__(self, trace_dir: Path, *, role: str) -> None:
        self.trace_dir = _safe_run_dir(trace_dir)
        if role not in _ROLES:
            raise ValueError("model call role is unavailable")
        self.role = role
        self.calls_dir = trace_dir / "model_calls"
        if self.calls_dir.is_symlink():
            raise ValueError("model call directory is symlinked")
        self.calls_dir.mkdir(exist_ok=True)
        if not self.calls_dir.is_dir() or self.calls_dir.is_symlink():
            raise ValueError("model call directory is unsafe")

    def begin(self, model_requested: str) -> str:
        if not isinstance(model_requested, str) or not _ID.fullmatch(model_requested):
            raise ValueError("model call model identifier is unsafe")
        with agent_run_lock(self.calls_dir):
            prior = audit_model_calls(self.trace_dir)
            if prior["pending_call_ids"]:
                raise RuntimeError("an unresolved model call prohibits another request")
            journal = _journal_bytes(self.trace_dir)
            if json.loads(journal.splitlines()[-1]).get("action") == "Stop":
                raise RuntimeError("a terminal agent journal prohibits another model request")
            call_id = uuid4().hex
            intent = {
                "schema_version": 1, "call_id": call_id, "role": self.role,
                "trace_id": self.trace_dir.name, "model_requested": model_requested,
                "agent_journal_sha256_before": _sha(journal),
                "started_at_utc": datetime.now(UTC).isoformat(),
            }
            _write_once(self.calls_dir / f"{call_id}.intent.json", intent)
        return call_id

    def finish(self, call_id: str, event: dict[str, Any]) -> None:
        if not isinstance(call_id, str) or not _CALL_ID.fullmatch(call_id):
            raise ValueError("model call identifier is unsafe")
        _validate_event(event)
        intent_path = self.calls_dir / f"{call_id}.intent.json"
        intent = _json_object(intent_path, _INTENT_FIELDS)
        if (intent["call_id"] != call_id or intent["role"] != self.role
                or intent["trace_id"] != self.trace_dir.name
                or intent["model_requested"] != event["model_requested"]):
            raise ValueError("model call result differs from its intent")
        result = {
            "schema_version": 1, "call_id": call_id,
            "intent_sha256": _sha(intent_path.read_bytes()),
            "agent_journal_sha256_after": _sha(_journal_bytes(self.trace_dir)),
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "event": event,
        }
        _write_once(self.calls_dir / f"{call_id}.result.json", result)


def audit_model_calls(trace_dir: Path) -> dict[str, Any]:
    """Read-only audit of metadata files and their agent-journal prefix bindings."""
    trace_dir = _safe_run_dir(trace_dir)
    journal = _journal_bytes(trace_dir)
    digest = hashlib.sha256()
    prefixes = {digest.hexdigest(): 0}
    for position, line in enumerate(journal.splitlines(keepends=True), start=1):
        digest.update(line)
        prefixes[digest.hexdigest()] = position
    calls_dir = trace_dir / "model_calls"
    if not calls_dir.is_dir() or calls_dir.is_symlink():
        raise ValueError("model call directory is missing or unsafe")
    files = list(calls_dir.iterdir())
    if len(files) > 10000:
        raise ValueError("model call archive is oversized")
    intents: dict[str, Path] = {}
    results: dict[str, Path] = {}
    for path in files:
        if path.name == "agent_writer.lock":
            if not path.is_file() or path.is_symlink():
                raise ValueError("model call writer lock is unsafe")
            continue
        match = re.fullmatch(r"([0-9a-f]{32})\.(intent|result)\.json", path.name)
        if match is None or not path.is_file() or path.is_symlink():
            raise ValueError("model call archive contains an unexpected file")
        (intents if match[2] == "intent" else results)[match[1]] = path
    if results.keys() - intents.keys():
        raise ValueError("model call result has no intent")
    pending = []
    pending_calls = []
    completed = []
    for call_id, intent_path in sorted(intents.items()):
        intent = _json_object(intent_path, _INTENT_FIELDS)
        if (intent["schema_version"] != 1 or intent["call_id"] != call_id
                or intent["trace_id"] != trace_dir.name or intent["role"] not in _ROLES
                or not isinstance(intent["model_requested"], str)
                or not _ID.fullmatch(intent["model_requested"])
                or not _timestamp(intent["started_at_utc"])
                or intent["agent_journal_sha256_before"] not in prefixes):
            raise ValueError("model call intent is not bound to this agent journal")
        if call_id not in results:
            pending.append(call_id)
            pending_calls.append({
                "call_id": call_id, "role": intent["role"],
                "journal_before_step": prefixes[intent["agent_journal_sha256_before"]],
            })
            continue
        result = _json_object(results[call_id], _RESULT_FIELDS)
        if (result["schema_version"] != 1 or result["call_id"] != call_id
                or result["intent_sha256"] != _sha(intent_path.read_bytes())
                or not _timestamp(result["completed_at_utc"])
                or result["agent_journal_sha256_after"] not in prefixes
                or prefixes[result["agent_journal_sha256_after"]]
                < prefixes[intent["agent_journal_sha256_before"]]):
            raise ValueError("model call result is not bound to this intent and journal")
        _validate_event(result["event"])
        if result["event"]["model_requested"] != intent["model_requested"]:
            raise ValueError("model call recorded a different model")
        completed.append({
            "call_id": call_id, "role": intent["role"], "event": result["event"],
            "journal_before_step": prefixes[intent["agent_journal_sha256_before"]],
            "journal_after_step": prefixes[result["agent_journal_sha256_after"]],
        })
    return {
        "schema_version": 1, "trace_id": trace_dir.name,
        "attempts": len(intents), "completed": len(completed),
        "pending_call_ids": pending, "pending_calls": pending_calls, "calls": completed,
        "pricing_counts_reported": bool(intents) and not pending and all(
            all(item["event"][key] is not None for key in (
                "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "total_tokens",
            ))
            for item in completed
        ),
    }
