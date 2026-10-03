from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from orfadc.metric_contract import validate_metrics_payload


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FULLCHAIN_ARTIFACTS = frozenset({
    "metrics", "candidate", "netlist", "spectre_log", "waveforms",
    "dc_raw", "sp_raw", "noise_raw", "compression_raw",
})
_NONEMPTY_ARTIFACTS = _FULLCHAIN_ARTIFACTS | {"netlist", "spectre_log", "sp_raw", "noise_raw"}


def _artifact_path(run_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("artifact path must be a portable relative path")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(relative).is_absolute():
        raise ValueError("artifact path must not escape the run directory")
    path = run_dir.joinpath(*parts)
    current = path
    while current != run_dir:
        if current.is_symlink():
            raise ValueError("symlinked artifacts are not accepted")
        current = current.parent
    if not path.is_file() or not path.resolve().is_relative_to(run_dir.resolve()):
        raise ValueError(f"missing or out-of-tree artifact: {relative}")
    return path


def _digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return path.stat().st_size, digest.hexdigest()


def _read_metrics(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid metrics.json") from exc
    if not isinstance(payload, dict):
        raise ValueError("metrics.json must contain an object")
    validate_metrics_payload(payload)
    return payload


def _required_artifacts(payload: dict[str, Any]) -> set[str]:
    required = {"metrics"}
    if payload.get("candidate") is not None:
        required.add("candidate")
    if payload.get("simulation_status") == "ok":
        required.update({"netlist", "spectre_log"})
    if payload.get("spec_pass") is True:
        required.update(_FULLCHAIN_ARTIFACTS)
    return required


def _check_payload_evidence(payload: dict[str, Any], paths: dict[str, Path]) -> None:
    missing = _required_artifacts(payload) - paths.keys()
    if missing:
        raise ValueError(f"run evidence missing artifacts: {', '.join(sorted(missing))}")
    if paths["metrics"].name != "metrics.json":
        raise ValueError("metrics artifact must be metrics.json")
    if "candidate" in paths:
        if payload.get("candidate") is None:
            raise ValueError("candidate snapshot has no metrics context")
        if paths["candidate"].name != "candidate.json":
            raise ValueError("candidate artifact must be candidate.json")
        try:
            snapshot = json.loads(paths["candidate"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid candidate.json") from exc
        if not isinstance(snapshot, dict) or any(
            snapshot.get(key) != value for key, value in payload["candidate"].items()
        ):
            raise ValueError("candidate snapshot disagrees with metrics")
    if payload.get("simulation_status") == "ok":
        if any(path.stat().st_size == 0 for key, path in paths.items() if key in _NONEMPTY_ARTIFACTS):
            raise ValueError("successful run contains an empty required artifact")
        log = paths["spectre_log"].read_text(encoding="utf-8", errors="replace")
        if "spectre completes with 0 errors" not in log or "SPECTRE-25" in log:
            raise ValueError("spectre.log lacks clean completion evidence")


def build_evidence_manifest(run_dir: Path, artifacts: Mapping[str, str]) -> dict[str, Any]:
    if not run_dir.is_dir() or not isinstance(artifacts, Mapping) or not artifacts or "metrics" not in artifacts:
        raise ValueError("run directory and metrics artifact are required")
    if any(not isinstance(key, str) or not _KEY_RE.fullmatch(key) for key in artifacts):
        raise ValueError("invalid artifact key")
    if any(not isinstance(relative, str) for relative in artifacts.values()):
        raise ValueError("artifact paths must be strings")
    if len(set(artifacts.values())) != len(artifacts):
        raise ValueError("each artifact must have a distinct path")
    paths = {key: _artifact_path(run_dir, relative) for key, relative in artifacts.items()}
    payload = _read_metrics(paths["metrics"])
    _check_payload_evidence(payload, paths)
    entries = {}
    for key, path in sorted(paths.items()):
        size, digest = _digest(path)
        entries[key] = {"path": artifacts[key], "size_bytes": size, "sha256": digest}
    return {
        "schema_version": 1,
        "run_id": payload["run_id"],
        "artifacts": entries,
    }


def verify_evidence_manifest(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("invalid evidence manifest version")
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("evidence manifest has no artifacts")
    artifacts: dict[str, str] = {}
    for key, entry in entries.items():
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or not isinstance(entry, dict):
            raise ValueError("invalid evidence artifact entry")
        if set(entry) != {"path", "size_bytes", "sha256"}:
            raise ValueError("invalid evidence artifact fields")
        path = _artifact_path(run_dir, entry["path"])
        size, digest = _digest(path)
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] != size or entry["sha256"] != digest:
            raise ValueError(f"artifact hash or size mismatch: {key}")
        artifacts[key] = entry["path"]
    if len(set(artifacts.values())) != len(artifacts):
        raise ValueError("evidence artifacts share a path")
    paths = {key: _artifact_path(run_dir, relative) for key, relative in artifacts.items()}
    if "metrics" not in paths:
        raise ValueError("metrics artifact is required")
    payload = _read_metrics(paths["metrics"])
    if manifest.get("run_id") != payload["run_id"]:
        raise ValueError("evidence run_id disagrees with metrics")
    _check_payload_evidence(payload, paths)
    return payload


def write_evidence_manifest(run_dir: Path, artifacts: Mapping[str, str]) -> Path:
    manifest = build_evidence_manifest(run_dir, artifacts)
    path = run_dir / "evidence_manifest.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return path


def read_evidenced_metrics(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "evidence_manifest.json"
    if path.is_symlink():
        raise ValueError("symlinked evidence manifest is not accepted")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid or missing evidence_manifest.json") from exc
    return verify_evidence_manifest(run_dir, manifest)
