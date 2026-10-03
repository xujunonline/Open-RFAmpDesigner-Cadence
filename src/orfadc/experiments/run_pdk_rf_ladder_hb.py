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
from orfadc.experiments.audit_pdk_rf_input_ladder import audit_pdk_rf_input_ladder
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)


_INPUT = re.compile(rb"(?m)^PORT1 \(match_out 0\) port r=50 num=1 type=sine\r?$")
_OUTPUT = re.compile(rb"(?m)^PORT2 \(outp outn\) port r=1787 num=2 type=sine\r?$")
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp",
        "hb.fd.pss_hb", "hb.fi.pss_hb", "hb.td.pss_hb")


def render_pdk_rf_ladder_hb(source: bytes, input_dbm: int, *, harmonics: int = 7) -> bytes:
    if type(input_dbm) is not int or not -100 <= input_dbm <= 0:
        raise ValueError("ladder HB input must be an integer in -100..0 dBm")
    if type(harmonics) is not int or harmonics not in {7, 9, 11}:
        raise ValueError("ladder HB harmonics must be 7, 9 or 11")
    if re.search(rb"(?m)^(?:dcOp |dcOpInfo |sp |hb )", source):
        raise ValueError("ladder source already has an analysis")
    derived, input_count = _INPUT.subn(
        f"PORT1 (match_out 0) port r=50 num=1 type=sine dbm={input_dbm} freq=10G".encode(),
        source,
    )
    derived, output_count = _OUTPUT.subn(
        b"PORT2 (outp outn) port r=1787 num=2 type=dc", derived,
    )
    if input_count != 1 or output_count != 1 or source.count(b'include "ade_e.scs"') != 1:
        raise ValueError("ladder source lacks unique expected ports or companion")
    return derived + (
        "\ndcOp dc\n"
        "dcOpInfo info what=oppoint where=rawfile\n"
        "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2] \\\n"
        '    paramtype=s file="ladder_hb.s2p" datafmt=touchstone \\\n'
        "    donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport\n"
        f"hb hb fundfreqs=[10G] maxharms=[{harmonics}] annotate=status\n"
    ).encode()


def run_pdk_rf_ladder_hb(
    config_path: Path, output_dir: Path, *, ladder_dir: Path,
    input_dbm: int = -70, harmonics: int = 7,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    _require_private_path(ladder_dir)
    audit_pdk_rf_input_ladder(ladder_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before ladder HB")
    source = (ladder_dir / "netlist.scs").read_bytes()
    derived = render_pdk_rf_ladder_hb(source, input_dbm, harmonics=harmonics)
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "ladder_input.scs").write_bytes(source)
    (output_dir / "netlist.scs").write_bytes(derived)
    shutil.copy2(ladder_dir / "ade_e.scs", output_dir / "ade_e.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_ladder_hb_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "ladder_run_id": ladder_dir.name, "input_dbm": input_dbm,
        "harmonics": harmonics, "ladder_manifest_sha256": hashlib.sha256(
            (ladder_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "source_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(derived).hexdigest(),
        "host_available_gib_before": available,
        "pdk_write": False, "user_oa_write": False,
        "physical_qualification": False, "cdf_callback_validated": False,
        "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["spectre_returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    for name in ("netlist.scs", "ade_e.scs"):
        if not runner.upload(output_dir / name, str(PurePosixPath(remote_dir) / name)).ok:
            return finish("upload_failed")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii",
         "-raw", "psf", "+log", "spectre.log", "netlist.scs"], cwd=remote_dir,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    names = ("spectre.log", "ladder_hb.s2p", *_RAW,
             "remote_netlist.scs", "remote_ade_e.scs")
    downloads = {}
    for name in names:
        if name.startswith("remote_"):
            remote_name = name.removeprefix("remote_")
        elif name in _RAW:
            remote_name = f"psf/{name}"
        else:
            remote_name = name
        downloads[name] = runner.download(
            str(PurePosixPath(remote_dir) / remote_name), output_dir / name,
        ).ok
    status["downloads"] = downloads
    if not result.ok or not all(downloads.values()):
        return finish("spectre_or_download_failed", result.returncode)
    if any((output_dir / f"remote_{name}").read_bytes() != (output_dir / name).read_bytes()
           for name in ("netlist.scs", "ade_e.scs")):
        return finish("remote_source_mismatch", result.returncode)
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*5 warnings", log):
        return finish("spectre_log_unexpected", result.returncode)
    return finish("simulation_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate one archived RF ladder HB drive point")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--ladder-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_ladder_hb")
    parser.add_argument("--input-dbm", type=int, default=-70)
    parser.add_argument("--harmonics", type=int, default=7)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_pdk_rf_ladder_hb(
        args.config, output_dir, ladder_dir=args.ladder_dir,
        input_dbm=args.input_dbm, harmonics=args.harmonics,
    )
    print(f"status={result['status']} output={output_dir.resolve()}")
    return 0 if result["status"] == "simulation_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
