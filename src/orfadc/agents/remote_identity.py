from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ..cadence.remote_runner import RemoteCadenceConfig


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {
    "schema_version", "host", "user", "port", "remote_root",
    "identity_file", "strict_host_key_checking",
}


def remote_identity(config: RemoteCadenceConfig) -> dict:
    if not isinstance(config, RemoteCadenceConfig):
        raise TypeError("remote identity requires a validated Cadence config")
    return {
        "schema_version": 1,
        "host": config.host,
        "user": config.user,
        "port": config.port,
        "remote_root": config.remote_root,
        "identity_file": str(config.identity_file.resolve()) if config.identity_file else None,
        "strict_host_key_checking": config.strict_host_key_checking,
    }


def _encode(identity: dict) -> bytes:
    return (json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def write_remote_identity_snapshot(run_dir: Path, config: RemoteCadenceConfig) -> str:
    payload = _encode(remote_identity(config))
    with (run_dir / "agent_remote.json").open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def read_remote_identity_snapshot(run_dir: Path, digest: str) -> dict:
    path = run_dir / "agent_remote.json"
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("agent remote identity digest is invalid")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("agent remote identity snapshot is missing or unsafe")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("agent remote identity snapshot digest differs")
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("agent remote identity snapshot is malformed") from exc
    if (
        not isinstance(data, dict) or set(data) != _FIELDS
        or type(data["schema_version"]) is not int or data["schema_version"] != 1
        or type(data["port"]) is not int
        or (data["identity_file"] is not None and not isinstance(data["identity_file"], str))
    ):
        raise ValueError("agent remote identity snapshot has unexpected fields")
    try:
        config = RemoteCadenceConfig(
            host=data["host"], user=data["user"], port=data["port"],
            remote_root=data["remote_root"],
            identity_file=Path(data["identity_file"]) if data["identity_file"] else None,
            strict_host_key_checking=data["strict_host_key_checking"],
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("agent remote identity values are invalid") from exc
    if data != remote_identity(config) or _encode(data) != raw:
        raise ValueError("agent remote identity snapshot is not canonical")
    return data
