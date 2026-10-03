from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.agents.journal import inspect_journal
from orfadc.agents.recover_pending_failure import snapshot_remote_failure_artifacts
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.remote_quarantine_fence import (
    FENCE_FILE, fence_bytes, publish_remote_fence, remote_fence_sha256,
)
from orfadc.agents.run_lock import agent_run_lock
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.experiments.audit_failed_active_diagnostic import FAILURE_SOURCE_FILES, _SUMMARY
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Candidate


QUARANTINE_FILE = "agent_pending_quarantine.json"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {
    "schema_version", "status", "trace_id", "spec_id", "seed", "candidate_id", "run_id",
    "journal_sha256", "candidate_snapshots_sha256", "pending_index_sha256", "control_attempt_sha256",
    "candidate_file_sha256",
    "remote_identity_sha256", "remote_dir_sha256", "remote_artifacts_sha256",
    "remote_probe_before", "remote_probe_after", "remote_hash_snapshots",
    "remote_probe_post_fence", "remote_hash_post_fence",
    "remote_fence_sha256", "remote_fence_publish_status",
    "staging_dir", "observed_at_utc", "evaluations_used", "budget_disposition",
    "safe_to_dispatch", "safe_to_reconcile", "new_run_authorized", "not_lna_result", "spec_pass",
}


def _fence_payload(record: dict) -> dict:
    keys = (
        "trace_id", "spec_id", "seed", "candidate_id", "run_id",
        "journal_sha256", "candidate_snapshots_sha256", "pending_index_sha256",
        "control_attempt_sha256", "candidate_file_sha256", "remote_identity_sha256",
        "remote_dir_sha256", "remote_artifacts_sha256", "evaluations_used",
        "budget_disposition", "safe_to_dispatch", "safe_to_reconcile",
        "new_run_authorized", "not_lna_result", "spec_pass",
    )
    return {"schema_version": 1, "decision": "quarantined_pending_incomplete",
            **{key: record[key] for key in keys}}


def require_not_quarantined(trace_dir: Path) -> None:
    """Fail closed at existing recovery entry points; this protocol has no release action."""
    path = trace_dir / QUARANTINE_FILE
    if path.exists() or path.is_symlink():
        raise ValueError("pending run is quarantined; recovery and reconciliation are disabled")


def _hash(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("quarantine source is missing or unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(trace_dir: Path, runs_root: Path) -> tuple[object, dict, Path, dict]:
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    audit = inspect_journal(trace_dir)
    if (
        audit.disposition != "reconcile_pending_evaluation" or not audit.spec_verified
        or not audit.candidate_snapshots_verified or not audit.remote_identity_verified
        or audit.pending_candidate_id is None or audit.pending_run_id is None
        or audit.searches_used != 1 or audit.evaluations_used != 1
        or any((trace_dir / name).exists() or (trace_dir / name).is_symlink()
               for name in ("agent_trace.json", "agent_reconciliation.json"))
    ):
        raise ValueError("quarantine requires one verified planned pending diagnostic")
    journal_path = trace_dir / "agent_events.jsonl"
    start = json.loads(journal_path.read_bytes().splitlines()[0])
    if (start.get("dispatch_mode") != "planned" or start.get("max_searches") != 1
            or start.get("max_evaluations") != 1):
        raise ValueError("quarantine requires a one-run planned journal")
    snapshots_path = trace_dir / "agent_candidates.jsonl"
    snapshots = [json.loads(line) for line in snapshots_path.read_text(encoding="ascii").splitlines()]
    if len(snapshots) != 1 or len(snapshots[0]["candidates"]) != 1:
        raise ValueError("quarantine requires one candidate snapshot")
    candidate = Candidate(**snapshots[0]["candidates"][0])
    if (
        candidate.candidate_id != audit.pending_candidate_id or candidate.spec_id != audit.spec_id
        or candidate.seed != audit.seed or candidate.status != "active_common_source_diagnostic"
        or candidate.power_ratio_list or candidate.passive_params or candidate.sim_result is not None
    ):
        raise ValueError("quarantine candidate differs from the pending diagnostic")
    parts = (audit.spec_id, f"seed{audit.seed}", candidate.candidate_id, audit.pending_run_id)
    run_dir = runs_root
    for part in parts:
        if not _ID.fullmatch(part):
            raise ValueError("quarantine run identifier is unsafe")
        run_dir = run_dir / part
        if run_dir.is_symlink():
            raise ValueError("quarantine run path is symlinked")
    if not run_dir.is_dir() or not run_dir.resolve().is_relative_to(runs_root.resolve()):
        raise ValueError("quarantine candidate archive is missing or unsafe")
    index_path = trace_dir / "agent_evaluation.json"
    if not index_path.is_file() or index_path.is_symlink():
        raise ValueError("quarantine pending index is missing or unsafe")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if (
        not isinstance(index, dict) or index.get("execution_status") != "pending_remote_evaluation"
        or index.get("spec_id") != audit.spec_id or index.get("seed") != audit.seed
        or index.get("candidate_id") != candidate.candidate_id
        or index.get("candidate_run_id") != audit.pending_run_id
        or index.get("candidate_run_relative") != Path(*parts).as_posix()
        or index.get("not_lna_result") is not True or index.get("spec_pass") is not None
        or any((run_dir / name).exists() or (run_dir / name).is_symlink()
               for name in ("metrics.json", "evidence_manifest.json"))
    ):
        raise ValueError("quarantine pending index or candidate archive is inconsistent")
    saved_candidate = run_dir / "candidate.json"
    if (not saved_candidate.is_file() or saved_candidate.is_symlink()
            or json.loads(saved_candidate.read_text(encoding="utf-8")) != candidate.to_dict()):
        raise ValueError("quarantine local candidate differs from the journal")
    for name in ("netlist.scs", "ade_e.scs"):
        _hash(run_dir / name)
    attempt_path = run_dir / "control_attempt" / "dispatch.json"
    if not attempt_path.is_file() or attempt_path.is_symlink():
        raise ValueError("quarantine requires an uncertain controller dispatch record")
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    if (
        not isinstance(attempt, dict) or attempt.get("run_id") != audit.pending_run_id
        or attempt.get("status") != "uncertain" or attempt.get("returncode") not in {124, 255}
    ):
        raise ValueError("quarantine controller dispatch record is not uncertain")
    return audit, start, run_dir, index


def audit_pending_quarantine(trace_dir: Path, runs_root: Path = _PRIVATE_ROOT) -> dict:
    """Recheck the local frozen record without contacting or modifying the remote host."""
    audit, start, run_dir, _ = _context(trace_dir, runs_root)
    report_path = trace_dir / QUARANTINE_FILE
    if not report_path.is_file() or report_path.is_symlink() or report_path.stat().st_size > 4096:
        raise ValueError("quarantine record is missing or unsafe")
    raw = report_path.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or set(report) != _FIELDS:
        raise ValueError("quarantine record fields differ")
    expected = {
        "schema_version": 2, "status": "quarantined_pending_incomplete",
        "trace_id": trace_dir.name, "spec_id": audit.spec_id, "seed": audit.seed,
        "candidate_id": audit.pending_candidate_id, "run_id": audit.pending_run_id,
        "journal_sha256": _hash(trace_dir / "agent_events.jsonl"),
        "candidate_snapshots_sha256": _hash(trace_dir / "agent_candidates.jsonl"),
        "pending_index_sha256": _hash(trace_dir / "agent_evaluation.json"),
        "control_attempt_sha256": _hash(run_dir / "control_attempt" / "dispatch.json"),
        "candidate_file_sha256": _hash(run_dir / "candidate.json"),
        "remote_identity_sha256": start["remote_identity_sha256"],
        "evaluations_used": 1, "budget_disposition": "dispatched_outcome_unknown",
        "safe_to_dispatch": False, "safe_to_reconcile": False,
        "new_run_authorized": False, "not_lna_result": True, "spec_pass": None,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("quarantine record differs from its pending source")
    if (
        not isinstance(report["remote_dir_sha256"], str)
        or not _SHA256.fullmatch(report["remote_dir_sha256"])
        or not isinstance(report["observed_at_utc"], str)
        or not isinstance(report["staging_dir"], str)
        or not re.fullmatch(r"quarantine_staging_[0-9a-f]{8}", report["staging_dir"])
        or not isinstance(report["remote_artifacts_sha256"], dict)
        or set(report["remote_artifacts_sha256"]) != set(FAILURE_SOURCE_FILES)
        or any(not isinstance(digest, str) or not _SHA256.fullmatch(digest)
               for digest in report["remote_artifacts_sha256"].values())
    ):
        raise ValueError("quarantine remote snapshot metadata is malformed")
    expected_probe = {
        "state": "observed", "directory": "present", "spectre_active": False,
        "spectre_log_present": True, "sp_raw_present": False, "noise_raw_present": False,
    }
    expected_hash_snapshot = {
        "status": "stable_unverified",
        "artifacts_sha256": report["remote_artifacts_sha256"], "safe_to_adopt": False,
    }
    if (report["remote_probe_before"] != expected_probe
            or report["remote_probe_after"] != expected_probe
            or report["remote_probe_post_fence"] != expected_probe
            or report["remote_hash_snapshots"] != [
                expected_hash_snapshot, expected_hash_snapshot,
            ] or report["remote_hash_post_fence"] != expected_hash_snapshot):
        raise ValueError("quarantine observations do not support an incomplete remote run")
    fence_raw = fence_bytes(_fence_payload(report))
    if (report["remote_fence_publish_status"] not in {"created", "existing_same"}
            or report["remote_fence_sha256"] != hashlib.sha256(fence_raw).hexdigest()):
        raise ValueError("quarantine remote fence differs from its pending decision")
    try:
        datetime.fromisoformat(report["observed_at_utc"])
    except ValueError as exc:
        raise ValueError("quarantine timestamp is malformed") from exc
    identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    remote_dir = str(PurePosixPath(identity["remote_root"]) /
                     f"rf_active_{audit.spec_id}_seed{audit.seed}_{audit.pending_candidate_id}_{audit.pending_run_id}")
    if report["remote_dir_sha256"] != hashlib.sha256(remote_dir.encode("utf-8")).hexdigest():
        raise ValueError("quarantine remote directory differs from planned identity")
    stage_root = run_dir / report["staging_dir"]
    stage = stage_root / audit.pending_run_id
    if (stage_root.is_symlink() or stage.is_symlink() or not stage.is_dir()
            or not stage.resolve().is_relative_to(run_dir.resolve())):
        raise ValueError("quarantine staging archive is missing or unsafe")
    for name in FAILURE_SOURCE_FILES:
        if _hash(stage / name) != report["remote_artifacts_sha256"][name]:
            raise ValueError("quarantine staged source differs from observed remote hashes")
    fence_stage = stage / FENCE_FILE
    if _hash(fence_stage) != report["remote_fence_sha256"] or fence_stage.read_bytes() != fence_raw:
        raise ValueError("quarantine staged remote fence differs from its decision")
    for name in ("netlist.scs", "ade_e.scs"):
        if _hash(run_dir / name) != report["remote_artifacts_sha256"][name]:
            raise ValueError("quarantine source differs from the planned local input")
    log = (stage / "spectre.log").read_bytes()
    if not log or len(log) > 16 * 1024 * 1024 or _SUMMARY.findall(log):
        raise ValueError("quarantine requires a nonterminal incomplete Spectre log")
    return report


def verify_remote_pending_quarantine(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner,
) -> dict:
    """Recheck only the remote fence, not current Spectre activity or source stability."""
    report = audit_pending_quarantine(trace_dir, runs_root)
    start = json.loads((trace_dir / "agent_events.jsonl").read_bytes().splitlines()[0])
    identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    if identity != remote_identity(runner.config):
        raise ValueError("quarantine SSH endpoint differs from planned dispatch")
    remote_dir = str(PurePosixPath(identity["remote_root"]) /
                     f"rf_active_{report['spec_id']}_seed{report['seed']}_{report['candidate_id']}_{report['run_id']}")
    if remote_fence_sha256(runner, remote_dir) != report["remote_fence_sha256"]:
        raise ValueError("remote quarantine fence changed or differs from local evidence")
    return report


def _publish_once(path: Path, report: dict) -> None:
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if len(encoded) > 4096:
        raise ValueError("quarantine record is oversized")
    temporary = path.with_name("quarantine_tmp_" + uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _commit_new(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_new(temporary: Path, target: Path) -> None:
    # Windows rename refuses an existing target; POSIX link creates it exclusively.
    # The local lock is host-local; the remote fence serializes the decision separately.
    if os.name == "nt":
        os.rename(temporary, target)
    else:
        os.link(temporary, target)


def quarantine_incomplete_diagnostic(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner,
) -> dict:
    """Freeze one observed incomplete planned run; never dispatch, reconcile, or declare failure."""
    with agent_run_lock(trace_dir):
        report_path = trace_dir / QUARANTINE_FILE
        if report_path.exists() or report_path.is_symlink():
            report = audit_pending_quarantine(trace_dir, runs_root)
            identity = read_remote_identity_snapshot(trace_dir, report["remote_identity_sha256"])
            if identity != remote_identity(runner.config):
                raise ValueError("quarantine SSH endpoint differs from planned dispatch")
            return report
        audit, start, run_dir, _ = _context(trace_dir, runs_root)
        frozen_local = {
            "journal_sha256": trace_dir / "agent_events.jsonl",
            "candidate_snapshots_sha256": trace_dir / "agent_candidates.jsonl",
            "pending_index_sha256": trace_dir / "agent_evaluation.json",
            "control_attempt_sha256": run_dir / "control_attempt" / "dispatch.json",
            "candidate_file_sha256": run_dir / "candidate.json",
            "local_netlist_sha256": run_dir / "netlist.scs",
            "local_ade_sha256": run_dir / "ade_e.scs",
        }
        local_hashes = {key: _hash(path) for key, path in frozen_local.items()}
        identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        if identity != remote_identity(runner.config):
            raise ValueError("quarantine SSH endpoint differs from planned dispatch")
        remote_dir = str(PurePosixPath(runner.config.remote_root) /
                         f"rf_active_{audit.spec_id}_seed{audit.seed}_{audit.pending_candidate_id}_{audit.pending_run_id}")
        from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory

        def require_incomplete() -> dict:
            remote = probe_remote_diagnostic_directory(runner, remote_dir)
            if (
                remote.get("state") != "observed" or remote.get("directory") != "present"
                or remote.get("spectre_active") is not False
                or remote.get("spectre_log_present") is not True
                or remote.get("sp_raw_present") is not False
                or remote.get("noise_raw_present") is not False
            ):
                raise ValueError("remote is unknown, active, complete, or lacks an incomplete log")
            return remote

        probe_before = require_incomplete()
        link_check = runner.run_remote([
            "bash", "-c", 'for item in "$@"; do [ -f "$item" ] && [ ! -L "$item" ] || exit 7; done',
            "--", *FAILURE_SOURCE_FILES,
        ], cwd=remote_dir, timeout_seconds=30)
        if not link_check.ok:
            raise ValueError("remote incomplete source is missing, symlinked, or unreachable")
        before = snapshot_remote_failure_artifacts(runner, remote_dir)
        if before.get("status") != "stable_unverified_failure":
            raise ValueError("remote incomplete source is active, unavailable, or changing")
        stage_name = "quarantine_staging_" + uuid4().hex[:8]
        stage = run_dir / stage_name / audit.pending_run_id
        stage.mkdir(parents=True, exist_ok=False)
        hashes = before["artifacts_sha256"]
        for name in FAILURE_SOURCE_FILES:
            destination = stage / name
            result = runner.download(str(PurePosixPath(remote_dir) / name), destination)
            if not result.ok or _hash(destination) != hashes[name]:
                raise ValueError("quarantine download differs from first remote hash")
        after = snapshot_remote_failure_artifacts(runner, remote_dir)
        probe_after = require_incomplete()
        if after.get("status") != "stable_unverified_failure" or after["artifacts_sha256"] != hashes:
            raise ValueError("remote incomplete source changed during quarantine")
        for name in ("netlist.scs", "ade_e.scs"):
            if _hash(run_dir / name) != hashes[name]:
                raise ValueError("remote incomplete source differs from planned local inputs")
        if any(_hash(path) != local_hashes[key] for key, path in frozen_local.items()):
            raise ValueError("local pending evidence changed during quarantine")
        log = (stage / "spectre.log").read_bytes()
        if not log or len(log) > 16 * 1024 * 1024 or _SUMMARY.findall(log):
            raise ValueError("quarantine cannot classify a terminal Spectre log as incomplete")
        report = {
            "schema_version": 2, "status": "quarantined_pending_incomplete",
            "trace_id": trace_dir.name, "spec_id": audit.spec_id, "seed": audit.seed,
            "candidate_id": audit.pending_candidate_id, "run_id": audit.pending_run_id,
            "journal_sha256": local_hashes["journal_sha256"],
            "candidate_snapshots_sha256": local_hashes["candidate_snapshots_sha256"],
            "pending_index_sha256": local_hashes["pending_index_sha256"],
            "control_attempt_sha256": local_hashes["control_attempt_sha256"],
            "candidate_file_sha256": local_hashes["candidate_file_sha256"],
            "remote_identity_sha256": start["remote_identity_sha256"],
            "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
            "remote_artifacts_sha256": hashes,
            "remote_probe_before": probe_before, "remote_probe_after": probe_after,
            "remote_hash_snapshots": [
                {"status": "stable_unverified", "artifacts_sha256": item["artifacts_sha256"],
                 "safe_to_adopt": False}
                for item in (before, after)
            ],
            "staging_dir": stage_name,
            "observed_at_utc": datetime.now(UTC).isoformat(),
            "evaluations_used": 1, "budget_disposition": "dispatched_outcome_unknown",
            "safe_to_dispatch": False, "safe_to_reconcile": False,
            "new_run_authorized": False, "not_lna_result": True, "spec_pass": None,
        }
        if identity != remote_identity(runner.config):
            raise ValueError("quarantine SSH endpoint changed during observation")
        fence_status, fence_raw = publish_remote_fence(runner, remote_dir, _fence_payload(report))
        if identity != remote_identity(runner.config):
            raise ValueError("quarantine SSH endpoint changed after fence publication")
        fence_destination = stage / FENCE_FILE
        fence_download = runner.download(
            str(PurePosixPath(remote_dir) / FENCE_FILE), fence_destination,
        )
        if not fence_download.ok or _hash(fence_destination) != hashlib.sha256(fence_raw).hexdigest():
            raise ValueError("downloaded remote quarantine fence differs from committed decision")
        post_fence = snapshot_remote_failure_artifacts(runner, remote_dir)
        probe_post_fence = require_incomplete()
        if (post_fence.get("status") != "stable_unverified_failure"
                or post_fence["artifacts_sha256"] != hashes):
            raise ValueError("remote incomplete source changed after fence publication")
        if any(_hash(path) != local_hashes[key] for key, path in frozen_local.items()):
            raise ValueError("local pending evidence changed after fence publication")
        if identity != remote_identity(runner.config):
            raise ValueError("quarantine SSH endpoint changed after fence publication")
        report.update({
            "remote_probe_post_fence": probe_post_fence,
            "remote_hash_post_fence": {
                "status": "stable_unverified", "artifacts_sha256": post_fence["artifacts_sha256"],
                "safe_to_adopt": False,
            },
            "remote_fence_sha256": hashlib.sha256(fence_raw).hexdigest(),
            "remote_fence_publish_status": fence_status,
        })
        _publish_once(report_path, report)
        return audit_pending_quarantine(trace_dir, runs_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine one incomplete planned OA diagnostic")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--verify-remote", action="store_true")
    parser.add_argument("--publish-remote-fence", action="store_true")
    args = parser.parse_args()
    if args.audit_only and args.verify_remote:
        parser.error("--audit-only and --verify-remote are mutually exclusive")
    if args.publish_remote_fence and (args.audit_only or args.verify_remote):
        parser.error("remote fence publication cannot be combined with an audit")
    if not args.audit_only and not args.verify_remote and not args.publish_remote_fence:
        parser.error("quarantine now writes remote metadata; use --publish-remote-fence explicitly")
    if args.audit_only:
        report = audit_pending_quarantine(args.trace_dir, args.runs_root)
    elif args.verify_remote:
        report = verify_remote_pending_quarantine(
            args.trace_dir, args.runs_root, RemoteRunner(load_remote_config(args.config)),
        )
    else:
        report = quarantine_incomplete_diagnostic(
            args.trace_dir, args.runs_root, RemoteRunner(load_remote_config(args.config)),
        )
    print(f"status={report['status']} run_id={report['run_id']} safe_to_dispatch=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
