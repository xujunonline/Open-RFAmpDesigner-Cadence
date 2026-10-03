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
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_lna import render_teaching_lna_netlist
from orfadc.metric_contract import validate_metrics_payload


_INPUT = re.compile(r"^(PORT1 \(in 0\) port r=50 num=1) type=sine(?=\r?$)", re.MULTILINE)
_OUTPUT = re.compile(r"^(PORT2 \(out 0\) port r=50 num=2) type=sine(?=\r?$)", re.MULTILINE)
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp", "hb.fd.pss_hb", "hb.fi.pss_hb", "hb.td.pss_hb")


def render_teaching_hb_netlist(
    input_dbm: float, *, frequency_ghz: float = 10.0, harmonics: int = 7,
    vbias_v: float = 0.65,
    ldd_nh: float = 2.0, cblock_ff: float = 5000.0,
    rdamp_ohm: float | None = None,
    sp_intervals: int = 199, sp_start_ghz: float = 0.1,
    sp_stop_ghz: float = 20.0,
) -> str:
    if (
        type(input_dbm) not in {int, float} or not math.isfinite(input_dbm) or not -100 <= input_dbm <= 0
        or type(frequency_ghz) not in {int, float} or not math.isfinite(frequency_ghz)
        or not 0.1 <= frequency_ghz <= 20
        or type(harmonics) is not int or not 1 <= harmonics <= 7
    ):
        raise ValueError("teaching HB needs -100..0 dBm, 0.1..20 GHz, and 1..7 harmonics")
    source = render_teaching_lna_netlist(
        vbias_v, ldd_nh=ldd_nh, cblock_ff=cblock_ff, rdamp_ohm=rdamp_ohm,
        sp_intervals=sp_intervals, sp_start_ghz=sp_start_ghz,
        sp_stop_ghz=sp_stop_ghz,
    ).decode("ascii")
    step = (sp_stop_ghz - sp_start_ghz) / sp_intervals
    grid_index = (frequency_ghz - sp_start_ghz) / step
    if not sp_start_ghz <= frequency_ghz <= sp_stop_ghz or not math.isclose(
        grid_index, round(grid_index), rel_tol=0, abs_tol=1e-8,
    ):
        raise ValueError("teaching HB frequency must lie on the SP grid")
    source, input_count = _INPUT.subn(
        lambda m: f"{m[1]} type=sine dbm={input_dbm:.17g} freq={frequency_ghz * 1e9:.17g}", source
    )
    source, output_count = _OUTPUT.subn(lambda m: f"{m[1]} type=dc", source)
    if input_count != 1 or output_count != 1:
        raise ValueError("teaching HB needs exactly one 50-ohm input and output port")
    return source + f"\nhb hb fundfreqs=[{frequency_ghz * 1e9:.17g}] maxharms=[{harmonics}] annotate=status\n"


def run_teaching_hb(
    config_path: Path, output_dir: Path, *, input_dbm: float,
    frequency_ghz: float = 10.0, harmonics: int = 7,
    vbias_v: float = 0.65,
    ldd_nh: float = 2.0, cblock_ff: float = 5000.0,
    rdamp_ohm: float | None = None,
    sp_intervals: int = 199, sp_start_ghz: float = 0.1,
    sp_stop_ghz: float = 20.0,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    netlist = render_teaching_hb_netlist(
        input_dbm, frequency_ghz=frequency_ghz, harmonics=harmonics, vbias_v=vbias_v,
        ldd_nh=ldd_nh, cblock_ff=cblock_ff, rdamp_ohm=rdamp_ohm,
        sp_intervals=sp_intervals, sp_start_ghz=sp_start_ghz,
        sp_stop_ghz=sp_stop_ghz,
    )
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before teaching HB")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist.encode("ascii"))
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"teach_hb_{uuid4().hex[:12]}")
    payload = {
        "schema_version": 1,
        "status": "unknown",
        "simulation_status": "unknown",
        "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": output_dir.name,
        "scope": "one-point MOS1 teaching HB diagnostic; not a foundry LNA result",
        "analysis": ["dc", "sp", "noise", "hb"],
        "parameters": {"input_dbm": input_dbm, "frequency_ghz": frequency_ghz,
                       "harmonics": harmonics, "vbias_v": vbias_v,
                       **({"ldd_nh": ldd_nh, "cblock_ff": cblock_ff,
                           "rdamp_ohm": rdamp_ohm} if rdamp_ohm is not None else {}),
                       **({"sp_intervals": sp_intervals,
                           "sp_start_ghz": sp_start_ghz,
                           "sp_stop_ghz": sp_stop_ghz}
                          if (sp_intervals, sp_start_ghz, sp_stop_ghz) != (199, 0.1, 20.0) else {})},
        "host_available_gib_before": available,
    }

    def finish(status: str, *, simulation_status: str = "unknown", error: str | None = None) -> dict:
        payload["status"] = status
        payload["simulation_status"] = simulation_status
        if simulation_status == "ok":
            payload["source"] = "cadence_spectre"
        if error:
            payload["error"] = error
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        filenames = {
            "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
            "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
            "hb_fd_raw": "hb.fd.pss_hb", "hb_fi_raw": "hb.fi.pss_hb",
            "hb_td_raw": "hb.td.pss_hb", "stdout": "spectre.stdout.log",
            "stderr": "spectre.stderr.log",
        }
        write_evidence_manifest(output_dir, {key: name for key, name in filenames.items()
                                             if (output_dir / name).is_file()})
        return payload

    created = runner.ensure_remote_dir(remote_dir)
    if not created.ok:
        return finish("mkdir_failed", error=f"returncode={created.returncode}")
    uploaded = runner.upload(output_dir / "netlist.scs", str(PurePosixPath(remote_dir) / "netlist.scs"))
    if not uploaded.ok:
        return finish("upload_failed", error=f"returncode={uploaded.returncode}")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "-format", "psfascii", "-raw", "psf",
         "+log", "spectre.log", "netlist.scs"], cwd=remote_dir,
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
    for name in _RAW:
        downloaded = runner.download(str(PurePosixPath(remote_dir) / "psf" / name), output_dir / name)
        if not downloaded.ok:
            return finish("raw_download_failed", simulation_status="ok",
                          error=f"file={name} returncode={downloaded.returncode}")
    warning_count = re.search(r"spectre completes with 0 errors,\s*(\d+) warnings", log)
    if not warning_count:
        return finish("log_summary_missing", simulation_status="ok")
    if int(warning_count[1]) > 0:
        codes = sorted(set(re.findall(r"\b(?:CMI|SPECTRE)-\d+\b", log)))
        payload["quality_flags"] = ["spectre_warnings", *codes]
        return finish("model_validity_warning", simulation_status="ok")
    try:
        fundamental = extract_hb_fundamental_power(
            output_dir / "hb.fd.pss_hb", output_node="out", fundamental_hz=frequency_ghz * 1e9,
        )
        s21_db = extract_sp_s21_at_frequency(output_dir / "sp.sp", frequency_ghz * 1e9)
    except (OSError, ValueError) as exc:
        return finish("result_parse_failed", simulation_status="ok", error=type(exc).__name__)
    gain_db = fundamental["output_power_dbm"] - input_dbm
    payload["metrics"] = {
        **fundamental,
        "input_available_power_dbm": input_dbm,
        "power_gain_db": gain_db,
        "small_signal_s21_db": s21_db,
        "hb_minus_s21_db": gain_db - s21_db,
    }
    payload["reference_planes"] = {"input": "PORT1_available_power", "output": "PORT2_50ohm_load",
                                   "z0_ohm": 50.0}
    return finish("hb_fundamental_extracted", simulation_status="ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Cadence HB point for the public MOS1 teaching LNA")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_hb")
    parser.add_argument("--input-dbm", type=float, required=True)
    parser.add_argument("--frequency-ghz", type=float, default=10.0)
    parser.add_argument("--harmonics", type=int, default=7)
    parser.add_argument("--vbias-v", type=float, default=0.65)
    parser.add_argument("--ldd-nh", type=float, default=2.0)
    parser.add_argument("--cblock-ff", type=float, default=5000.0)
    parser.add_argument("--rdamp-ohm", type=float)
    parser.add_argument("--sp-intervals", type=int, default=199)
    parser.add_argument("--sp-start-ghz", type=float, default=0.1)
    parser.add_argument("--sp-stop-ghz", type=float, default=20.0)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_hb(args.config, output_dir, input_dbm=args.input_dbm,
                                  frequency_ghz=args.frequency_ghz, harmonics=args.harmonics,
                                  vbias_v=args.vbias_v, ldd_nh=args.ldd_nh,
                                  cblock_ff=args.cblock_ff, rdamp_ohm=args.rdamp_ohm,
                                  sp_intervals=args.sp_intervals,
                                  sp_start_ghz=args.sp_start_ghz,
                                  sp_stop_ghz=args.sp_stop_ghz)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0 if payload["status"] == "hb_fundamental_extracted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
