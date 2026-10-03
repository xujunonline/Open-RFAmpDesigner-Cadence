from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory
from orfadc.agents.journal import inspect_journal
from orfadc.agents.recover_pending_failure import snapshot_remote_failure_artifacts
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.audit_failed_active_diagnostic import (
    FAILURE_SOURCE_FILES, terminal_spectre_error_count,
)
from orfadc.experiments.audit_inflight_lost_reply import _RAW_PROBE
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


def _json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("disconnect evidence is missing or unsafe")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("disconnect evidence must be an object")
    return data


def audit_live_ssh_disconnect(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner,
) -> dict:
    _require_private_path(trace_dir)
    _require_private_path(runs_root)
    if not trace_dir.is_dir() or trace_dir.is_symlink():
        raise ValueError("disconnect trace is missing or unsafe")
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if not (
        journal.disposition == "reconcile_pending_evaluation"
        and journal.spec_verified and journal.candidate_snapshots_verified
        and journal.remote_identity_verified and journal.pending_run_id is not None
        and journal.pending_candidate_id is not None
    ):
        raise ValueError("disconnect trace is not a verified planned pending run")
    events = (trace_dir / "agent_events.jsonl").read_text(encoding="ascii").splitlines()
    start = json.loads(events[0])
    identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    if identity != remote_identity(runner.config):
        raise ValueError("disconnect SSH endpoint differs from the planned dispatch")
    run_id = journal.pending_run_id
    candidate_id = journal.pending_candidate_id
    pending = _json(trace_dir / "agent_evaluation.json")
    live = _json(trace_dir / "live_disconnect_probe.json")
    remote_name = f"rf_active_{journal.spec_id}_seed{journal.seed}_{candidate_id}_{run_id}"
    remote_dir = str(PurePosixPath(runner.config.remote_root) / remote_name)
    if (
        start.get("dispatch_mode") != "planned"
        or pending.get("execution_status") != "pending_remote_evaluation"
        or pending.get("candidate_run_id") != run_id
        or pending.get("not_lna_result") is not True or pending.get("spec_pass") is not None
        or live.get("mode") != "real_spectre_live_observation_then_local_ssh_termination"
        or live.get("trace_id") != trace_dir.name
        or live.get("candidate_run_id") != run_id
        or live.get("remote_dir_sha256") != hashlib.sha256(remote_dir.encode("utf-8")).hexdigest()
        or live.get("spectre_in_flight_observed") is not True
        or live.get("local_ssh_terminated") is not True
        or type(live.get("local_ssh_pid")) is not int or live["local_ssh_pid"] <= 0
        or type(live.get("local_ssh_exitcode")) is not int or live["local_ssh_exitcode"] == 0
        or live.get("spectre_calls") != 1
        or live.get("execution_status") != "pending_remote_evaluation"
        or live.get("spectre_dispatched_by_observer") is not False
        or live.get("not_lna_result") is not True or live.get("spec_pass") is not None
        or (trace_dir / "agent_trace.json").exists()
        or (trace_dir / "agent_reconciliation.json").exists()
    ):
        raise ValueError("disconnect controller evidence differs from the pending journal")
    samples = live.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 100:
        raise ValueError("disconnect lacks bounded live SSH observations")
    active_seen = False
    for sample in samples:
        if not isinstance(sample, dict) or type(sample.get("raw_returncode")) is not int or sample["raw_returncode"] != 0:
            raise ValueError("disconnect live SSH observation did not complete")
        raw = sample.get("raw_stdout")
        match = _RAW_PROBE.fullmatch(raw) if isinstance(raw, str) else None
        if match is None:
            raise ValueError("disconnect raw SSH observation is malformed")
        directory, active, log, sp, noise = match.groups()
        if sample.get("parsed") != {
            "state": "observed", "directory": directory,
            "spectre_active": active == "1", "spectre_log_present": log == "1",
            "sp_raw_present": sp == "1", "noise_raw_present": noise == "1",
        }:
            raise ValueError("disconnect parsed SSH status differs from its raw response")
        active_seen |= directory == "present" and active == "1"
    if not active_seen:
        raise ValueError("disconnect was not preceded by a live Spectre observation")
    run_dir = runs_root / journal.spec_id / f"seed{journal.seed}" / candidate_id / run_id
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("pending candidate run is missing or unsafe")
    attempt = _json(run_dir / "control_attempt" / "dispatch.json")
    if (
        attempt.get("run_id") != run_id or attempt.get("returncode") != 255
        or attempt.get("status") != "uncertain"
        or (run_dir / "metrics.json").exists()
        or (run_dir / "evidence_manifest.json").exists()
    ):
        raise ValueError("disconnect pending candidate was incorrectly finalized")
    remote = probe_remote_diagnostic_directory(runner, remote_dir)
    if not (
        remote.get("state") == "observed" and remote.get("directory") == "present"
        and remote.get("spectre_active") is False
        and remote.get("spectre_log_present") is True
        and remote.get("sp_raw_present") is False
        and remote.get("noise_raw_present") is False
    ):
        raise ValueError("disconnect remote result is not quiescent and incomplete")
    snapshot = snapshot_remote_failure_artifacts(runner, remote_dir)
    if snapshot.get("status") != "stable_unverified_failure" or snapshot.get("safe_to_adopt") is not False:
        raise ValueError("disconnect failure files are active or changing")
    stages = list(run_dir.glob("remote_failure_staging_*"))
    if len(stages) != 1 or stages[0].is_symlink():
        raise ValueError("disconnect lacks one rejected failure-recovery staging archive")
    stage = stages[0] / run_id
    for name in FAILURE_SOURCE_FILES:
        file = stage / name
        if not file.is_file() or file.is_symlink():
            raise ValueError("disconnect staged failure source is missing or unsafe")
        if hashlib.sha256(file.read_bytes()).hexdigest() != snapshot["artifacts_sha256"][name]:
            raise ValueError("disconnect staged failure source differs from remote hashes")
    try:
        terminal_spectre_error_count((stage / "spectre.log").read_bytes())
    except ValueError:
        pass
    else:
        raise ValueError("disconnect failure log has a terminal error summary")
    report = {
        "status": "live_ssh_disconnected_remote_quiescent_incomplete",
        "trace_id": trace_dir.name, "candidate_run_id": run_id,
        "live_samples": len(samples), "remote_artifacts_sha256": snapshot["artifacts_sha256"],
        "spectre_dispatched_by_auditor": False,
        "safe_to_dispatch": False, "safe_to_reconcile": False,
        "not_lna_result": True, "spec_pass": None,
    }
    write_json(trace_dir / "live_disconnect_audit.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a real live SSH disconnect that remains pending")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    args = parser.parse_args()
    result = audit_live_ssh_disconnect(
        args.trace_dir, args.runs_root, RemoteRunner(load_remote_config(args.config)),
    )
    print(f"status={result['status']} safe_to_dispatch={result['safe_to_dispatch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
