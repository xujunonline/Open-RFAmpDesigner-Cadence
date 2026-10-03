from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.hb_metrics import extract_hb_fundamental_power, extract_sp_s21_at_frequency
from orfadc.experiments.run_teaching_hb import render_teaching_hb_netlist


_PORT1 = re.compile(
    r"^PORT1 \(in 0\) port r=50 num=1 type=sine dbm=([-+0-9.eE]+) freq=([-+0-9.eE]+)$",
    re.MULTILINE,
)
_HB = re.compile(r"^hb hb fundfreqs=\[([-+0-9.eE]+)\] maxharms=\[(\d+)\] annotate=status$", re.MULTILINE)
_BIAS = re.compile(r"^parameters VDD=1\.2 VBIAS=([-+0-9.eE]+) WMOS=300u LMOS=100n ", re.MULTILINE)
_RAW = {"netlist": "netlist.scs", "spectre_log": "spectre.log", "sp_raw": "sp.sp",
        "hb_fd_raw": "hb.fd.pss_hb", "hb_fi_raw": "hb.fi.pss_hb", "hb_td_raw": "hb.td.pss_hb"}


def _close(actual: object, expected: float, label: str) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError(f"teaching HB {label} disagrees with archived raw data")


def audit_teaching_hb(run_dir: Path) -> dict:
    """Independently recompute one warning-free MOS1 HB point from original files."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("teaching HB run directory is missing or symlinked")
    result = read_evidenced_metrics(run_dir)
    parameters = result.get("parameters")
    if (
        result.get("status") != "hb_fundamental_extracted"
        or result.get("simulation_status") != "ok"
        or result.get("source") != "cadence_spectre"
        or result.get("circuit_class") != "teaching_mos1_common_source"
        or result.get("model_kind") != "teaching_model"
        or result.get("not_lna_result") is not True
        or result.get("spec_pass") is not None
        or result.get("run_id") != run_dir.name
        or not isinstance(parameters, dict)
    ):
        raise ValueError("archive is not a successful teaching MOS1 HB point")
    manifest_path = run_dir / "evidence_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("symlinked teaching HB manifest is not accepted")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict) or any(
        not isinstance(entries.get(key), dict) or entries[key].get("path") != name
        for key, name in _RAW.items()
    ):
        raise ValueError("teaching HB raw files are not all in the verified manifest")
    netlist = (run_dir / "netlist.scs").read_text(encoding="ascii")
    if "not foundry data" not in netlist or "model n_teach mos1" not in netlist:
        raise ValueError("teaching HB netlist has no identified public MOS1 model")
    if "dcOpInfo info what=oppoint where=rawfile" in netlist and (
        not isinstance(entries.get("op_raw"), dict)
        or entries["op_raw"].get("path") != "dcOpInfo.info"
    ):
        raise ValueError("teaching HB working point is missing from evidence")
    ports = _PORT1.findall(netlist)
    hbs = _HB.findall(netlist)
    biases = _BIAS.findall(netlist)
    if (
        len(ports) != 1 or len(hbs) != 1 or len(biases) != 1
        or len(re.findall(r"^PORT2 \(out 0\) port r=50 num=2 type=dc$", netlist, re.MULTILINE)) != 1
    ):
        raise ValueError("teaching HB source/load reference planes are ambiguous")
    frequency_hz = float(ports[0][1])
    power_dbm = float(ports[0][0])
    harmonics = int(hbs[0][1])
    recorded_bias = parameters.get("vbias_v")
    if recorded_bias is None and "dcOpInfo info what=oppoint where=rawfile" not in netlist:
        recorded_bias = 0.65
    for key, expected in (
        ("input_dbm", power_dbm), ("frequency_ghz", frequency_hz / 1e9),
        ("harmonics", harmonics),
    ):
        _close(parameters.get(key), expected, f"parameter {key}")
    _close(recorded_bias, float(biases[0]), "parameter vbias_v")
    _close(float(hbs[0][0]), frequency_hz, "HB tone")
    if "rdamp_ohm" in parameters:
        expected_netlist = render_teaching_hb_netlist(
            parameters["input_dbm"], frequency_ghz=parameters["frequency_ghz"],
            harmonics=parameters["harmonics"], vbias_v=parameters["vbias_v"],
            ldd_nh=parameters["ldd_nh"], cblock_ff=parameters["cblock_ff"],
            rdamp_ohm=parameters["rdamp_ohm"],
            sp_intervals=parameters.get("sp_intervals", 199),
            sp_start_ghz=parameters.get("sp_start_ghz", 0.1),
            sp_stop_ghz=parameters.get("sp_stop_ghz", 20.0),
        )
        if netlist.replace("\r\n", "\n") != expected_netlist.replace("\r\n", "\n"):
            raise ValueError("matched teaching HB netlist differs from the recorded parameters")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*0 warnings", log):
        raise ValueError("teaching HB Spectre log does not establish zero warnings")
    fundamental = extract_hb_fundamental_power(
        run_dir / "hb.fd.pss_hb", output_node="out", fundamental_hz=frequency_hz,
    )
    s21_db = extract_sp_s21_at_frequency(run_dir / "sp.sp", frequency_hz)
    expected_metrics = {
        **fundamental, "input_available_power_dbm": power_dbm,
        "power_gain_db": fundamental["output_power_dbm"] - power_dbm,
        "small_signal_s21_db": s21_db,
        "hb_minus_s21_db": fundamental["output_power_dbm"] - power_dbm - s21_db,
    }
    metrics = result.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(expected_metrics):
        raise ValueError("teaching HB metrics fields disagree with the raw extractor")
    for key, expected in expected_metrics.items():
        _close(metrics[key], expected, f"metric {key}")
    if result.get("reference_planes") != {
        "input": "PORT1_available_power", "output": "PORT2_50ohm_load", "z0_ohm": 50.0,
    }:
        raise ValueError("teaching HB recorded reference planes are wrong")
    return {"status": "verified", "run_id": run_dir.name, "metrics": expected_metrics,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a Cadence MOS1 teaching HB point")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        report = audit_teaching_hb(args.run_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"teaching HB archive audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} run_id={report['run_id']}")
    print(f"metrics={report['metrics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
