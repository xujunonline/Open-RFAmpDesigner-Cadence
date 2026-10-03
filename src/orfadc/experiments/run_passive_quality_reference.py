from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_passive_quality_reference import (
    _TEMPLATE, finalize_passive_quality_reference,
)
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)


def run_passive_quality_reference(
    config_path: Path, output_dir: Path, *, runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before passive quality reference")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    probe = runner.probe(tools=("spectre",))
    guest = runner.run_remote(["pgrep", "-x", "vmtoolsd"], timeout_seconds=20)
    if probe["status"] != "ok" or not probe["tools"]["spectre"]["found"] or not guest.ok:
        raise RuntimeError("SSH, Spectre, or guest Tools preflight failed")
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_TEMPLATE, output_dir / "netlist.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"passive_q_{uuid4().hex[:12]}")

    def fail(reason: str) -> None:
        write_json(output_dir / "failure.json", {
            "status": reason, "not_lna_result": True, "spec_pass": None,
            "physical_qualification": False, "host_available_gib_before": available,
        })
        raise RuntimeError(f"passive quality reference failed at {reason}; raw archive retained")

    if not runner.ensure_remote_dir(remote_dir).ok:
        fail("remote_directory")
    if not runner.upload(output_dir / "netlist.scs", f"{remote_dir}/netlist.scs").ok:
        fail("upload")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
         "+log", "spectre.log", "netlist.scs"], cwd=remote_dir, timeout_seconds=180,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    log_ok = runner.download(f"{remote_dir}/spectre.log", output_dir / "spectre.log").ok
    if not result.ok or not log_ok:
        fail("spectre_or_log")
    for remote, local in (
        ("netlist.scs", "remote_netlist.scs"), ("psf/sp.sp", "sp.sp"),
        ("teaching_inductor_quality.s1p", "teaching_inductor_quality.s1p"),
    ):
        if not runner.download(f"{remote_dir}/{remote}", output_dir / local).ok:
            fail("raw_download")
    try:
        return finalize_passive_quality_reference(output_dir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        if (output_dir / "metrics.json").exists():
            raise RuntimeError("passive quality audit failed; raw archive retained") from exc
        fail(f"extraction_{type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public one-port passive quality reference in Spectre")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "passive_quality_reference")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_passive_quality_reference(args.config, output_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
