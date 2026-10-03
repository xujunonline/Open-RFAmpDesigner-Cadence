from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Callable
from uuid import uuid4

from orfadc.agents.journal import inspect_journal
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Candidate


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REMOTE_ARTIFACTS = (
    "netlist.scs", "ade_e.scs", "spectre.log",
    "psf/dcOp.dc", "psf/sp.sp", "psf/sp.noise.sp",
)
_REMOTE_SCRIPT = r'''
target="$1"
if [ -L "$target" ]; then
  directory=symlink
elif [ -d "$target" ]; then
  directory=present
else
  directory=missing
fi
active=0
log=0
sp=0
noise=0
if [ "$directory" = present ]; then
  [ -s "$target/spectre.log" ] && log=1
  [ -s "$target/psf/sp.sp" ] && sp=1
  [ -s "$target/psf/sp.noise.sp" ] && noise=1
  for process in /proc/[0-9]*; do
    [ -r "$process/comm" ] || continue
    IFS= read -r name < "$process/comm" || continue
    case "$name" in spectre*|SPECTRE*) ;; *) continue ;; esac
    working_dir="$(readlink "$process/cwd" 2>/dev/null)" || continue
    case "$working_dir" in "$target"|"$target"/*) active=1 ;; esac
  done
fi
printf 'directory=%s\nactive=%s\nlog=%s\nsp=%s\nnoise=%s\n' \
  "$directory" "$active" "$log" "$sp" "$noise"
'''


def probe_remote_diagnostic_directory(runner: RemoteRunner, remote_dir: str) -> dict:
    """Observe a single named run directory without modifying or restarting a job."""
    path = PurePosixPath(remote_dir)
    if (
        not path.is_absolute() or ".." in path.parts or str(path) != remote_dir
        or not re.fullmatch(r"/[A-Za-z0-9._/+\-]+", remote_dir)
    ):
        raise ValueError("remote diagnostic path is unsafe")
    result = runner.run_remote(["bash", "-c", _REMOTE_SCRIPT, "--", remote_dir], timeout_seconds=30)
    if not result.ok or len(result.stdout) > 1024:
        return {"state": "unknown", "reason": "remote_probe_failed"}
    lines = result.stdout.strip().splitlines()
    if len(lines) != 5:
        return {"state": "unknown", "reason": "remote_probe_malformed"}
    fields = {}
    for line in lines:
        if "=" not in line:
            return {"state": "unknown", "reason": "remote_probe_malformed"}
        key, value = line.split("=", 1)
        if key in fields:
            return {"state": "unknown", "reason": "remote_probe_malformed"}
        fields[key] = value
    if (
        set(fields) != {"directory", "active", "log", "sp", "noise"}
        or fields["directory"] not in {"present", "missing", "symlink"}
        or any(fields[key] not in {"0", "1"} for key in ("active", "log", "sp", "noise"))
        or (fields["directory"] != "present" and any(
            fields[key] != "0" for key in ("active", "log", "sp", "noise")
        ))
    ):
        return {"state": "unknown", "reason": "remote_probe_malformed"}
    if fields["directory"] == "symlink":
        return {"state": "unsafe_remote_directory"}
    return {
        "state": "observed", "directory": fields["directory"],
        "spectre_active": fields["active"] == "1",
        "spectre_log_present": fields["log"] == "1",
        "sp_raw_present": fields["sp"] == "1",
        "noise_raw_present": fields["noise"] == "1",
    }


def _remote_artifact_hashes(runner: RemoteRunner, remote_dir: str) -> dict[str, str] | None:
    result = runner.run_remote(
        ["sha256sum", "--", *_REMOTE_ARTIFACTS], cwd=remote_dir, timeout_seconds=30,
    )
    if not result.ok or len(result.stdout) > 4096:
        return None
    lines = result.stdout.splitlines()
    if len(lines) != len(_REMOTE_ARTIFACTS):
        return None
    hashes = {}
    for name, line in zip(_REMOTE_ARTIFACTS, lines, strict=True):
        digest, separator, recorded_name = line.partition("  ")
        if separator != "  " or recorded_name != name or not _SHA256.fullmatch(digest):
            return None
        hashes[name] = digest
    return hashes


def snapshot_remote_diagnostic_artifacts(
    runner: RemoteRunner, remote_dir: str, *, wait_seconds: float = 3.0,
    waiter: Callable[[float], None] = time.sleep,
) -> dict:
    """Observe two quiescent remote hashes; this never certifies a completed simulation."""
    if (type(wait_seconds) not in {int, float} or not math.isfinite(wait_seconds)
            or not 1 <= wait_seconds <= 10):
        raise ValueError("stable-artifact observation interval must be 1..10 seconds")
    first = probe_remote_diagnostic_directory(runner, remote_dir)
    if first["state"] != "observed":
        return {"status": "remote_unknown", "safe_to_adopt": False}
    if first["directory"] != "present":
        return {"status": "remote_missing", "safe_to_adopt": False}
    if first["spectre_active"]:
        return {"status": "spectre_in_flight", "safe_to_adopt": False}
    before = _remote_artifact_hashes(runner, remote_dir)
    if before is None:
        return {"status": "remote_artifacts_unavailable", "safe_to_adopt": False}
    waiter(float(wait_seconds))
    second = probe_remote_diagnostic_directory(runner, remote_dir)
    if second["state"] != "observed" or second["directory"] != "present":
        return {"status": "remote_unknown", "safe_to_adopt": False}
    if second["spectre_active"]:
        return {"status": "spectre_in_flight", "safe_to_adopt": False}
    after = _remote_artifact_hashes(runner, remote_dir)
    if after is None:
        return {"status": "remote_artifacts_unavailable", "safe_to_adopt": False}
    if before != after:
        return {"status": "remote_artifacts_changed", "safe_to_adopt": False}
    return {
        "status": "stable_unverified", "artifacts_sha256": after,
        "observations": 2, "wait_seconds": float(wait_seconds),
        "safe_to_adopt": False,
    }


def inspect_pending_diagnostic_remote(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner, *, stable_artifacts: bool = False,
) -> dict:
    """Classify one planned pending diagnostic run; never dispatch or adopt its archive."""
    _require_private_path(trace_dir)
    _require_private_path(runs_root)
    if type(stable_artifacts) is not bool:
        raise ValueError("stable_artifacts must be a boolean")
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise ValueError("candidate runs root is missing or unsafe")
    with agent_run_lock(trace_dir):
        audit = inspect_journal(trace_dir)
        if (
            audit.disposition != "reconcile_pending_evaluation"
            or not audit.spec_verified or not audit.candidate_snapshots_verified
            or not audit.remote_identity_verified
            or audit.pending_candidate_id is None or audit.pending_run_id is None
            or audit.searches_used != 1 or audit.evaluations_used != 1
            or (trace_dir / "agent_trace.json").exists()
        ):
            raise ValueError("trace is not a planned pending diagnostic run")
        journal = (trace_dir / "agent_events.jsonl").read_bytes()
        start = json.loads(journal.splitlines()[0])
        if (
            start.get("dispatch_mode") != "planned"
            or start["max_searches"] != 1 or start["max_evaluations"] != 1
        ):
            raise ValueError("pending diagnostic lacks the one-run planned context")
        bound_remote = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        if bound_remote != remote_identity(runner.config):
            raise ValueError("current remote config differs from the planned dispatch")
        spec = read_spec_snapshot(trace_dir, start["spec_sha256"])
        if spec.id != audit.spec_id:
            raise ValueError("pending diagnostic spec snapshot changed")
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 1 or len(snapshots[0]["candidates"]) != 1:
            raise ValueError("pending diagnostic needs exactly one candidate snapshot")
        candidate = Candidate(**snapshots[0]["candidates"][0])
        params = candidate.active_params
        if (
            candidate.candidate_id != audit.pending_candidate_id
            or candidate.spec_id != spec.id or candidate.seed != audit.seed
            or candidate.status != "active_common_source_diagnostic"
            or candidate.power_ratio_list != [] or candidate.passive_params
            or candidate.sim_result is not None or not isinstance(params, dict)
            or set(params) != {"rd_ohm", "vbias_v"}
            or any(type(params[key]) not in {int, float} or not math.isfinite(params[key])
                   for key in params)
            or not 50 <= params["rd_ohm"] <= 1000
            or not 0.4 <= params["vbias_v"] <= 0.8
        ):
            raise ValueError("pending candidate is not the bounded OA diagnostic")
        config = runner.config
        remote_name = (
            f"rf_active_{spec.id}_seed{audit.seed}_{candidate.candidate_id}_{audit.pending_run_id}"
        )
        remote_dir = str(PurePosixPath(config.remote_root) / remote_name)
        remote = probe_remote_diagnostic_directory(runner, remote_dir)
        artifact_snapshot = (
            snapshot_remote_diagnostic_artifacts(runner, remote_dir)
            if stable_artifacts and remote["state"] == "observed"
            and remote["directory"] == "present" and not remote["spectre_active"]
            else None
        )
        cursor = runs_root
        for part in (spec.id, f"seed{audit.seed}", candidate.candidate_id, audit.pending_run_id):
            if not _ID.fullmatch(part):
                raise ValueError("pending run path contains an unsafe identifier")
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("pending local archive path is symlinked")
        local_state = "absent"
        if cursor.exists():
            if not cursor.is_dir() or not cursor.resolve().is_relative_to(runs_root.resolve()):
                raise ValueError("pending local archive path is unsafe")
            local_state = "incomplete"
            if (cursor / "evidence_manifest.json").exists():
                try:
                    evidence = read_evidenced_metrics(cursor)
                except (OSError, ValueError, TypeError):
                    local_state = "invalid_manifest"
                else:
                    local_state = "hash_verified_raw_audit_pending" if (
                        evidence.get("run_id") == cursor.name
                        and evidence.get("candidate") == candidate.to_dict()
                        and evidence.get("spec") == asdict(spec)
                    ) else "context_mismatch"
        if remote["state"] != "observed":
            disposition = "remote_unsafe" if remote["state"] == "unsafe_remote_directory" else "remote_unknown"
        elif remote["spectre_active"]:
            disposition = "spectre_in_flight"
        elif local_state in {"invalid_manifest", "context_mismatch"}:
            disposition = "local_archive_invalid"
        elif local_state == "hash_verified_raw_audit_pending":
            disposition = "local_raw_audit_required"
        elif remote["directory"] == "present":
            snapshot_status = artifact_snapshot["status"] if artifact_snapshot is not None else None
            disposition = {
                None: "remote_quiescent_unverified",
                "stable_unverified": "remote_quiescent_raw_audit_required",
                "remote_artifacts_unavailable": "remote_quiescent_incomplete",
                "remote_artifacts_changed": "remote_artifacts_changing",
                "spectre_in_flight": "spectre_in_flight",
            }.get(snapshot_status, "remote_unknown")
        else:
            disposition = "dispatch_not_observed"
        return {
            "schema_version": 1, "status": disposition,
            "observed_at_utc": datetime.now(UTC).isoformat(),
            "spec_id": spec.id, "seed": audit.seed,
            "candidate_id": candidate.candidate_id, "candidate_run_id": audit.pending_run_id,
            "journal_sha256": hashlib.sha256(journal).hexdigest(),
            "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
            "remote": remote, "local_archive": local_state,
            "artifact_snapshot": artifact_snapshot,
            "safe_to_dispatch": False, "spectre_dispatched_by_probe": False,
            "not_lna_result": True, "spec_pass": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only remote status for one planned OA diagnostic run")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--stable-artifacts", action="store_true")
    args = parser.parse_args()
    try:
        runner = RemoteRunner(load_remote_config(args.config))
        report = inspect_pending_diagnostic_remote(
            args.trace_dir, args.runs_root, runner, stable_artifacts=args.stable_artifacts,
        )
        path = args.trace_dir / (
            "pending_remote_probe_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "_" + uuid4().hex[:8] + ".json"
        )
        write_json(path, report)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"remote pending probe rejected: {type(exc).__name__}")
    print(f"status={report['status']} local={report['local_archive']} run_id={report['candidate_run_id']}")
    print(f"report={path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
