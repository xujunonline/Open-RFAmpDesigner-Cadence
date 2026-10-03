from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_dc_values, parse_struct_values
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.experiments.extract_active_oa import extract_active_oa
from orfadc.experiments.run_teaching_lna import render_teaching_lna_netlist


_RAW_FILES = {
    "dc_raw": "dcOp.dc", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
    "touchstone": "teaching_mos1_lna.s2p", "waveforms": "waveforms.csv",
}


def _validate_damping(source: str, design: dict) -> None:
    matches = re.findall(r"^RDAMP \(vdd drain\) resistor r=([0-9.eE+-]+)\r?$", source, re.MULTILINE)
    named_lines = re.findall(r"^RDAMP\b", source, re.MULTILINE)
    stated = design.get("rdamp_ohm")
    if stated is None and not named_lines:
        return
    if len(named_lines) != 1 or len(matches) != 1 or type(stated) not in {int, float} or not math.isfinite(stated):
        raise ValueError("teaching damping resistor and metadata disagree")
    actual = float(matches[0])
    if not 100 <= actual <= 10000:
        raise ValueError("teaching damping resistor is outside its policy range")
    _close(stated, actual, "recorded RDAMP", tolerance=1e-12)


def _close(actual: object, expected: float, label: str, *, tolerance: float = 1e-8) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=tolerance, abs_tol=tolerance
    ):
        raise ValueError(f"teaching LNA {label} disagrees with raw simulation data")


def audit_teaching_lna(run_dir: Path) -> dict:
    """Read-only recomputation of an archived, explicitly non-PDK MOS1 run."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("teaching run directory must exist and not be a symlink")
    result = read_evidenced_metrics(run_dir)
    design = result.get("design_parameters", {})
    topology = design.get("topology", "common_source") if isinstance(design, dict) else None
    if (
        result.get("status") != "ok_with_warnings"
        or result.get("simulation_status") != "ok"
        or result.get("source") != "cadence_spectre"
        or topology not in {"common_source", "cascode"}
        or result.get("source_run_kind") != (
            "teaching_mos1_cascode_direct_spectre" if topology == "cascode"
            else "teaching_mos1_direct_spectre"
        )
        or result.get("circuit_class") != (
            "teaching_mos1_cascode" if topology == "cascode"
            else "teaching_mos1_common_source"
        )
        or result.get("model_kind") != "teaching_model"
        or result.get("not_lna_result") is not True
        or result.get("spec_pass") is not None
        or result.get("run_id") != run_dir.name
        or result.get("analysis") not in (["dc", "sp", "noise"], ["dc", "op_info", "sp", "noise"])
    ):
        raise ValueError("archive is not a successful teaching MOS1 diagnostic")
    manifest_path = run_dir / "evidence_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("symlinked teaching manifest is not accepted")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict) or any(
        not isinstance(entries.get(key), dict) or entries[key].get("path") != name
        for key, name in _RAW_FILES.items()
    ):
        raise ValueError("teaching raw outputs are not all in the verified manifest")
    netlist_bytes = (run_dir / "netlist.scs").read_bytes()
    if hashlib.sha256(netlist_bytes).hexdigest() != result.get("netlist_sha256"):
        raise ValueError("teaching netlist hash disagrees with run metadata")
    source = netlist_bytes.decode("ascii")
    if "model n_teach mos1" not in source or "not foundry data" not in source:
        raise ValueError("archived teaching model is not identifiable")
    if "dcOpInfo info what=oppoint where=rawfile" in source:
        op_entry = entries.get("op_raw")
        if not isinstance(op_entry, dict) or op_entry.get("path") != "dcOpInfo.info":
            raise ValueError("teaching operating-point raw file is missing from evidence")
    bias_match = re.search(r"^parameters VDD=1\.2 VBIAS=([0-9.]+) WMOS=([0-9.]+)u LMOS=100n\b", source, re.MULTILINE)
    if bias_match is None:
        raise ValueError("archived teaching bias is not identifiable")
    vbias_v = result.get("design_parameters", {}).get("vbias_v", 0.65)
    _close(vbias_v, float(bias_match[1]), "recorded VBIAS", tolerance=1e-12)
    wmos_um = result.get("design_parameters", {}).get("wmos_um", 300.0)
    _close(wmos_um, float(bias_match[2]), "recorded WMOS", tolerance=1e-12)
    if not 100 <= wmos_um <= 500:
        raise ValueError("teaching MOS width is outside the characterized policy range")
    lgs_match = re.search(r"\bLGS=([0-9.]+)n\b", source)
    lss_match = re.search(r"\bLSS=([0-9.]+)p\b", source)
    ldd_match = re.search(r"\bLDD=([0-9.]+)n\b", source)
    capacitor_match = re.search(r"^CBLOCK \(drain out\) capacitor c=([0-9.]+)([fp])$", source, re.MULTILINE)
    if any(match is None for match in (lgs_match, lss_match, ldd_match, capacitor_match)):
        raise ValueError("archived teaching matching values are not identifiable")
    _validate_damping(source, design)
    if (design.get("rdamp_ohm") is not None or topology == "cascode") and netlist_bytes != render_teaching_lna_netlist(**design):
        raise ValueError("teaching netlist differs from the controlled topology template")
    sweep_match = re.search(
        r"^sp sp start=(100M|[0-9.eE+-]+G) stop=([0-9.eE+-]+G) lin=(\d+) ports=\[PORT1 PORT2\]",
        source, re.MULTILINE,
    )
    if sweep_match is None:
        raise ValueError("teaching SP sweep is not identifiable")
    start_ghz = 0.1 if sweep_match[1] == "100M" else float(sweep_match[1][:-1])
    stop_ghz = float(sweep_match[2][:-1])
    intervals = int(sweep_match[3])
    if (
        not 40 <= intervals <= 999
        or not 0.1 <= start_ghz < stop_ghz <= 20.0
        or (stop_ghz - start_ghz) / intervals > 0.10001
        or design.get("sp_intervals", 199) != intervals
        or design.get("sp_start_ghz", 0.1) != start_ghz
        or design.get("sp_stop_ghz", 20.0) != stop_ghz
    ):
        raise ValueError("teaching SP sweep and metadata disagree")
    _close(design.get("lgs_nh", 1.0), float(lgs_match[1]), "recorded LGS", tolerance=1e-12)
    _close(design.get("lss_ph", 240.0), float(lss_match[1]), "recorded LSS", tolerance=1e-12)
    _close(design.get("ldd_nh", 2.0), float(ldd_match[1]), "recorded LDD", tolerance=1e-12)
    capacitance_ff = float(capacitor_match[1]) * (1000 if capacitor_match[2] == "p" else 1)
    _close(design.get("cblock_ff", 5000.0), capacitance_ff, "recorded CBLOCK", tolerance=1e-12)
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*0 warnings", log):
        raise ValueError("teaching Spectre log does not establish zero warnings")
    band = result.get("frequency_band_ghz")
    if band != {"low": 8.0, "high": 12.0}:
        raise ValueError("teaching run does not use the 8-12 GHz diagnostic band")
    rows, recomputed = extract_active_oa(
        run_dir, run_id=run_dir.name, supply_voltage_v=1.2,
        supply_current_signal="VDD_SRC:p", low_ghz=8.0, high_ghz=12.0,
        source_run_kind="teaching_mos1_direct_spectre",
    )
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("teaching metrics object is missing")
    for key, value in recomputed["metrics"].items():
        _close(metrics.get(key), value, f"metric {key}")
    stability = result.get("stability")
    if not isinstance(stability, dict):
        raise ValueError("teaching stability object is missing")
    for key, value in recomputed["stability"].items():
        if type(value) is bool:
            if stability.get(key) is not value:
                raise ValueError(f"teaching stability {key} disagrees with raw S parameters")
        else:
            _close(stability.get(key), value, f"stability {key}")
    if result.get("points") != len(rows):
        raise ValueError("teaching point count disagrees with raw data")
    if len(rows) != intervals + 1:
        raise ValueError("teaching SP point count disagrees with the netlist")
    for actual, expected in ((rows[0]["freq_ghz"], start_ghz),
                             (rows[-1]["freq_ghz"], stop_ghz)):
        _close(actual, expected, "SP sweep endpoint", tolerance=1e-8)
    csv_path = run_dir / "waveforms.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked teaching waveform CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(rows):
        raise ValueError("teaching waveform CSV point count disagrees with raw data")
    for index, (saved, fresh) in enumerate(zip(csv_rows, rows, strict=True)):
        for key, expected in fresh.items():
            try:
                value = float(saved[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"teaching CSV row {index} has invalid {key}") from exc
            _close(value, expected, f"CSV row {index} {key}")
    touchstone = parse_touchstone_2port(run_dir / "teaching_mos1_lna.s2p")
    if len(touchstone) != len(rows) or any(row["reference_ohm"] != 50 for row in touchstone):
        raise ValueError("teaching Touchstone port or sweep contract failed")
    maximum_complex_delta = 0.0
    for name in ("s11", "s21", "s12", "s22"):
        frequencies, values = parse_complex_trace(run_dir / "sp.sp", name)
        for index, (frequency, value, saved) in enumerate(zip(frequencies, values, touchstone, strict=True)):
            _close(saved["freq_hz"], frequency, f"Touchstone frequency {index}", tolerance=1e-7)
            delta = abs(complex(saved[f"{name}_real"], saved[f"{name}_imag"]) - value)
            maximum_complex_delta = max(maximum_complex_delta, delta)
    if maximum_complex_delta > 1e-8:
        raise ValueError("teaching Touchstone and PSFASCII S parameters disagree")
    dc = parse_dc_values(run_dir / "dcOp.dc")
    _close(dc.get("gate"), vbias_v, "gate DC bias", tolerance=1e-3)
    if dc.get("VDD_SRC:p", 0) >= 0:
        raise ValueError("teaching supply current does not flow out of VDD")
    device_op = None
    cascode_op = None
    if "dcOpInfo info what=oppoint where=rawfile" in source:
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance="M1", struct_type="mos1")
        device_op = {key: op[key] for key in ("ids", "vgs", "vds", "vth", "vdsat", "gm", "gds", "cgs", "cgd")}
        if any(not math.isfinite(value) for value in device_op.values()):
            raise ValueError("teaching MOS1 operating point contains nonfinite values")
        if any(device_op[key] < 0 for key in ("ids", "gm", "gds", "cgs", "cgd")):
            raise ValueError("teaching MOS1 operating point contains negative device quantities")
        _close(device_op["ids"], -dc["VDD_SRC:p"], "MOS drain current", tolerance=1e-8)
        _close(device_op["vgs"], dc["gate"] - dc["source"], "MOS VGS", tolerance=1e-8)
        _close(device_op["vds"], dc["cas" if topology == "cascode" else "drain"] - dc["source"],
               "MOS VDS", tolerance=1e-8)
        if device_op["vds"] < device_op["vdsat"]:
            raise ValueError("teaching MOS1 operating point lacks VDS headroom")
        if topology == "cascode":
            m2 = parse_struct_values(run_dir / "dcOpInfo.info", instance="M2", struct_type="mos1")
            cascode_op = {key: m2[key] for key in ("ids", "vgs", "vds", "vth", "vdsat", "gm", "gds", "cgs", "cgd")}
            if any(not math.isfinite(value) for value in cascode_op.values()):
                raise ValueError("teaching cascode operating point contains nonfinite values")
            if any(cascode_op[key] < 0 for key in ("ids", "gm", "gds", "cgs", "cgd")):
                raise ValueError("teaching cascode operating point contains negative device quantities")
            _close(dc.get("casgate"), design["vcas_v"], "cascode gate DC bias", tolerance=1e-3)
            _close(cascode_op["ids"], device_op["ids"], "cascode drain current", tolerance=1e-3)
            _close(cascode_op["vgs"], dc["casgate"] - dc["cas"], "cascode VGS", tolerance=1e-8)
            _close(cascode_op["vds"], dc["drain"] - dc["cas"], "cascode VDS", tolerance=1e-8)
            if cascode_op["vds"] < cascode_op["vdsat"]:
                raise ValueError("teaching cascode M2 lacks VDS headroom")
    report = {
        "status": "verified",
        "run_id": run_dir.name,
        "points_verified": len(rows),
        "max_touchstone_psfascii_complex_delta": maximum_complex_delta,
        "metrics": recomputed["metrics"],
        "stability": recomputed["stability"],
        "not_lna_result": True,
    }
    if device_op is not None:
        report["device_op"] = device_op
    if cascode_op is not None:
        report["cascode_op"] = cascode_op
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a Cadence MOS1 teaching LNA archive")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        report = audit_teaching_lna(args.run_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"teaching archive audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points={report['points_verified']} run_id={report['run_id']}")
    print(f"metrics={report['metrics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
