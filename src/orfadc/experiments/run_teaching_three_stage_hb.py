from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage_hb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage_hb import (
    _ARTIFACTS, audit_teaching_three_stage_hb, extract_teaching_three_stage_hb,
)
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)


def run_teaching_three_stage_hb(
    config_path: Path, output_dir: Path, *, input_dbm: float = -70.0,
    output_secondary_nh: float = 1.0, frequency_ghz: float = 10.0,
    harmonics: int = 7, runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    if type(input_dbm) not in {int, float} or not -100 <= input_dbm <= 0:
        raise ValueError("three-stage HB requires -100..0 dBm")
    netlist = render_teaching_three_stage_hb(
        input_dbm, output_secondary_nh=output_secondary_nh,
        frequency_ghz=frequency_ghz, harmonics=harmonics,
    )
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before three-stage low-drive HB")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    probe = runner.probe(tools=("spectre",))
    guest = runner.run_remote(["pgrep", "-x", "vmtoolsd"], timeout_seconds=20)
    if probe["status"] != "ok" or not probe["tools"]["spectre"]["found"] or not guest.ok:
        raise RuntimeError("SSH, Spectre, or guest Tools preflight failed")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist)
    shutil.copy2(PUBLIC_MODEL, output_dir / "teaching_mos1_model.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"teach3_hb_{uuid4().hex[:12]}")

    def fail(reason: str) -> None:
        write_json(output_dir / "failure.json", {
            "status": reason, "not_lna_result": True, "spec_pass": None,
            "input_dbm": input_dbm, "host_available_gib_before": available,
        })
        raise RuntimeError(f"three-stage low-drive HB failed at {reason}; raw archive retained")

    if not runner.ensure_remote_dir(remote_dir).ok:
        fail("remote_directory")
    for local, name in ((output_dir / "netlist.scs", "netlist.scs"),
                        (output_dir / "teaching_mos1_model.scs", "teaching_mos1_model.scs")):
        if not runner.upload(local, f"{remote_dir}/{name}").ok:
            fail("upload")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
         "+log", "spectre.log", "netlist.scs"], cwd=remote_dir, timeout_seconds=240,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    log_ok = runner.download(f"{remote_dir}/spectre.log", output_dir / "spectre.log").ok
    if not result.ok or not log_ok:
        fail("spectre_or_log")
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if "spectre completes with 0 errors, 0 warnings" not in log:
        fail("spectre_warning_or_error")
    downloads = (
        ("netlist.scs", "remote_netlist.scs"),
        ("teaching_mos1_model.scs", "remote_teaching_mos1_model.scs"),
        ("psf/dcOp.dc", "dcOp.dc"), ("psf/dcOpInfo.info", "dcOpInfo.info"),
        ("psf/sp.sp", "sp.sp"), ("psf/sp.noise.sp", "sp.noise.sp"),
        ("psf/hb.fd.pss_hb", "hb.fd.pss_hb"),
        ("psf/hb.fi.pss_hb", "hb.fi.pss_hb"),
        ("psf/hb.td.pss_hb", "hb.td.pss_hb"),
        ("teaching_three_stage_probe.s2p", "teaching_three_stage_probe.s2p"),
    )
    for remote, local in downloads:
        if not runner.download(f"{remote_dir}/{remote}", output_dir / local).ok:
            fail("raw_download")
    try:
        rows, payload = extract_teaching_three_stage_hb(output_dir)
        write_active_oa_results(output_dir, rows, payload)
        write_evidence_manifest(output_dir, _ARTIFACTS)
        audit_teaching_three_stage_hb(output_dir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        if (output_dir / "metrics.json").exists():
            raise RuntimeError("three-stage HB audit failed; raw archive retained") from exc
        fail(f"extraction_{type(exc).__name__}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public MOS1 three-stage low-drive differential HB")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_hb")
    parser.add_argument("--input-dbm", type=float, default=-70.0)
    parser.add_argument("--output-secondary-nh", type=float, default=1.0)
    parser.add_argument("--frequency-ghz", type=float, default=10.0)
    parser.add_argument("--harmonics", type=int, default=7)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_three_stage_hb(
            args.config, output_dir, input_dbm=args.input_dbm,
            output_secondary_nh=args.output_secondary_nh,
            frequency_ghz=args.frequency_ghz, harmonics=args.harmonics,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
