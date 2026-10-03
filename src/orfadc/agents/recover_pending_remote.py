from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.agents.inspect_pending_remote import snapshot_remote_diagnostic_artifacts
from orfadc.agents.journal import inspect_journal
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.reconcile_pending_feedback import (
    _audit_source, _check_recovery_provenance, _source_dir,
)
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.audit_active_diagnostic_candidate import (
    _RECOVERY_FILES, _RECOVERY_MODE, audit_active_diagnostic_candidate,
)
from orfadc.experiments.extract_active_oa import extract_active_oa, write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import (
    _PRIVATE_ROOT, _SUPPLY_LINE, _read_ade_companion, _require_private_path,
    render_active_diagnostic_netlist,
)
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate


_CLEAN_LOG = re.compile(rb"spectre completes with 0 errors,\s*\d+ warnings")
_EVIDENCE_ARTIFACTS = {
    "metrics": "metrics.json", "candidate": "candidate.json",
    "netlist": "netlist.scs", "ade_companion": "ade_e.scs",
    "spectre_log": "spectre.log", "waveforms": "waveforms.csv",
    "dc_raw": "psf/dcOp.dc", "sp_raw": "psf/sp.sp",
    "noise_raw": "psf/sp.noise.sp", "recovery_provenance": "recovery_provenance.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _publish_without_replacing(source: Path, target: Path, expected_sha256: str) -> None:
    if target.is_symlink():
        raise ValueError("recovery target is symlinked")
    if target.exists():
        if not target.is_file() or _sha256(target) != expected_sha256:
            raise ValueError("existing recovery target differs from the remote snapshot")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink():
        raise ValueError("recovery target parent is symlinked")
    with source.open("r+b") as input_stream:
        os.fsync(input_stream.fileno())
    if sys.platform == "win32":
        os.rename(source, target)
    else:
        os.link(source, target)
    if _sha256(target) != expected_sha256:
        raise ValueError("copied recovery target differs from the remote snapshot")


def _check_target_path(run_dir: Path, target: Path) -> None:
    cursor = target
    while cursor != run_dir:
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("recovery target path is linked")
        if cursor != target and cursor.exists() and not cursor.is_dir():
            raise ValueError("recovery target parent is not a directory")
        cursor = cursor.parent


def recover_pending_diagnostic_remote(
    trace_dir: Path, runs_root: Path, runner: RemoteRunner, *,
    template: Path, template_sha256: str, feedback_second: bool = False,
) -> tuple[Path, dict]:
    """Download one quiescent planned OA diagnostic; never run Spectre or reconcile it."""
    _require_private_path(trace_dir)
    _require_private_path(runs_root)
    _require_private_path(template)
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise ValueError("candidate runs root is missing or unsafe")
    with agent_run_lock(trace_dir):
        from orfadc.agents.quarantine_pending import require_not_quarantined
        require_not_quarantined(trace_dir)
        audit = inspect_journal(
            trace_dir, candidate_runs_root=runs_root if feedback_second else None,
        )
        if (
            audit.disposition != "reconcile_pending_evaluation"
            or not audit.spec_verified or not audit.candidate_snapshots_verified
            or not audit.remote_identity_verified
            or audit.pending_candidate_id is None or audit.pending_run_id is None
            or audit.searches_used != (2 if feedback_second else 1)
            or audit.evaluations_used != (2 if feedback_second else 1)
            or (feedback_second and not audit.candidate_bindings_verified)
            or (trace_dir / "agent_trace.json").exists()
        ):
            raise ValueError("agent trace is not a bound planned pending diagnostic")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        start = events[0]
        budget = 2 if feedback_second else 1
        if (start.get("dispatch_mode") != "planned"
                or start["max_searches"] != budget or start["max_evaluations"] != budget):
            raise ValueError("pending recovery has an incompatible planned dispatch budget")
        bound = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
        if bound != remote_identity(runner.config):
            raise ValueError("current SSH config differs from the planned dispatch")
        spec = read_spec_snapshot(trace_dir, start["spec_sha256"])
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != budget or any(len(item["candidates"]) != 1 for item in snapshots):
            raise ValueError("pending recovery has an incompatible candidate snapshot count")
        candidate = Candidate(**snapshots[-1]["candidates"][0])
        if (
            spec.id != audit.spec_id or candidate.candidate_id != audit.pending_candidate_id
            or candidate.spec_id != spec.id or candidate.seed != audit.seed
            or candidate.status != "active_common_source_diagnostic"
            or candidate.power_ratio_list != [] or candidate.passive_params
            or candidate.sim_result is not None
        ):
            raise ValueError("pending candidate is not the bounded OA diagnostic")
        if feedback_second:
            if (
                [event["action"] for event in events] != [
                    "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
                    "SearchCandidates", "EvaluateCandidate",
                ]
                or events[3]["status"] != "diagnostic_refinement_proposed"
                or candidate.candidate_id != f"{spec.id}_seed{audit.seed}_oa_feedback1"
                or candidate.notes != []
            ):
                raise ValueError("pending remote feedback lacks a verified first-round schedule")
            first = Candidate(**snapshots[0]["candidates"][0])
            if (
                first.candidate_id != f"{spec.id}_seed{audit.seed}_oa_feedback0"
                or first.status != "active_common_source_diagnostic" or first.notes != []
                or events[2]["candidate_id"] != first.candidate_id
                or events[3]["candidate_id"] != first.candidate_id
                or events[3]["run_id"] != events[2]["run_id"]
                or events[5]["candidate_id"] != candidate.candidate_id
                or events[5]["run_id"] != audit.pending_run_id
            ):
                raise ValueError("pending remote feedback first-round context differs")
            first_dir = _source_dir(runs_root, spec, first, events[2]["run_id"])
            first_evidence, digest = _audit_source(
                first_dir, spec, first, template=template, template_sha256=template_sha256,
            )
            _check_recovery_provenance(
                first_dir, first_evidence, trace_dir, bound,
                start["remote_identity_sha256"], first,
            )
            first_gain = first_evidence["metrics"].get("s21_db")
            if (
                events[3]["evidence_manifest_sha256"] != digest
                or type(first_gain) not in {int, float} or not math.isfinite(first_gain)
                or first_gain >= spec.gain_db
                or candidate.active_params["rd_ohm"] != round(first.active_params["rd_ohm"] * 1.1, 9)
                or candidate.active_params["vbias_v"] != first.active_params["vbias_v"]
            ):
                raise ValueError("pending remote feedback lacks a justified second candidate")
        netlist = render_active_diagnostic_netlist(candidate, template, template_sha256)
        companion = _read_ade_companion(template, netlist)
        if companion is None:
            raise ValueError("this recovery protocol requires the OA ADE companion")
        supply = _SUPPLY_LINE.findall(netlist)
        if len(supply) != 1 or not math.isfinite(float(supply[0])):
            raise ValueError("OA diagnostic supply is ambiguous")
        remote_name = (
            f"rf_active_{spec.id}_seed{audit.seed}_{candidate.candidate_id}_{audit.pending_run_id}"
        )
        remote_dir = str(PurePosixPath(runner.config.remote_root) / remote_name)
        link_check = runner.run_remote([
            "bash", "-c",
            'for item in "$@"; do [ -f "$item" ] && [ ! -L "$item" ] || exit 7; done; [ ! -L psf ]',
            "--", *_RECOVERY_FILES,
        ], cwd=remote_dir, timeout_seconds=30)
        if not link_check.ok:
            raise ValueError("remote recovery source is missing, symlinked, or unreachable")
        before = snapshot_remote_diagnostic_artifacts(runner, remote_dir)
        if before["status"] != "stable_unverified":
            raise ValueError("remote diagnostic is active, incomplete, or changing")
        marker = runner.run_remote([
            "grep", "-Eq", r"spectre completes with 0 errors,[[:space:]]*[0-9]+ warnings", "spectre.log",
        ], cwd=remote_dir, timeout_seconds=30)
        if not marker.ok:
            raise ValueError("remote Spectre completion marker is absent")
        root = runs_root.resolve()
        cursor = runs_root
        for part in (spec.id, f"seed{audit.seed}", candidate.candidate_id, audit.pending_run_id):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", part):
                raise ValueError("pending archive path has an unsafe identifier")
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("pending archive path is symlinked")
        run_dir = cursor
        if not run_dir.exists():
            run_dir = reserve_candidate_run(runs_root, spec, candidate, run_id=audit.pending_run_id)
        if not run_dir.is_dir() or not run_dir.resolve().is_relative_to(root):
            raise ValueError("pending archive path is unsafe")
        if (run_dir / "evidence_manifest.json").exists():
            raise ValueError("pending archive already has an evidence manifest")
        stage = run_dir / ("remote_recovery_staging_" + uuid4().hex[:8]) / run_dir.name
        stage.mkdir(parents=True, exist_ok=False)
        hashes = before["artifacts_sha256"]
        for name in _RECOVERY_FILES:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = runner.download(str(PurePosixPath(remote_dir) / name), destination)
            if not result.ok or _sha256(destination) != hashes[name]:
                raise ValueError("remote recovery download differs from the first remote hash")
        after = snapshot_remote_diagnostic_artifacts(runner, remote_dir)
        if after["status"] != "stable_unverified" or after["artifacts_sha256"] != hashes:
            raise ValueError("remote diagnostic changed during download")
        if (stage / "netlist.scs").read_bytes() != netlist.encode("utf-8"):
            raise ValueError("downloaded OA netlist differs from the planned candidate")
        if (stage / "ade_e.scs").read_bytes() != companion:
            raise ValueError("downloaded OA companion differs from the source template")
        log = (stage / "spectre.log").read_bytes()
        if not _CLEAN_LOG.search(log) or b"SPECTRE-25" in log:
            raise ValueError("downloaded Spectre log lacks clean completion")
        if any((run_dir / name).exists() or (run_dir / name).is_symlink() for name in (
            "spectre.stdout.log", "spectre.stderr.log",
        )):
            raise ValueError("pending archive contains control-process logs")
        existing_candidate = run_dir / "candidate.json"
        candidate_path = stage / "candidate.json"
        if existing_candidate.exists() or existing_candidate.is_symlink():
            if existing_candidate.is_symlink() or json.loads(existing_candidate.read_text(
                encoding="utf-8"
            )) != candidate.to_dict():
                raise ValueError("existing candidate snapshot differs from the pending journal")
            shutil.copyfile(existing_candidate, candidate_path)
        else:
            write_json(candidate_path, candidate.to_dict())
        provenance = {
            "schema_version": 1, "mode": _RECOVERY_MODE,
            "trace_id": trace_dir.name, "spec_id": spec.id, "seed": candidate.seed,
            "candidate_id": candidate.candidate_id, "run_id": run_dir.name,
            "remote_identity_sha256": start["remote_identity_sha256"],
            "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
            "remote_artifacts_sha256": hashes,
            "controller_stdout_stderr_captured": False,
            "spectre_dispatched_by_recovery": False,
        }
        provenance_path = stage / "recovery_provenance.json"
        write_json(provenance_path, provenance)
        rows, payload = extract_active_oa(
            stage / "psf", run_id=run_dir.name, supply_voltage_v=float(supply[0]),
            source_run_kind="oa_netlist_derivative_bias_load_direct_spectre",
        )
        payload.update({
            "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
            "timeout_seconds": runner.config.command_timeout_seconds,
            "template_sha256": template_sha256, "source_template_sha256": template_sha256,
            "failure_code": None, "recovery_mode": _RECOVERY_MODE,
            "controller_stdout_stderr_captured": False,
            "recovery_provenance_sha256": _sha256(provenance_path),
        })
        validate_metrics_payload(payload)
        write_active_oa_results(stage, rows, payload)
        write_evidence_manifest(stage, _EVIDENCE_ARTIFACTS)
        staged_audit = audit_active_diagnostic_candidate(
            stage, template=template, template_sha256=template_sha256,
        )
        if staged_audit != payload:
            raise ValueError("recovered active diagnostic differs from the raw audit")
        to_publish = [*_EVIDENCE_ARTIFACTS.values(), "evidence_manifest.json"]
        for name in to_publish:
            existing = run_dir / name
            _check_target_path(run_dir, existing)
            if existing.is_symlink() or (existing.exists() and (
                not existing.is_file() or _sha256(existing) != _sha256(stage / name)
            )):
                raise ValueError("existing recovery target differs from the staged archive")
        for name in to_publish:
            _publish_without_replacing(stage / name, run_dir / name, _sha256(stage / name))
        audited = audit_active_diagnostic_candidate(
            run_dir, template=template, template_sha256=template_sha256,
        )
        if audited != staged_audit:
            raise ValueError("published active diagnostic differs from the staged audit")
        return run_dir, {
            "status": "recovered_raw_audited", "candidate_run_id": run_dir.name,
            "trace_id": trace_dir.name, "points": audited["points"],
            "spectre_dispatched_by_recovery": False,
            "controller_stdout_stderr_captured": False,
            "not_lna_result": True, "spec_pass": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover a quiescent planned OA diagnostic without rerunning Spectre")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--feedback-second", action="store_true")
    args = parser.parse_args()
    try:
        runner = RemoteRunner(load_remote_config(args.config))
        run_dir, report = recover_pending_diagnostic_remote(
            args.trace_dir, args.runs_root, runner,
            template=args.template, template_sha256=args.template_sha256,
            feedback_second=args.feedback_second,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"remote recovery rejected: {type(exc).__name__}")
    print(f"status={report['status']} run_id={run_dir.name} points={report['points']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
