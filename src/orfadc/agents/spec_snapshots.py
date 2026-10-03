from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from ..schemas import Spec


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"id", "fc_ghz", "fbw_ratio", "power_ma", "gain_db", "nf_max_db", "ip1db_min_dbm"}


def _encode(spec: Spec) -> bytes:
    return (json.dumps(asdict(spec), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def write_spec_snapshot(run_dir: Path, spec: Spec) -> str:
    payload = _encode(spec)
    with (run_dir / "agent_spec.json").open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def read_spec_snapshot(run_dir: Path, digest: str) -> Spec:
    path = run_dir / "agent_spec.json"
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("agent spec digest is invalid")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("agent spec snapshot is missing or unsafe")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("agent spec snapshot digest differs")
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("agent spec snapshot is malformed") from exc
    if not isinstance(data, dict) or set(data) != _FIELDS or not isinstance(data["id"], str):
        raise ValueError("agent spec snapshot has unexpected fields")
    spec = Spec(**data)
    if _encode(spec) != raw:
        raise ValueError("agent spec snapshot is not canonical")
    return spec
