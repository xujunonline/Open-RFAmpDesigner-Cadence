from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory
from orfadc.agents.journal import inspect_journal
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.agents.recover_pending_remote import _check_target_path, _publish_without_replacing, _sha256
from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.audit_failed_active_diagnostic import (
    FAILURE_ARTIFACTS, FAILURE_RECOVERY_MODE, FAILURE_SOURCE_FILES,
    audit_failed_active_diagnostic, terminal_spectre_error_count,
)
from orfadc.experiments.run_active_diagnostic_candidate import (
    _PRIVATE_ROOT, _read_ade_companion, _require_private_path, render_active_diagnostic_netlist,
)
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _failure_file_hashes(runner: RemoteRunner, remote_dir: str) -> dict[str, str] | None:
    result = runner.run_remote(
        ["sha256sum", "--", *FAILURE_SOURCE_FILES], cwd=remote_dir, timeout_seconds=30,
    )
    if not result.ok or len(result.stdout) > 2048:
        return None
    lines = result.stdout.splitlines()
    if len(lines) != len(FAILURE_SOURCE_FILES):
        return None
    hashes = {}
    for name, line in zip(FAILURE_SOURCE_FILES, lines, strict=True):
        digest, separator, recorded_name = line.partition("  ")
        if separator != "  " or recorded_name != name or not _SHA256.fullmatch(digest):
            return None
        hashes[name] = digest
    return hashes


def snapshot_remote_failure_artifacts(
    runner: RemoteRunner, remote_dir: str, *, wait_seconds: float = 3.0,
) -> dict:
    """Observe a terminal-failure candidate twice; hashes do not certify log meaning."""
    if type(wait_seconds) not in {int, float} or not math.isfinite(wait_seconds) or not 1 <= wait_seconds <= 10:
        raise ValueError("failure observation interval must be 1..10 seconds")
    first = probe_remote_diagnostic_directory(runner, remote_dir)
    if first.get("state") != "observed" or first.get("directory") != "present":
        return {"status": "remote_unknown", "safe_to_adopt": False}
    if first["spectre_active"]:
        return {"status": "spectre_in_flight", "safe_to_adopt": False}
    before = _failure_file_hashes(runner, remote_dir)
    if before is None:
        return {"status": "failure_artifacts_unavailable", "safe_to_adopt": False}
    time.sleep(float(wait_seconds))
    second = probe_remote_diagnostic_directory(runner, remote_dir)
    if second.get("state") != "observed" or second.get("directory") != "present":
        return {"status": "remote_unknown", "safe_to_adopt": False}
    if second["spectre_active"]:
        return {"status": "spectre_in_flight", "safe_to_adopt": False}
    after = _failure_file_hashes(runner, remote_dir)
    if after is None or before != after:
        return {"status": "failure_artifacts_changed", "safe_to_adopt": False}
    return {"status": "stable_unverified_failure", "artifacts_sha256": after, "safe_to_adopt": False}


def recover_pending_diagnostic_failure(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner, *,
    template: Path, template_sha256: str,
) -> tuple[Path, dict]:
    """Recover one evidenced terminal Spectre failure; never execute or retry the netlist."""
    for path in (trace_dir, runs_root, template):
        _require_private_path(path)
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise ValueError("candidate runs root is missing or unsafe")
    with agent_run_lock(trace_dir):
        from orfadc.agents.quarantine_pending import require_not_quarantined
        require_not_quarantined(trace_dir)
        audit = inspect_journal(trace_dir)
        if (
            audit.disposition != "reconcile_pending_evaluation"
            or not audit.spec_verified or not audit.candidate_snapshots_verified
            or not audit.remote_identity_verified
            or audit.pending_candidate_id is None or audit.pending_run_id is None
            or audit.searches_used != 1 or audit.evaluations_used != 1
            or (trace_dir / "agent_trace.json").exists()
        ):
            raise ValueError("trace is not a bound planned pending diagnostic")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        start = events[0]
        if (start.get("dispatch_mode") != "planned"
                or start["max_searches"] != 1 or start["max_evaluations"] != 1):
            raise ValueError("pending failure recovery requires one planned dispatch")
        identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        if identity != remote_identity(runner.config):
            raise ValueError("current SSH config differs from the planned dispatch")
        spec = read_spec_snapshot(trace_dir, start["spec_sha256"])
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 1 or len(snapshots[0]["candidates"]) != 1:
            raise ValueError("pending failure recovery needs one candidate snapshot")
        candidate = Candidate(**snapshots[0]["candidates"][0])
        if (
            spec.id != audit.spec_id or candidate.candidate_id != audit.pending_candidate_id
            or candidate.spec_id != spec.id or candidate.seed != audit.seed
            or candidate.status != "active_common_source_diagnostic"
            or candidate.power_ratio_list != [] or candidate.passive_params
            or candidate.sim_result is not None
        ):
            raise ValueError("pending failure candidate is not the bounded OA diagnostic")
        netlist = render_active_diagnostic_netlist(candidate, template, template_sha256)
        companion = _read_ade_companion(template, netlist)
        if companion is None:
            raise ValueError("failure recovery requires the OA ADE companion")
        remote_name = f"rf_active_{spec.id}_seed{audit.seed}_{candidate.candidate_id}_{audit.pending_run_id}"
        remote_dir = str(PurePosixPath(runner.config.remote_root) / remote_name)
        link_check = runner.run_remote([
            "bash", "-c",
            'for item in "$@"; do [ -f "$item" ] && [ ! -L "$item" ] || exit 7; done',
            "--", *FAILURE_SOURCE_FILES,
        ], cwd=remote_dir, timeout_seconds=30)
        if not link_check.ok:
            raise ValueError("remote failure source is missing, symlinked, or unreachable")
        before = snapshot_remote_failure_artifacts(runner, remote_dir)
        if before["status"] != "stable_unverified_failure":
            raise ValueError("remote failure source is active, unavailable, or changing")
        cursor = runs_root
        for part in (spec.id, f"seed{audit.seed}", candidate.candidate_id, audit.pending_run_id):
            if not _ID.fullmatch(part):
                raise ValueError("pending failure archive path has an unsafe identifier")
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("pending failure archive path is symlinked")
        run_dir = cursor
        if not run_dir.exists():
            run_dir = reserve_candidate_run(runs_root, spec, candidate, run_id=audit.pending_run_id)
        if not run_dir.is_dir() or not run_dir.resolve().is_relative_to(runs_root.resolve()):
            raise ValueError("pending failure archive path is unsafe")
        if (run_dir / "evidence_manifest.json").exists():
            raise ValueError("pending failure archive already has an evidence manifest")
        stage = run_dir / ("remote_failure_staging_" + uuid4().hex[:8]) / run_dir.name
        stage.mkdir(parents=True, exist_ok=False)
        hashes = before["artifacts_sha256"]
        for name in FAILURE_SOURCE_FILES:
            destination = stage / name
            result = runner.download(str(PurePosixPath(remote_dir) / name), destination)
            if not result.ok or _sha256(destination) != hashes[name]:
                raise ValueError("remote failure download differs from the first remote hash")
        after = snapshot_remote_failure_artifacts(runner, remote_dir)
        if after["status"] != "stable_unverified_failure" or after["artifacts_sha256"] != hashes:
            raise ValueError("remote failure source changed during download")
        if (stage / "netlist.scs").read_bytes() != netlist.encode("utf-8"):
            raise ValueError("failed Spectre netlist differs from the planned candidate")
        if (stage / "ade_e.scs").read_bytes() != companion:
            raise ValueError("failed Spectre companion differs from the OA source")
        error_count = terminal_spectre_error_count((stage / "spectre.log").read_bytes())
        existing_candidate = run_dir / "candidate.json"
        if existing_candidate.exists() or existing_candidate.is_symlink():
            if existing_candidate.is_symlink() or json.loads(existing_candidate.read_text(
                encoding="utf-8"
            )) != candidate.to_dict():
                raise ValueError("existing candidate snapshot differs from the pending journal")
            shutil.copyfile(existing_candidate, stage / "candidate.json")
        else:
            write_json(stage / "candidate.json", candidate.to_dict())
        provenance = {
            "schema_version": 1, "mode": FAILURE_RECOVERY_MODE,
            "trace_id": trace_dir.name, "spec_id": spec.id, "seed": candidate.seed,
            "candidate_id": candidate.candidate_id, "run_id": run_dir.name,
            "remote_identity_sha256": start["remote_identity_sha256"],
            "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
            "remote_artifacts_sha256": hashes, "terminal_error_count": error_count,
            "controller_stdout_stderr_captured": False,
            "spectre_dispatched_by_recovery": False,
        }
        write_json(stage / "recovery_provenance.json", provenance)
        payload = {
            "schema_version": 1, "status": "spectre_failed", "simulation_status": "failed",
            "circuit_class": "active_common_source_smoke", "not_lna_result": True,
            "spec_pass": None, "failure_code": "spectre_error", "analysis": [],
            "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
            "timeout_seconds": runner.config.command_timeout_seconds, "run_id": run_dir.name,
            "template_sha256": template_sha256, "source_template_sha256": template_sha256,
            "recovery_mode": FAILURE_RECOVERY_MODE,
            "controller_stdout_stderr_captured": False,
            "terminal_error_count": error_count,
            "recovery_provenance_sha256": _sha256(stage / "recovery_provenance.json"),
        }
        validate_metrics_payload(payload)
        write_json(stage / "metrics.json", payload)
        write_evidence_manifest(stage, FAILURE_ARTIFACTS)
        if audit_failed_active_diagnostic(stage, template=template, template_sha256=template_sha256) != payload:
            raise ValueError("staged failure differs from its raw evidence")
        for name in [*FAILURE_ARTIFACTS.values(), "evidence_manifest.json"]:
            target = run_dir / name
            _check_target_path(run_dir, target)
            if target.is_symlink() or (target.exists() and (
                not target.is_file() or _sha256(target) != _sha256(stage / name)
            )):
                raise ValueError("existing failure recovery target differs from staged archive")
        for name in [*FAILURE_ARTIFACTS.values(), "evidence_manifest.json"]:
            _publish_without_replacing(stage / name, run_dir / name, _sha256(stage / name))
        if audit_failed_active_diagnostic(run_dir, template=template, template_sha256=template_sha256) != payload:
            raise ValueError("published failure differs from the staged archive")
        return run_dir, {
            "status": "recovered_terminal_failure_audited", "candidate_run_id": run_dir.name,
            "trace_id": trace_dir.name, "terminal_error_count": error_count,
            "spectre_dispatched_by_recovery": False,
            "not_lna_result": True, "spec_pass": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover one quiescent terminal failed OA diagnostic")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    try:
        archive, report = recover_pending_diagnostic_failure(
            args.trace_dir, args.runs_root, RemoteRunner(load_remote_config(args.config)),
            template=args.template, template_sha256=args.template_sha256,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"terminal failure recovery rejected: {type(exc).__name__}")
    print(f"status={report['status']} run_id={archive.name} errors={report['terminal_error_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
