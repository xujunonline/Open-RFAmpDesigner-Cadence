from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_rf_input_lmatch import render_lmatch_wrapper


_CREATE = "rf_default_create_20260926T231047Z_38b59de6"
_BASE = "rf_default_sp_20260926T231333Z_19c5f59b"
_PORT1 = re.compile(r"(?m)^PORT1 \(in 0\) port r=50 num=1 type=sine\r?$")
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp")


def render_source_termination_netlist(source: bytes, source_ohm: int) -> bytes:
    if type(source_ohm) is not int or source_ohm != 100:
        raise ValueError("this controlled source-termination comparison requires 100 ohm")
    rendered, count = _PORT1.subn(
        "PORT1 (in 0) port r=100 num=1 type=sine", source.decode("utf-8"),
    )
    if count != 1:
        raise ValueError("RF OA source netlist lacks its unique 50-ohm input port")
    return rendered.encode("utf-8")


def render_source_termination_wrapper() -> bytes:
    source = render_lmatch_wrapper()
    if source.count(b"matched.s2p") != 1:
        raise ValueError("bounded RF SP/noise wrapper changed")
    return source.replace(b"matched.s2p", b"source_termination.s2p")


def run_pdk_rf_source_termination(
    config_path: Path, output_dir: Path, *, runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    base_root = _PRIVATE_ROOT / "pdk_three_stage_fixed"
    base_dir, create_dir = base_root / _BASE, base_root / _CREATE
    audit_pdk_rf_default_three_stage(base_dir, create_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before source termination diagnostic")
    source = (base_dir / "netlist.scs").read_bytes()
    netlist = render_source_termination_netlist(source, 100)
    wrapper = render_source_termination_wrapper()
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist)
    (output_dir / "wrapper.scs").write_bytes(wrapper)
    shutil.copy2(base_dir / "ade_e.scs", output_dir / "ade_e.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_source_termination_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_active_run_id": _BASE, "source_create_run_id": _CREATE,
        "source_manifest_sha256": hashlib.sha256((base_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "source_oa_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(netlist).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "source_ohm": 100, "host_available_gib_before": available,
        "pdk_write": False, "user_oa_write": False, "physical_qualification": False,
        "cdf_callback_validated": False, "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["spectre_returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    for name in ("netlist.scs", "ade_e.scs", "wrapper.scs"):
        if not runner.upload(output_dir / name, str(PurePosixPath(remote_dir) / name)).ok:
            return finish("upload_failed")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii",
         "-raw", "psf", "+log", "spectre.log", "wrapper.scs"], cwd=remote_dir,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    names = ("spectre.log", "source_termination.s2p", *_RAW,
             "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs")
    downloads = {}
    for name in names:
        remote_name = (name.removeprefix("remote_") if name.startswith("remote_") else
                       f"psf/{name}" if name in _RAW else name)
        downloads[name] = runner.download(str(PurePosixPath(remote_dir) / remote_name), output_dir / name).ok
    status["downloads"] = downloads
    if not result.ok or not all(downloads.values()):
        return finish("spectre_or_download_failed", result.returncode)
    if any((output_dir / f"remote_{name}").read_bytes() != (output_dir / name).read_bytes()
           for name in ("netlist.scs", "wrapper.scs", "ade_e.scs")):
        return finish("remote_source_mismatch", result.returncode)
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*5 warnings", log):
        return finish("spectre_log_unexpected", result.returncode)
    return finish("simulation_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run controlled 100-ohm RF source termination diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_source_termination")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    status = run_pdk_rf_source_termination(args.config, output_dir)
    print(f"status={status['status']} output={output_dir.resolve()}")
    return 0 if status["status"] == "simulation_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
