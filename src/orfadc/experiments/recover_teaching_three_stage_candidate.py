from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory
from orfadc.agents.recover_pending_remote import _publish_without_replacing, _sha256
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.run_lock import agent_run_lock
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage import (
    _ARTIFACTS, audit_teaching_three_stage, extract_teaching_three_stage,
)
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.schemas import Candidate, Spec


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REMOTE_FILES = {
    "teaching_three_stage_probe.scs": "remote_teaching_three_stage_probe.scs",
    "teaching_mos1_model.scs": "remote_teaching_mos1_model.scs",
    "spectre.log": "spectre.log", "psf/dcOp.dc": "dcOp.dc",
    "psf/dcOpInfo.info": "dcOpInfo.info", "psf/sp.sp": "sp.sp",
    "psf/sp.noise.sp": "sp.noise.sp",
    "teaching_three_stage_probe.s2p": "teaching_three_stage_probe.s2p",
}
_RECOVERED_ARTIFACTS = {
    **{key: value for key, value in _ARTIFACTS.items() if key not in {"stdout", "stderr"}},
    "candidate": "candidate.json", "dispatch_plan": "dispatch_plan.json",
    "remote_identity": "agent_remote.json", "recovery_provenance": "recovery_provenance.json",
}


def _validate_pending(run_dir: Path, runner: RemoteRunner) -> tuple[dict, Candidate, Spec]:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink() or not _ID.fullmatch(run_dir.name):
        raise ValueError("three-stage pending archive path is unsafe")
    root = run_dir.parents[3]
    _require_private_path(root)
    cursor = root
    for part in run_dir.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("three-stage pending archive path is linked")
    plan = json.loads((run_dir / "dispatch_plan.json").read_text(encoding="utf-8"))
    candidate = Candidate(**plan["candidate"])
    spec = Spec(**plan["spec"])
    if (
        candidate.to_dict() != plan["candidate"] or asdict(spec) != plan["spec"]
        or run_dir.relative_to(root).parts != (
            spec.id, f"seed{candidate.seed}", candidate.candidate_id, run_dir.name,
        )
        or candidate.status != "teaching_three_stage_diagnostic"
        or candidate.spec_id != spec.id or candidate.seed < 0
        or candidate.active_params or candidate.power_ratio_list or candidate.notes
        or candidate.sim_result is not None
        or set(candidate.passive_params) != {"output_tune_ff", "output_secondary_nh"}
        or spec.id != "S1" or spec.band_edges_ghz[0] < 8 or spec.band_edges_ghz[1] > 12
        or type(plan.get("host_available_gib_before")) not in {int, float}
        or plan["host_available_gib_before"] < 2.66
    ):
        raise ValueError("three-stage pending candidate context is invalid")
    identity = read_remote_identity_snapshot(run_dir, plan["remote_identity_sha256"])
    if identity != remote_identity(runner.config):
        raise ValueError("three-stage pending remote identity differs from the current config")
    remote_name = f"teach3_{spec.id}_seed{candidate.seed}_{candidate.candidate_id}_{run_dir.name}"
    expected = {
        "schema_version": 1, "run_id": run_dir.name,
        "remote_dir": str(PurePosixPath(identity["remote_root"]) / remote_name),
        "remote_identity_sha256": plan["remote_identity_sha256"],
        "netlist_sha256": _sha256(run_dir / "netlist.scs"),
        "model_sha256": _sha256(run_dir / "teaching_mos1_model.scs"),
        "candidate": candidate.to_dict(), "spec": asdict(spec),
        "host_available_gib_before": plan["host_available_gib_before"],
        "spectre_timeout_seconds": 180, "spectre_dispatched_by_recovery": False,
    }
    if (
        plan != expected
        or json.loads((run_dir / "candidate.json").read_text(encoding="utf-8")) != candidate.to_dict()
        or (run_dir / "netlist.scs").read_bytes() != render_teaching_three_stage(
            output_tune_ff=candidate.passive_params["output_tune_ff"],
            output_secondary_nh=candidate.passive_params["output_secondary_nh"],
        )
        or (run_dir / "teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()
    ):
        raise ValueError("three-stage pending plan differs from its original local inputs")
    marker = json.loads((run_dir / "dispatch_uncertain.json").read_text(encoding="utf-8"))
    if (
        marker.get("status") != "unverified_remote_dispatch"
        or marker.get("run_id") != run_dir.name
        or marker.get("safe_to_retry") is not False
        or marker.get("spec_pass") is not None
    ):
        raise ValueError("three-stage archive is not an uncertain dispatched candidate")
    return plan, candidate, spec


def _quiescent_hashes(runner: RemoteRunner, remote_dir: str, *, wait_seconds: float = 3.0) -> dict[str, str]:
    if not 1 <= wait_seconds <= 10:
        raise ValueError("three-stage remote observation interval is invalid")
    snapshots = []
    for index in range(2):
        observed = probe_remote_diagnostic_directory(runner, remote_dir)
        if (
            observed.get("state") != "observed" or observed.get("directory") != "present"
            or observed.get("spectre_active") is not False
        ):
            raise ValueError("three-stage remote job is active, absent, or unobservable")
        link_check = runner.run_remote([
            "bash", "-c",
            'for item in "$@"; do [ -f "$item" ] && [ ! -L "$item" ] || exit 7; done; [ ! -L psf ]',
            "--", *_REMOTE_FILES,
        ], cwd=remote_dir, timeout_seconds=30)
        if not link_check.ok:
            raise ValueError("three-stage remote raw source is incomplete or linked")
        result = runner.run_remote(["sha256sum", "--", *_REMOTE_FILES], cwd=remote_dir, timeout_seconds=30)
        lines = result.stdout.splitlines()
        if not result.ok or len(result.stdout) > 4096 or len(lines) != len(_REMOTE_FILES):
            raise ValueError("three-stage remote raw hashes are unavailable")
        hashes = {}
        for name, line in zip(_REMOTE_FILES, lines, strict=True):
            digest, separator, recorded = line.partition("  ")
            if separator != "  " or recorded != name or not _SHA256.fullmatch(digest):
                raise ValueError("three-stage remote raw hash response is invalid")
            hashes[name] = digest
        snapshots.append(hashes)
        if index == 0:
            time.sleep(wait_seconds)
    if snapshots[0] != snapshots[1]:
        raise ValueError("three-stage remote raw files changed between observations")
    return snapshots[1]


def recover_teaching_three_stage_candidate(run_dir: Path, runner: RemoteRunner) -> dict:
    """Adopt only a clean, stationary original remote run; never dispatch Spectre."""
    _require_private_path(run_dir)
    with agent_run_lock(run_dir):
        plan, candidate, spec = _validate_pending(run_dir, runner)
        if (run_dir / "evidence_manifest.json").exists():
            audited = audit_teaching_three_stage(run_dir)
            if json.loads((run_dir / "probe_status.json").read_text(encoding="utf-8")).get(
                "dispatch_protocol_version"
            ) != 4:
                raise ValueError("three-stage archive was not recovered by this protocol")
            return {**audited, "status": "already_recovered"}
        if any((run_dir / name).exists() for name in ("metrics.json", "probe_status.json")):
            raise ValueError("three-stage pending archive already contains unverified results")
        remote_dir = plan["remote_dir"]
        before = _quiescent_hashes(runner, remote_dir)
        completion = runner.run_remote([
            "grep", "-Eq", r"spectre completes with 0 errors,[[:space:]]*0 warnings", "spectre.log",
        ], cwd=remote_dir, timeout_seconds=30)
        if not completion.ok:
            raise ValueError("three-stage remote run lacks a clean terminal Spectre summary")
        stage = run_dir / ("remote_recovery_staging_" + uuid4().hex[:8]) / run_dir.name
        stage.mkdir(parents=True, exist_ok=False)
        for name in ("netlist.scs", "teaching_mos1_model.scs", "candidate.json",
                     "dispatch_plan.json", "agent_remote.json"):
            shutil.copy2(run_dir / name, stage / name)
        for remote, local in _REMOTE_FILES.items():
            downloaded = runner.download(str(PurePosixPath(remote_dir) / remote), stage / local)
            if not downloaded.ok or _sha256(stage / local) != before[remote]:
                raise ValueError("three-stage recovered file differs from the first remote snapshot")
        after = _quiescent_hashes(runner, remote_dir)
        if before != after:
            raise ValueError("three-stage remote raw source changed during recovery")
        if (
            (stage / "remote_teaching_three_stage_probe.scs").read_bytes()
            != (stage / "netlist.scs").read_bytes()
            or (stage / "remote_teaching_mos1_model.scs").read_bytes()
            != (stage / "teaching_mos1_model.scs").read_bytes()
        ):
            raise ValueError("three-stage recovered remote inputs differ from planned inputs")
        write_json(stage / "probe_status.json", {
            "status": "raw_probe_only", "spectre_returncode": None,
            "raw_completion_verified": True, "spectre_log_downloaded": True,
            "host_available_gib_before": plan["host_available_gib_before"],
            "output_tune_ff": candidate.passive_params["output_tune_ff"],
            "output_secondary_nh": candidate.passive_params["output_secondary_nh"],
            "candidate": candidate.to_dict(), "spec": asdict(spec), "seed": candidate.seed,
            "timeout_seconds": 180, "dispatch_protocol_version": 4,
            "recovery_mode": "remote_quiescent_raw",
            "not_lna_result": True, "spec_pass": None,
        })
        write_json(stage / "recovery_provenance.json", {
            "schema_version": 1, "mode": "remote_quiescent_raw", "run_id": run_dir.name,
            "remote_identity_sha256": plan["remote_identity_sha256"],
            "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
            "remote_artifacts_sha256": before,
            "controller_stdout_stderr_captured": False,
            "spectre_dispatched_by_recovery": False,
        })
        rows, payload = extract_teaching_three_stage(stage)
        write_active_oa_results(stage, rows, payload)
        write_evidence_manifest(stage, _RECOVERED_ARTIFACTS)
        audit_teaching_three_stage(stage)
        for name in _RECOVERED_ARTIFACTS.values():
            _publish_without_replacing(stage / name, run_dir / name, _sha256(stage / name))
        _publish_without_replacing(
            stage / "evidence_manifest.json", run_dir / "evidence_manifest.json",
            _sha256(stage / "evidence_manifest.json"),
        )
        audit_teaching_three_stage(run_dir)
        return {"status": "verified_recovered", "run_id": run_dir.name,
                "not_lna_result": True, "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover one bounded public MOS1 three-stage remote raw run")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    args = parser.parse_args()
    try:
        report = recover_teaching_three_stage_candidate(
            args.run_dir, RemoteRunner(load_remote_config(args.config)),
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} run_id={report['run_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
