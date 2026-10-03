from __future__ import annotations

import argparse
import hashlib
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.agents.remote_identity import write_remote_identity_snapshot
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage import (
    _ARTIFACTS, audit_teaching_three_stage, extract_teaching_three_stage,
)
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Candidate, Spec


def run_teaching_three_stage(
    config_path: Path, output_dir: Path, *, output_tune_ff: float = 0.0,
    output_secondary_nh: float = 1.0,
    broadband: bool = False,
    runner: RemoteRunner | None = None,
    candidate: Candidate | None = None,
    spec: Spec | None = None,
) -> dict:
    _require_private_path(output_dir)
    if (candidate is None) != (spec is None):
        raise ValueError("three-stage candidate and spec must be provided together")
    if candidate is not None and (
        candidate.spec_id != spec.id or candidate.seed < 0
        or candidate.status != "teaching_three_stage_diagnostic"
        or candidate.active_params or candidate.power_ratio_list or candidate.passive_params != {
            "output_tune_ff": output_tune_ff, "output_secondary_nh": output_secondary_nh,
        }
        or candidate.sim_result is not None or candidate.notes
        or spec.id != "S1" or spec.band_edges_ghz[0] < 8 or spec.band_edges_ghz[1] > 12
    ):
        raise ValueError("three-stage candidate context is not the bounded S1 teaching topology")
    netlist = render_teaching_three_stage(
        output_tune_ff=output_tune_ff, output_secondary_nh=output_secondary_nh,
        broadband=broadband,
    )
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before three-stage teaching probe")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    probe = runner.probe(tools=("spectre",))
    tools = runner.run_remote(["pgrep", "-x", "vmtoolsd"], timeout_seconds=20)
    if probe["status"] != "ok" or not probe["tools"]["spectre"]["found"] or not tools.ok:
        raise RuntimeError("SSH, Spectre, or guest Tools preflight failed")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist)
    shutil.copy2(PUBLIC_MODEL, output_dir / "teaching_mos1_model.scs")
    remote_name = (
        f"teach3_{spec.id}_seed{candidate.seed}_{candidate.candidate_id}_{output_dir.name}"
        if candidate is not None else f"teach3_{uuid4().hex[:12]}"
    )
    remote_dir = str(PurePosixPath(runner.config.remote_root) / remote_name)
    if candidate is not None:
        identity_sha256 = write_remote_identity_snapshot(output_dir, runner.config)
        write_json(output_dir / "candidate.json", candidate.to_dict())
        write_json(output_dir / "dispatch_plan.json", {
            "schema_version": 1, "run_id": output_dir.name,
            "remote_dir": remote_dir, "remote_identity_sha256": identity_sha256,
            "netlist_sha256": hashlib.sha256(netlist).hexdigest(),
            "model_sha256": hashlib.sha256(PUBLIC_MODEL.read_bytes()).hexdigest(),
            "candidate": candidate.to_dict(), "spec": asdict(spec),
            "host_available_gib_before": available,
            "spectre_timeout_seconds": 180, "spectre_dispatched_by_recovery": False,
        })

    def fail(reason: str) -> None:
        write_json(output_dir / "failure.json", {
            "status": reason, "not_lna_result": True, "spec_pass": None,
            "host_available_gib_before": available, "output_tune_ff": output_tune_ff,
            "output_secondary_nh": output_secondary_nh, "broadband": broadband,
        })
        raise RuntimeError(f"three-stage probe failed at {reason}; raw archive retained")

    if candidate is not None:
        if not runner.ensure_remote_dir(runner.config.remote_root).ok:
            fail("remote_root")
        if not runner.run_remote(["mkdir", "--", remote_dir], timeout_seconds=20).ok:
            fail("remote_directory")
    elif not runner.ensure_remote_dir(remote_dir).ok:
        fail("remote_directory")
    for local, remote in ((output_dir / "netlist.scs", "teaching_three_stage_probe.scs"),
                          (output_dir / "teaching_mos1_model.scs", "teaching_mos1_model.scs")):
        if not runner.upload(local, f"{remote_dir}/{remote}").ok:
            fail("upload")
    try:
        result = runner.run_remote(
            [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
             "+log", "spectre.log", "teaching_three_stage_probe.scs"],
            cwd=remote_dir, timeout_seconds=180,
        )
    except Exception as exc:
        if candidate is None:
            raise
        write_json(output_dir / "dispatch_uncertain.json", {
            "schema_version": 1, "status": "unverified_remote_dispatch",
            "run_id": output_dir.name, "safe_to_retry": False,
            "not_lna_result": True, "spec_pass": None,
        })
        raise RemoteEvaluationUncertain("three-stage remote dispatch outcome is uncertain") from exc
    if candidate is not None and result.returncode in {124, 255}:
        (output_dir / "spectre.stdout.log").write_text(result.stdout, encoding="utf-8")
        (output_dir / "spectre.stderr.log").write_text(result.stderr, encoding="utf-8")
        write_json(output_dir / "dispatch_uncertain.json", {
            "schema_version": 1, "status": "unverified_remote_dispatch",
            "run_id": output_dir.name, "control_returncode": result.returncode,
            "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
        })
        raise RemoteEvaluationUncertain("three-stage remote dispatch outcome is uncertain")
    (output_dir / "spectre.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(result.stderr, encoding="utf-8")
    log_ok = runner.download(f"{remote_dir}/spectre.log", output_dir / "spectre.log").ok
    if not result.ok or not log_ok:
        fail("spectre_or_log")
    downloads = (
        ("teaching_three_stage_probe.scs", "remote_teaching_three_stage_probe.scs"),
        ("teaching_mos1_model.scs", "remote_teaching_mos1_model.scs"),
        ("psf/dcOp.dc", "dcOp.dc"), ("psf/dcOpInfo.info", "dcOpInfo.info"),
        ("psf/sp.sp", "sp.sp"), ("psf/sp.noise.sp", "sp.noise.sp"),
        ("teaching_three_stage_probe.s2p", "teaching_three_stage_probe.s2p"),
    )
    for remote, local in downloads:
        if not runner.download(f"{remote_dir}/{remote}", output_dir / local).ok:
            fail("raw_download")
    probe_status = {
        "status": "raw_probe_only", "spectre_returncode": result.returncode,
        "spectre_log_downloaded": True, "host_available_gib_before": available,
        "output_tune_ff": output_tune_ff, "not_lna_result": True, "spec_pass": None,
        "output_secondary_nh": output_secondary_nh,
    }
    if broadband:
        probe_status["broadband"] = True
    if candidate is not None:
        probe_status.update({
            "candidate": candidate.to_dict(), "spec": asdict(spec),
            "seed": candidate.seed, "timeout_seconds": 180,
            "dispatch_protocol_version": 3,
        })
    write_json(output_dir / "probe_status.json", probe_status)
    try:
        rows, payload = extract_teaching_three_stage(output_dir)
        write_active_oa_results(output_dir, rows, payload)
        write_evidence_manifest(
            output_dir, {
                **_ARTIFACTS,
                **({
                    "candidate": "candidate.json", "dispatch_plan": "dispatch_plan.json",
                    "remote_identity": "agent_remote.json",
                } if candidate else {}),
            },
        )
        audit_teaching_three_stage(output_dir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        if not (output_dir / "metrics.json").exists():
            fail(f"extraction_{type(exc).__name__}")
        raise RuntimeError("three-stage audit failed; raw archive retained") from exc
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public MOS1 three-stage topology probe in Spectre")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage")
    parser.add_argument("--output-tune-ff", type=float, default=0.0)
    parser.add_argument("--output-secondary-nh", type=float, default=1.0)
    parser.add_argument("--broadband", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_three_stage(
            args.config, output_dir, output_tune_ff=args.output_tune_ff,
            output_secondary_nh=args.output_secondary_nh, broadband=args.broadband,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
