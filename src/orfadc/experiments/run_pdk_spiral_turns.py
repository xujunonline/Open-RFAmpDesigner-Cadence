from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_inductor_oneport import audit_pdk_inductor_oneport
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path


_NR = re.compile(rb"(?m)^L1 \([^\n]+\) [A-Za-z_][A-Za-z0-9_]* w=6u rad=20u nr=3 lay=10 gdis=20u\b")
_RAW = ("sp.sp",)


def render_spiral_turns_netlist(source: bytes, turns: int) -> bytes:
    if type(turns) is not int or not 2 <= turns <= 9 or turns == 3:
        raise ValueError("diagnostic spiral turns must be an integer from 2 to 9 other than the default 3")
    derived, count = _NR.subn(lambda match: match.group().replace(b"nr=3", f"nr={turns}".encode("ascii")), source)
    if count != 1:
        raise ValueError("source lacks exactly one expected default spiral instance")
    return derived


def render_spiral_turns_wrapper() -> bytes:
    return b'simulator lang=spectre\ninclude "netlist.scs"\nsp sp ports=[PORT1] start=500M stop=30G lin=590\n'


def run_pdk_spiral_turns(
    config_path: Path, output_dir: Path, *, source_dir: Path, turns: int,
    runner: RemoteRunner | None = None,
) -> dict:
    for path in (source_dir, output_dir):
        _require_private_path(path)
    audit_pdk_inductor_oneport(source_dir)
    if json.loads((source_dir / "run_status.json").read_text(encoding="utf-8")).get("geometry_variant", "default") != "default":
        raise ValueError("turns probe requires the audited default standard spiral")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before spiral turns probe")
    source = (source_dir / "netlist.scs").read_bytes()
    derived = render_spiral_turns_netlist(source, turns)
    wrapper = render_spiral_turns_wrapper()
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(derived)
    (output_dir / "wrapper.scs").write_bytes(wrapper)
    shutil.copy2(source_dir / "ade_e.scs", output_dir / "ade_e.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"spiral_turns_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_run_id": source_dir.name, "turns": turns,
        "source_manifest_sha256": hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "source_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(derived).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "host_available_gib_before": available,
        "pdk_write": False, "user_oa_write": False, "cdf_callback_validated": False,
        "geometry_sweep_verified": False, "physical_qualification": False,
        "not_lna_result": True, "spec_pass": None,
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
         "-raw", "psf", "+log", "spectre.log", "wrapper.scs"],
        cwd=remote_dir, timeout_seconds=180,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    names = ("spectre.log", *_RAW, "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs")
    downloads = {}
    for name in names:
        remote_name = name.removeprefix("remote_") if name.startswith("remote_") else (
            f"psf/{name}" if name in _RAW else name
        )
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
    parser = argparse.ArgumentParser(description="Diagnose an unqualified PDK spiral turns perturbation")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--turns", type=int, required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_spiral_turns")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_pdk_spiral_turns(args.config, output_dir, source_dir=args.source_dir, turns=args.turns)
    print(f"status={result['status']} output={output_dir.resolve()}")
    return 0 if result["status"] == "simulation_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
