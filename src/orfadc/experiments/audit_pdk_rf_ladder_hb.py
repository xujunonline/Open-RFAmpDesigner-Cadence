from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.hb_metrics import (
    extract_hb_differential_fundamental_power, extract_hb_input_available_power,
    extract_sp_s21_at_frequency,
)
from orfadc.cadence.psfascii_reader import (
    parse_complex_trace, parse_dc_values, parse_scalar_trace, parse_struct_values,
)
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_input_ladder import audit_pdk_rf_input_ladder
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_pdk_rf_ladder_hb import render_pdk_rf_ladder_hb
from orfadc.metric_contract import validate_metrics_payload


_OP_FIELDS = ("ids", "vgs", "vds", "vdsat", "vth", "gm", "gds", "region")
_COLUMNS = (
    "input_available_power_dbm", "output_power_dbm", "power_gain_db",
    "small_signal_s21_db", "hb_minus_s21_db", "load_current_relative_error",
)
_ARTIFACTS = {
    "run_status": "run_status.json", "source": "ladder_input.scs",
    "netlist": "netlist.scs", "remote_netlist": "remote_netlist.scs",
    "ade": "ade_e.scs", "remote_ade": "remote_ade_e.scs",
    "spectre_log": "spectre.log", "stdout": "stdout.log", "stderr": "stderr.log",
    "dc": "dcOp.dc", "op": "dcOpInfo.info", "sp": "sp.sp",
    "noise": "sp.noise.sp", "hb_fd": "hb.fd.pss_hb",
    "hb_fi": "hb.fi.pss_hb", "hb_td": "hb.td.pss_hb",
    "touchstone": "ladder_hb.s2p",
}


def extract_pdk_rf_ladder_hb(run_dir: Path, ladder_dir: Path) -> dict:
    for path in (run_dir, ladder_dir):
        _require_private_path(path)
        if not path.is_dir() or path.is_symlink():
            raise ValueError("ladder HB source directory is missing or unsafe")
    audit_pdk_rf_input_ladder(ladder_dir)
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    source = (run_dir / "ladder_input.scs").read_bytes()
    derived = (run_dir / "netlist.scs").read_bytes()
    companion = (run_dir / "ade_e.scs").read_bytes()
    drive = status.get("input_dbm")
    harmonics = status.get("harmonics")
    if (
        status.get("status") != "simulation_recorded"
        or status.get("run_id") != run_dir.name
        or status.get("ladder_run_id") != ladder_dir.name
        or type(drive) is not int or not -100 <= drive <= 0
        or type(harmonics) is not int or harmonics != 7
        or source != (ladder_dir / "netlist.scs").read_bytes()
        or companion != (ladder_dir / "ade_e.scs").read_bytes()
        or derived != render_pdk_rf_ladder_hb(source, drive, harmonics=harmonics)
        or (run_dir / "remote_netlist.scs").read_bytes() != derived
        or (run_dir / "remote_ade_e.scs").read_bytes() != companion
        or status.get("source_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derived).hexdigest()
        or status.get("ladder_manifest_sha256") != hashlib.sha256(
            (ladder_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest()
        or status.get("spectre_returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("pdk_write") is not False
        or status.get("user_oa_write") is not False
        or status.get("physical_qualification") is not False
        or status.get("cdf_callback_validated") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or not isinstance(status.get("downloads"), dict)
        or any(value is not True for value in status["downloads"].values())
    ):
        raise ValueError("ladder HB provenance or remote source differs")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    loaded = re.findall(r"^Reading file:\s+(/[^\s]+/netlist\.scs)$", log, re.MULTILINE)
    if (
        len(loaded) != 1
        or not re.search(r"/rf_ladder_hb_[0-9a-f]{12}/netlist\.scs$", loaded[0])
        or len(re.findall(r"^Reading file:\s+" + re.escape(loaded[0].rsplit("/", 1)[0])
                          + r"/ade_e\.scs$", log, re.MULTILINE)) != 1
        or not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or not re.search(r"Total time required for hb analysis `hb'", log)
    ):
        raise ValueError("ladder HB Spectre log is incomplete or points to a different source")
    for name, analysis_type in (
        ("hb.fd.pss_hb", "fd.pss_hb"), ("hb.fi.pss_hb", "fi.pss_hb"),
        ("hb.td.pss_hb", "td.pss_hb"),
    ):
        header = (run_dir / name).read_text(encoding="utf-8", errors="replace").split("TYPE", 1)[0]
        if f'"analysis type" "{analysis_type}"' not in header or '"analysis name" "hb"' not in header:
            raise ValueError("ladder HB raw analysis type differs")
        if name == "hb.fd.pss_hb" and not re.search(r'^"harms"\s+7$', header, re.MULTILINE):
            raise ValueError("ladder HB harmonic count differs")
    touchstone = parse_touchstone_2port(run_dir / "ladder_hb.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("ladder HB Touchstone reference planes differ")
    max_s_delta = max_noise_delta = max_touchstone_delta = 0.0
    frequency = None
    for signal in ("s11", "s21", "s12", "s22"):
        grid, current = parse_complex_trace(run_dir / "sp.sp", signal)
        baseline_grid, previous = parse_complex_trace(ladder_dir / "sp.sp", signal)
        if grid != baseline_grid or (frequency is not None and grid != frequency):
            raise ValueError("ladder HB SP frequency grid differs from its candidate")
        frequency = grid
        for hz, measured, original, touch in zip(grid, current, previous, touchstone, strict=True):
            if not math.isclose(hz, touch["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("ladder HB Touchstone grid differs")
            max_s_delta = max(max_s_delta, abs(measured - original))
            max_touchstone_delta = max(
                max_touchstone_delta,
                abs(measured - complex(touch[f"{signal}_real"], touch[f"{signal}_imag"])),
            )
    if frequency is None or len(frequency) != 161 or max_s_delta > 1e-8 or max_touchstone_delta > 1e-8:
        raise ValueError("ladder HB small-signal S differs from its archived candidate")
    for signal in ("NF", "NFmin", "F", "Fmin"):
        grid, current = parse_scalar_trace(run_dir / "sp.noise.sp", signal)
        baseline_grid, previous = parse_scalar_trace(ladder_dir / "sp.noise.sp", signal)
        if grid != frequency or baseline_grid != frequency:
            raise ValueError("ladder HB noise grid differs from SP")
        max_noise_delta = max(max_noise_delta, *(
            abs(a - b) for a, b in zip(current, previous, strict=True)
        ))
    if max_noise_delta > 1e-6:
        raise ValueError("ladder HB noise differs from its archived candidate")
    current_dc = parse_dc_values(run_dir / "dcOp.dc")
    baseline_dc = parse_dc_values(ladder_dir / "dcOp.dc")
    if not math.isclose(current_dc["VDD_SRC:p"], baseline_dc["VDD_SRC:p"], abs_tol=1e-9):
        raise ValueError("ladder HB supply current differs")
    for index in range(1, 7):
        current_op = parse_struct_values(run_dir / "dcOpInfo.info", instance=f"M{index}", struct_type="bsim4")
        baseline_op = parse_struct_values(ladder_dir / "dcOpInfo.info", instance=f"M{index}", struct_type="bsim4")
        if any(
            field not in current_op or field not in baseline_op
            or not math.isclose(current_op[field], baseline_op[field], rel_tol=1e-8, abs_tol=1e-12)
            for field in _OP_FIELDS
        ):
            raise ValueError("ladder HB device operating point differs")
    input_dbm = extract_hb_input_available_power(
        run_dir / "hb.fd.pss_hb", fundamental_hz=10e9, input_node="match_out",
    )
    hb = extract_hb_differential_fundamental_power(run_dir / "hb.fd.pss_hb", fundamental_hz=10e9)
    s21_db = extract_sp_s21_at_frequency(run_dir / "sp.sp", 10e9)
    gain_db = hb["output_power_dbm"] - input_dbm
    if not math.isclose(input_dbm, drive, abs_tol=0.01) or (
        drive <= -50 and abs(gain_db - s21_db) > 0.01
    ):
        raise ValueError("ladder HB drive or low-drive gain disagrees with same-run SP")
    metrics = {
        "input_available_power_dbm": input_dbm,
        "output_power_dbm": hb["output_power_dbm"],
        "power_gain_db": gain_db,
        "small_signal_s21_db": s21_db,
        "hb_minus_s21_db": gain_db - s21_db,
        "load_current_relative_error": hb["load_current_relative_error"],
        "vout_diff_peak_v": hb["vout_diff_peak_v"],
        "iout_peak_a": hb["iout_peak_a"],
        "supply_current_ma": -current_dc["VDD_SRC:p"] * 1e3,
    }
    payload = {
        "schema_version": 1,
        "status": ("ladder_hb_low_drive_verified_with_warnings" if drive <= -50
                   else "ladder_hb_drive_probe_verified_with_warnings"),
        "simulation_status": "ok", "source": "cadence_spectre",
        "circuit_class": "pdk_rf_ideal_input_ladder_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": ("one OA-netlist-derived ideal-input-ladder HB point; no compression or qualified LNA claim"
                  if drive <= -50 else
                  "one OA-netlist-derived ideal-input-ladder HB drive point; no standalone compression or qualified LNA claim"),
        "analysis": ["dc", "op_info", "sp", "noise", "hb"],
        "frequency_band_ghz": {"low": 8.0, "high": 12.0}, "points": len(frequency),
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "input_drive_dbm": drive, "harmonics": harmonics,
        "ladder_run_id": ladder_dir.name,
        "ladder_manifest_sha256": status["ladder_manifest_sha256"],
        "metrics": metrics,
        "maximum_ladder_complex_s_delta": max_s_delta,
        "maximum_ladder_noise_delta": max_noise_delta,
        "maximum_touchstone_complex_delta": max_touchstone_delta,
        "physical_qualification": False, "cdf_callback_validated": False,
        "spectre_warning_count": 5,
    }
    validate_metrics_payload(payload)
    return payload


def finalize_pdk_rf_ladder_hb(run_dir: Path, ladder_dir: Path) -> dict:
    payload = extract_pdk_rf_ladder_hb(run_dir, ladder_dir)
    fields = {key: payload["metrics"][key] for key in _COLUMNS}
    with (run_dir / "hb_fundamental.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerow(fields)
    write_json(run_dir / "metrics.json", payload)
    write_evidence_manifest(run_dir, {
        **_ARTIFACTS, "metrics": "metrics.json", "hb_summary": "hb_fundamental.csv",
    })
    return audit_pdk_rf_ladder_hb(run_dir, ladder_dir)


def audit_pdk_rf_ladder_hb(run_dir: Path, ladder_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    entries = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8")).get("artifacts", {})
    required = {**_ARTIFACTS, "metrics": "metrics.json", "hb_summary": "hb_fundamental.csv"}
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in required.items()):
        raise ValueError("ladder HB evidence lacks required raw artifacts")
    rebuilt = extract_pdk_rf_ladder_hb(run_dir, ladder_dir)
    if saved != rebuilt:
        raise ValueError("ladder HB metrics differ from raw Spectre archive")
    with (run_dir / "hb_fundamental.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("ladder HB summary columns differ")
        rows = list(reader)
    if len(rows) != 1 or any(
        not math.isclose(float(rows[0][key]), rebuilt["metrics"][key], rel_tol=1e-10, abs_tol=1e-12)
        for key in _COLUMNS
    ):
        raise ValueError("ladder HB summary differs from raw Spectre metrics")
    return {"status": "verified_diagnostic_only", "run_id": run_dir.name,
            "hb_minus_s21_db": rebuilt["metrics"]["hb_minus_s21_db"],
            "not_lna_result": True, "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit an RF input-ladder HB point")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--ladder-dir", type=Path, required=True)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    result = (audit_pdk_rf_ladder_hb if args.audit_only else finalize_pdk_rf_ladder_hb)(
        args.run_dir, args.ladder_dir,
    )
    print(f"status={result['status']} hb_minus_s21_db={result['hb_minus_s21_db']:.6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
