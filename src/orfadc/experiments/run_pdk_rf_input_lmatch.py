from __future__ import annotations

import argparse
import hashlib
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.passive_quality import oneport_impedance
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.analyze_pdk_rf_input_match import _at
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path


_PORT1 = re.compile(r"(?m)^PORT1 \(in 0\) port r=50 num=1 type=sine\r?$")
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp")


def synthesize_input_lmatch(active_dir: Path) -> tuple[float, float]:
    frequency, reflection = parse_complex_trace(active_dir / "sp.sp", "s11")
    impedance = oneport_impedance(_at(frequency, reflection, 10e9), 50.0)
    admittance = 1 / impedance
    conductance, susceptance = admittance.real, admittance.imag
    target_sq = conductance / 50.0 - conductance**2
    if conductance <= 0 or target_sq <= 0:
        raise ValueError("center-frequency input cannot use this passive L-match branch")
    target_susceptance = -math.sqrt(target_sq)
    omega = 2 * math.pi * 10e9
    shunt_l_h = 1 / (omega * (susceptance - target_susceptance))
    parallel_z = 1 / complex(conductance, target_susceptance)
    series_c_f = 1 / (omega * parallel_z.imag)
    if not all(math.isfinite(value) and value > 0 for value in (shunt_l_h, series_c_f)):
        raise ValueError("L-match synthesis did not produce positive finite components")
    return shunt_l_h, series_c_f


def render_input_lmatch(source: bytes, shunt_l_h: float, series_c_f: float) -> bytes:
    if any(type(value) is not float or not math.isfinite(value) or value <= 0
           for value in (shunt_l_h, series_c_f)):
        raise ValueError("L-match component values must be positive finite floats")
    text = source.decode("utf-8")
    if re.search(r"(?m)^(?:C_MATCH|L_MATCH)\s", text):
        raise ValueError("source netlist already contains a matching component")
    replacement = (
        "PORT1 (match_in 0) port r=50 num=1 type=sine\n"
        f"C_MATCH (match_in in) capacitor c={series_c_f:.17g}\n"
        f"L_MATCH (in 0) inductor l={shunt_l_h:.17g}"
    )
    rendered, count = _PORT1.subn(replacement, text)
    if count != 1:
        raise ValueError("source netlist lacks one expected input port")
    return rendered.encode("utf-8")


def render_lmatch_wrapper() -> bytes:
    return (
        "simulator lang=spectre\n"
        'include "netlist.scs"\n'
        "dcOp dc\n"
        "dcOpInfo info what=oppoint where=rawfile\n"
        "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2] \\\n"
        '    paramtype=s file="matched.s2p" datafmt=touchstone \\\n'
        "    donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport\n"
    ).encode("ascii")


def run_pdk_rf_input_lmatch(
    config_path: Path, output_dir: Path, *, active_dir: Path, create_dir: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    for path in (output_dir, active_dir, create_dir):
        _require_private_path(path)
    audit_pdk_rf_default_three_stage(active_dir, create_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before RF input L-match simulation")
    shunt_l_h, series_c_f = synthesize_input_lmatch(active_dir)
    source = (active_dir / "netlist.scs").read_bytes()
    netlist = render_input_lmatch(source, shunt_l_h, series_c_f)
    wrapper = render_lmatch_wrapper()
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist)
    (output_dir / "wrapper.scs").write_bytes(wrapper)
    shutil.copy2(active_dir / "ade_e.scs", output_dir / "ade_e.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_lmatch_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_active_run_id": active_dir.name, "source_create_run_id": create_dir.name,
        "source_oa_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(netlist).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "shunt_l_h": shunt_l_h, "series_c_f": series_c_f,
        "host_available_gib_before": available,
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
    names = ("spectre.log", "matched.s2p", *_RAW, "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs")
    downloads = {}
    for name in names:
        if name.startswith("remote_"):
            remote_name = name.removeprefix("remote_")
        elif name in _RAW:
            remote_name = f"psf/{name}"
        else:
            remote_name = name
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
    parser = argparse.ArgumentParser(description="Simulate one ideal center-frequency L-match on an archived private RF OA netlist")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--active-dir", type=Path, required=True)
    parser.add_argument("--create-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_input_lmatch")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_pdk_rf_input_lmatch(
        args.config, output_dir, active_dir=args.active_dir, create_dir=args.create_dir,
    )
    print(f"status={result['status']} output={output_dir.resolve()}")
    return 0 if result["status"] == "simulation_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
