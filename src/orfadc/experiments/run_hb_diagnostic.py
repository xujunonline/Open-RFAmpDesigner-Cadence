from __future__ import annotations

import argparse
import math
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.hb_metrics import extract_hb_fundamental_power, extract_sp_s21_at_frequency
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB,
    _PRIVATE_ROOT,
    _read_ade_companion,
    _require_private_path,
    render_active_diagnostic_netlist,
)
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate


_INPUT_PORT = re.compile(r"^(PORT1 \([^\r\n)]+\) port r=50 num=1) type=sine(?=\r?$)", re.MULTILINE)
_OUTPUT_PORT = re.compile(r"^(PORT2 \([^\r\n)]+\) port r=50 num=2) type=sine(?=\r?$)", re.MULTILINE)
_OUTPUT_NODE = re.compile(r"^PORT2 \(([A-Za-z0-9_.]+) 0\) port r=50 num=2 type=dc(?=\r?$)", re.MULTILINE)
_HB_RAW_FILES = ("hb.fd.pss_hb", "hb.fi.pss_hb", "hb.td.pss_hb")
_OTHER_RAW_FILES = ("dcOp.dc", "sp.sp", "sp.noise.sp")


def render_hb_diagnostic_netlist(
    template: Path,
    template_sha256: str,
    *,
    rd_ohm: float,
    vbias_v: float,
    input_dbm: float,
    frequency_ghz: float,
    harmonics: int = 3,
) -> str:
    if (
        type(input_dbm) not in {int, float} or not math.isfinite(input_dbm)
        or not -100 <= input_dbm <= 0
        or type(frequency_ghz) not in {int, float} or not math.isfinite(frequency_ghz)
        or not 0.1 <= frequency_ghz <= 20
        or type(harmonics) is not int or not 1 <= harmonics <= 7
    ):
        raise ValueError("HB input must have -100..0 dBm, 0.1..20 GHz, and 1..7 harmonics")
    candidate = Candidate(
        candidate_id="hb_diagnostic", spec_id="diagnostic", seed=0,
        power_ratio_list=[], active_params={"rd_ohm": rd_ohm, "vbias_v": vbias_v},
        status="active_common_source_diagnostic",
    )
    source = render_active_diagnostic_netlist(candidate, template, template_sha256)
    source, input_count = _INPUT_PORT.subn(
        lambda match: f"{match[1]} type=sine dbm={input_dbm:.17g} freq={frequency_ghz * 1e9:.17g}", source
    )
    source, output_count = _OUTPUT_PORT.subn(lambda match: f"{match[1]} type=dc", source)
    if input_count != 1 or output_count != 1 or re.search(r"^hb\s+hb\b", source, re.MULTILINE):
        raise ValueError("OA diagnostic netlist lacks unique expected ports or already contains HB")
    return source + f"\nhb hb fundfreqs=[{frequency_ghz * 1e9:.17g}] maxharms=[{harmonics}] annotate=status\n"


def run_hb_diagnostic(
    config_path: Path,
    output_dir: Path,
    *,
    template: Path,
    template_sha256: str,
    rd_ohm: float,
    vbias_v: float,
    input_dbm: float,
    frequency_ghz: float = 10.0,
    harmonics: int = 3,
) -> dict:
    _require_private_path(output_dir)
    netlist = render_hb_diagnostic_netlist(
        template, template_sha256, rd_ohm=rd_ohm, vbias_v=vbias_v,
        input_dbm=input_dbm, frequency_ghz=frequency_ghz, harmonics=harmonics,
    )
    output_nodes = _OUTPUT_NODE.findall(netlist)
    if len(output_nodes) != 1:
        raise ValueError("HB netlist lacks one grounded 50-ohm output port")
    companion = _read_ade_companion(template, netlist)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before HB diagnostic")
    runner = RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist.encode("utf-8"))
    if companion is not None:
        (output_dir / "ade_e.scs").write_bytes(companion)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"hb_diag_{uuid4().hex[:12]}")
    payload = {
        "schema_version": 1,
        "status": "unknown",
        "simulation_status": "unknown",
        "circuit_class": "active_common_source_smoke",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": output_dir.name,
        "scope": "one-power-point HB raw-data diagnostic; not a compression-point result",
        "analysis": ["dc", "sp", "noise", "hb"],
        "timeout_seconds": runner.config.command_timeout_seconds,
        "parameters": {"rd_ohm": rd_ohm, "vbias_v": vbias_v, "input_dbm": input_dbm,
                       "frequency_ghz": frequency_ghz, "harmonics": harmonics},
        "host_available_gib_before": available,
    }

    def finish(status: str, *, simulation_status: str = "unknown", error: str | None = None) -> dict:
        payload["status"] = status
        payload["simulation_status"] = simulation_status
        if error:
            payload["error"] = error
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        artifacts = {key: filename for key, filename in {
            "metrics": "metrics.json", "netlist": "netlist.scs", "ade_companion": "ade_e.scs",
            "spectre_log": "spectre.log", "dc_raw": "dcOp.dc",
            "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp", "hb_fd_raw": "hb.fd.pss_hb",
            "hb_fi_raw": "hb.fi.pss_hb", "hb_td_raw": "hb.td.pss_hb",
            "stdout": "spectre.stdout.log", "stderr": "spectre.stderr.log",
        }.items() if (output_dir / filename).is_file()}
        write_evidence_manifest(output_dir, artifacts)
        return payload

    created = runner.ensure_remote_dir(remote_dir)
    if not created.ok:
        return finish("mkdir_failed", error=f"returncode={created.returncode}")
    for name in ("netlist.scs", "ade_e.scs"):
        if not (output_dir / name).exists():
            continue
        upload = runner.upload(output_dir / name, str(PurePosixPath(remote_dir) / name))
        if not upload.ok:
            return finish("upload_failed", error=f"file={name} returncode={upload.returncode}")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "-format", "psfascii", "-raw", "psf", "+log", "spectre.log", "netlist.scs"],
        cwd=remote_dir,
    )
    (output_dir / "spectre.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(result.stderr, encoding="utf-8")
    log_result = runner.download(str(PurePosixPath(remote_dir) / "spectre.log"), output_dir / "spectre.log")
    if not result.ok:
        return finish("spectre_failed", simulation_status="failed", error=f"returncode={result.returncode}")
    if not log_result.ok:
        return finish("log_download_failed", error=f"returncode={log_result.returncode}")
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if "spectre completes with 0 errors" not in log:
        return finish("unclean_spectre_log")
    for name in _HB_RAW_FILES:
        raw_result = runner.download(str(PurePosixPath(remote_dir) / "psf" / name), output_dir / name)
        if not raw_result.ok:
            return finish("hb_raw_download_failed", error=f"file={name} returncode={raw_result.returncode}")
    for name in _OTHER_RAW_FILES:
        raw_result = runner.download(str(PurePosixPath(remote_dir) / "psf" / name), output_dir / name)
        if not raw_result.ok:
            return finish("analysis_raw_download_failed", error=f"file={name} returncode={raw_result.returncode}")
    payload["source"] = "cadence_spectre"
    try:
        fundamental = extract_hb_fundamental_power(
            output_dir / "hb.fd.pss_hb", output_node=output_nodes[0],
            fundamental_hz=frequency_ghz * 1e9,
        )
        s21_db = extract_sp_s21_at_frequency(output_dir / "sp.sp", frequency_ghz * 1e9)
    except (OSError, ValueError) as exc:
        return finish("result_parse_failed", simulation_status="ok", error=str(exc))
    power_gain_db = fundamental["output_power_dbm"] - input_dbm
    payload["metrics"] = {
        **fundamental,
        "input_available_power_dbm": input_dbm,
        "power_gain_db": power_gain_db,
        "small_signal_s21_db": s21_db,
        "hb_minus_s21_db": power_gain_db - s21_db,
    }
    payload["units"] = {
        "fundamental_hz": "Hz", "vout_peak_v": "V", "iout_peak_a": "A",
        "output_power_dbm": "dBm", "input_available_power_dbm": "dBm",
        "power_gain_db": "dB", "small_signal_s21_db": "dB", "hb_minus_s21_db": "dB",
        "load_current_relative_error": "1",
    }
    payload["reference_planes"] = {"input": "PORT1_available_power", "output": "PORT2_50ohm_load", "z0_ohm": 50.0}
    return finish("hb_fundamental_extracted", simulation_status="ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture one OA common-source Spectre HB diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "hb_diagnostic")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    parser.add_argument("--input-dbm", type=float, required=True)
    parser.add_argument("--frequency-ghz", type=float, default=10.0)
    parser.add_argument("--harmonics", type=int, default=3)
    args = parser.parse_args()
    output = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_hb_diagnostic(
            args.config, output, template=args.template, template_sha256=args.template_sha256,
            rd_ohm=args.rd_ohm, vbias_v=args.vbias_v, input_dbm=args.input_dbm,
            frequency_ghz=args.frequency_ghz, harmonics=args.harmonics,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']}")
    print(f"output={output.resolve()}")
    return 0 if payload["status"] == "hb_fundamental_extracted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
