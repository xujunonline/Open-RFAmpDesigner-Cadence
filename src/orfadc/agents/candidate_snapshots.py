from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from ..schemas import Candidate


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SENSITIVE = re.compile(r"[\\]|://|(?:^|[\s=])(?:[A-Za-z]:[/\\]|/[^/\s]+/)|\b(?:password|api_key|secret|private_key|token|credential|bearer)\b", re.IGNORECASE)
_MAX_BATCH_BYTES = 65_536
_MAX_FILE_BYTES = 10_000_000


def _safe_value(value: object, depth: int = 0) -> None:
    if depth > 6:
        raise ValueError("candidate snapshot is too deeply nested")
    if value is None or type(value) is bool:
        return
    if type(value) in {int, float}:
        if not math.isfinite(value):
            raise ValueError("candidate snapshot contains a nonfinite number")
        return
    if isinstance(value, str):
        if (len(value) > 256 or any(ord(char) < 32 or ord(char) > 126 for char in value)
                or _SENSITIVE.search(value)):
            raise ValueError("candidate snapshot contains unsafe text")
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise ValueError("candidate snapshot list is too large")
        for item in value:
            _safe_value(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 64 or any(
            not isinstance(key, str) or not _KEY.fullmatch(key) or _SENSITIVE.search(key)
            for key in value
        ):
            raise ValueError("candidate snapshot map has unsafe keys")
        for item in value.values():
            _safe_value(item, depth + 1)
        return
    raise ValueError("candidate snapshot contains an unsupported value")


def _validate_candidate(data: object, spec_id: str, seed: int) -> None:
    fields = {"candidate_id", "spec_id", "seed", "power_ratio_list", "active_params",
              "passive_params", "sim_result", "status", "notes"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("candidate snapshot has unexpected fields")
    if (
        not isinstance(data["candidate_id"], str) or not _ID.fullmatch(data["candidate_id"])
        or data["spec_id"] != spec_id or type(data["seed"]) is not int or data["seed"] != seed
        or not isinstance(data["power_ratio_list"], list)
        or len(data["power_ratio_list"]) > 16
        or any(type(value) not in {int, float} or not math.isfinite(value) or value < 0
               for value in data["power_ratio_list"])
        or not isinstance(data["active_params"], dict)
        or not isinstance(data["passive_params"], dict)
        or data["sim_result"] is not None or data["notes"] != []
        or not isinstance(data["status"], str) or not _ID.fullmatch(data["status"])
    ):
        raise ValueError("candidate snapshot is not a bounded unevaluated proposal")
    _safe_value(data)


def serialize_search_snapshot(
    search_step: int, candidates: list[Candidate], spec_id: str, seed: int,
) -> bytes:
    if type(search_step) is not int or search_step < 1:
        raise ValueError("candidate snapshot search step is invalid")
    data = [candidate.to_dict() for candidate in candidates]
    for item in data:
        _validate_candidate(item, spec_id, seed)
    encoded = (
        json.dumps({"search_step": search_step, "candidates": data},
                   sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("ascii")
    if len(encoded) > _MAX_BATCH_BYTES:
        raise ValueError("candidate snapshot batch is too large")
    return encoded


def verify_search_snapshots(
    path: Path, search_events: list[dict], spec_id: str, seed: int,
) -> bool:
    has_digests = any("candidate_snapshot_sha256" in event for event in search_events)
    if not path.exists() and not path.is_symlink():
        if has_digests:
            raise ValueError("candidate snapshot sidecar is missing")
        return False
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("candidate snapshot sidecar is unsafe")
    if not all("candidate_snapshot_sha256" in event for event in search_events):
        raise ValueError("candidate snapshot sidecar has unbound search events")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("candidate snapshot sidecar has an incomplete record")
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(search_events):
        raise ValueError("candidate snapshot count disagrees with search events")
    for line, event in zip(lines, search_events, strict=True):
        if len(line) > _MAX_BATCH_BYTES or hashlib.sha256(line).hexdigest() != event["candidate_snapshot_sha256"]:
            raise ValueError("candidate snapshot digest disagrees with journal")
        try:
            record = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("candidate snapshot record is malformed") from exc
        if (not isinstance(record, dict) or set(record) != {"search_step", "candidates"}
                or record["search_step"] != event["step"]
                or not isinstance(record["candidates"], list)
                or [item.get("candidate_id") if isinstance(item, dict) else None
                    for item in record["candidates"]] != event["candidate_ids"]):
            raise ValueError("candidate snapshot identities disagree with journal")
        for candidate in record["candidates"]:
            _validate_candidate(candidate, spec_id, seed)
        if serialize_search_snapshot(
            event["step"], [Candidate(**item) for item in record["candidates"]], spec_id, seed,
        ) != line:
            raise ValueError("candidate snapshot is not canonical")
    return True
