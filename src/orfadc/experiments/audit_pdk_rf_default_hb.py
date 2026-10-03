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
from orfadc.cadence.rf_low_drive_netlist import render_rf_hb_netlist
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_three_stage import (
    _check_creation, audit_pdk_rf_default_three_stage, default_rf_geometry,
)
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ARTIFACTS = {
    "metrics": "metrics.json", "hb_summary": "hb_fundamental.csv",
    "run_status": "run_status.json", "runner": "runner.py",
    "oa_source": "oa_input.scs", "netlist": "netlist.scs",
    "remote_netlist": "remote_netlist.scs", "ade_companion": "ade_e.scs",
    "remote_companion": "remote_ade_e.scs", "spectre_log": "spectre.log",
    "stdout": "stdout.log", "stderr": "stderr.log", "dc_raw": "dcOp.dc",
    "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
    "hb_fd_raw": "hb.fd.pss_hb", "hb_fi_raw": "hb.fi.pss_hb",
    "hb_td_raw": "hb.td.pss_hb", "touchstone": "rf_default_hb_probe.s2p",
}
_HB_COLUMNS = (
    "input_available_power_dbm", "output_power_dbm", "power_gain_db",
    "small_signal_s21_db", "hb_minus_s21_db", "load_current_relative_error",
)
_OP_FIELDS = ("ids", "vgs", "vds", "vdsat", "vth", "gm", "gds", "region")


def extract_pdk_rf_default_hb(
    run_dir: Path, create_dir: Path, baseline_dir: Path,
) -> dict:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("RF low-drive HB archive must be an ordinary directory")
    if audit_pdk_rf_default_three_stage(baseline_dir, create_dir)["status"] != "verified":
        raise ValueError("RF default SP baseline is not verified")
    baseline = read_evidenced_metrics(baseline_dir)
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    source = (run_dir / "oa_input.scs").read_bytes()
    derived = (run_dir / "netlist.scs").read_bytes()
    companion = (run_dir / "ade_e.scs").read_bytes()
    oa_hash = _check_creation(create_dir, source, companion)
    power_match = re.search(
        rb"^PORT1 \(in 0\) port r=50 num=1 type=sine dbm=(-?[0-9]+) freq=10G$",
        derived, re.MULTILINE,
    )
    if power_match is None:
        raise ValueError("RF HB input drive is absent from the derived netlist")
    drive_dbm = int(power_match[1])
    harmonic_match = re.search(
        rb"^hb hb fundfreqs=\[10G\] maxharms=\[([0-9]+)\] annotate=status$",
        derived, re.MULTILINE,
    )
    if harmonic_match is None:
        raise ValueError("RF HB harmonic setting is absent from the derived netlist")
    harmonics = int(harmonic_match[1])
    legacy_low_drive = status.get("probe_kind") == "oa_derived_low_drive_hb"
    if (
        source != (baseline_dir / "netlist.scs").read_bytes()
        or derived != render_rf_hb_netlist(source, drive_dbm, harmonics=harmonics)
        or derived != (run_dir / "remote_netlist.scs").read_bytes()
        or companion != (run_dir / "remote_ade_e.scs").read_bytes()
        or status.get("status") != "simulation_ok"
        or status.get("source") != "cadence_spectre"
        or status.get("spectre_returncode") != 0
        or status.get("oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derived).hexdigest()
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or status.get("physical_qualification") is not False
        or status.get("cdf_callback_validated") is not False
        or status.get("passive_model_kind") != "ideal_lumped_and_mutual_inductor"
        or (legacy_low_drive and (drive_dbm != -70 or "input_dbm" in status))
        or (not legacy_low_drive and (
            status.get("probe_kind") != "oa_derived_hb_drive"
            or status.get("input_dbm") != drive_dbm
        ))
        or (harmonics == 7 and "harmonics" in status)
        or (harmonics != 7 and status.get("harmonics") != harmonics)
        or type(status.get("host_available_gib_before")) not in {int, float}
        or status["host_available_gib_before"] < 2.66
        or status.get("downloads") != {name: True for name in (
            "spectre.log", "dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp",
            "hb.fd.pss_hb", "hb.fi.pss_hb", "hb.td.pss_hb", "rf_default_hb_probe.s2p",
        )}
    ):
        raise ValueError("RF low-drive HB OA derivation or remote source snapshot differs")
    geometry = default_rf_geometry(source.decode("utf-8"))
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    loaded = re.findall(r"^Reading file:\s+(/[^\s]+/netlist\.scs)$", log, re.MULTILINE)
    if (
        len(loaded) != 1
        or not loaded[0].endswith(f"/{run_dir.name}/netlist.scs")
        or len(re.findall(r"^Reading file:\s+" + re.escape(loaded[0].rsplit("/", 1)[0])
                          + r"/ade_e\.scs$", log, re.MULTILINE)) != 1
        or not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or not re.search(r"Total time required for hb analysis `hb'", log)
        or "SPECTRE-25" in log
    ):
        raise ValueError("RF low-drive HB Spectre source or completion differs")
    for name, analysis_type in (
        ("hb.fd.pss_hb", "fd.pss_hb"), ("hb.fi.pss_hb", "fi.pss_hb"),
        ("hb.td.pss_hb", "td.pss_hb"),
    ):
        header = (run_dir / name).read_text(encoding="utf-8", errors="replace").split("TYPE", 1)[0]
        if f'"analysis type" "{analysis_type}"' not in header or '"analysis name" "hb"' not in header:
            raise ValueError("RF low-drive HB raw analysis type differs")
        if name == "hb.fd.pss_hb" and not re.search(r'^"harms"\s+' + str(harmonics) + r'$', header, re.MULTILINE):
            raise ValueError("RF low-drive HB harmonic count differs")
    maximum_s_delta = 0.0
    frequency: list[float] | None = None
    touchstone = parse_touchstone_2port(run_dir / "rf_default_hb_probe.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("RF low-drive HB Touchstone port references differ")
    maximum_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, current = parse_complex_trace(run_dir / "sp.sp", signal)
        baseline_grid, prior = parse_complex_trace(baseline_dir / "sp.sp", signal)
        if grid != baseline_grid or (frequency is not None and grid != frequency):
            raise ValueError("RF low-drive HB SP grid differs from the OA baseline")
        frequency = grid
        for sample, left, right, row in zip(grid, current, prior, touchstone, strict=True):
            if not math.isclose(sample, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("RF low-drive HB Touchstone frequency differs")
            maximum_s_delta = max(maximum_s_delta, abs(left - right))
            maximum_touchstone_delta = max(
                maximum_touchstone_delta,
                abs(left - complex(row[f"{signal}_real"], row[f"{signal}_imag"])),
            )
    if (
        frequency is None or len(frequency) != 161
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
        or maximum_s_delta > 1e-8 or maximum_touchstone_delta > 1e-8
    ):
        raise ValueError("RF low-drive HB small-signal response differs from the OA baseline")
    maximum_noise_delta = 0.0
    for signal in ("NF", "NFmin", "F", "Fmin"):
        grid, current = parse_scalar_trace(run_dir / "sp.noise.sp", signal)
        prior_grid, prior = parse_scalar_trace(baseline_dir / "sp.noise.sp", signal)
        if grid != frequency or prior_grid != frequency:
            raise ValueError("RF low-drive HB noise grid differs from SP")
        maximum_noise_delta = max(maximum_noise_delta, *(abs(a - b) for a, b in zip(current, prior, strict=True)))
    if maximum_noise_delta > 1e-6:
        raise ValueError("RF low-drive HB noise response differs from the OA baseline")
    current_dc = parse_dc_values(run_dir / "dcOp.dc")
    baseline_dc = parse_dc_values(baseline_dir / "dcOp.dc")
    if (
        "VDD_SRC:p" not in current_dc or "VDD_SRC:p" not in baseline_dc
        or not math.isclose(current_dc["VDD_SRC:p"], baseline_dc["VDD_SRC:p"], abs_tol=1e-9)
    ):
        raise ValueError("RF low-drive HB supply current differs from the OA baseline")
    for index in range(1, 7):
        current_op = parse_struct_values(run_dir / "dcOpInfo.info", instance=f"M{index}", struct_type="bsim4")
        baseline_op = parse_struct_values(baseline_dir / "dcOpInfo.info", instance=f"M{index}", struct_type="bsim4")
        if any(
            field not in current_op or field not in baseline_op
            or not math.isclose(current_op[field], baseline_op[field], rel_tol=1e-8, abs_tol=1e-12)
            for field in _OP_FIELDS
        ):
            raise ValueError("RF low-drive HB device operating points differ from the OA baseline")
    hb_path = run_dir / "hb.fd.pss_hb"
    input_dbm = extract_hb_input_available_power(hb_path, fundamental_hz=10e9)
    hb = extract_hb_differential_fundamental_power(hb_path, fundamental_hz=10e9)
    small_signal_s21_db = extract_sp_s21_at_frequency(run_dir / "sp.sp", 10e9)
    power_gain_db = hb["output_power_dbm"] - input_dbm
    gain_delta_db = power_gain_db - small_signal_s21_db
    if not math.isclose(input_dbm, drive_dbm, abs_tol=0.01) or (
        drive_dbm <= -50 and abs(gain_delta_db) > 0.01
    ):
        raise ValueError("RF HB input or low-drive power gain disagrees with SP")
    metrics = {
        "input_available_power_dbm": input_dbm,
        "output_power_dbm": hb["output_power_dbm"],
        "power_gain_db": power_gain_db,
        "small_signal_s21_db": small_signal_s21_db,
        "hb_minus_s21_db": gain_delta_db,
        "load_current_relative_error": hb["load_current_relative_error"],
        "vout_diff_peak_v": hb["vout_diff_peak_v"],
        "iout_peak_a": hb["iout_peak_a"],
        "supply_current_ma": -current_dc["VDD_SRC:p"] * 1e3,
    }
    payload = {
        "schema_version": 1,
        "status": ("hb_low_drive_verified_with_warnings" if legacy_low_drive
                   else "hb_drive_probe_verified_with_warnings"),
        "simulation_status": "ok", "source": "cadence_spectre",
        "source_run_kind": ("pdk_rf_default_oa_derived_ideal_passive_hb_low_drive"
                            if legacy_low_drive else "pdk_rf_default_oa_derived_ideal_passive_hb_drive_probe"),
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": ("OA-derived low-drive differential HB with ideal passives; no compression or qualified LNA claim"
                  if legacy_low_drive else "OA-derived differential HB drive probe with ideal passives; no qualified LNA claim"),
        "analysis": ["dc", "op_info", "sp", "noise", "hb"], "points": len(frequency),
        "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "metrics": metrics, "oa_create_run_id": create_dir.name,
        "oa_schematic_sha256": oa_hash, "baseline_run_id": baseline_dir.name,
        "default_geometry_signature_sha256": hashlib.sha256("|".join(geometry).encode()).hexdigest(),
        "maximum_baseline_complex_s_delta": maximum_s_delta,
        "maximum_baseline_noise_delta": maximum_noise_delta,
        "maximum_touchstone_complex_delta": maximum_touchstone_delta,
        "physical_qualification": False, "cdf_callback_validated": False,
        "spectre_warning_count": 5,
    }
    if not legacy_low_drive:
        payload["input_drive_dbm"] = drive_dbm
    if harmonics != 7:
        payload["harmonics"] = harmonics
    validate_metrics_payload(payload)
    return payload


def audit_pdk_rf_default_hb(run_dir: Path, create_dir: Path, baseline_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    entries = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8")).get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != relative
           for key, relative in _ARTIFACTS.items()):
        raise ValueError("RF low-drive HB evidence lacks required artifacts")
    rebuilt = extract_pdk_rf_default_hb(run_dir, create_dir, baseline_dir)
    if saved != rebuilt:
        raise ValueError("RF low-drive HB metrics differ from raw Spectre archive")
    with (run_dir / "hb_fundamental.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _HB_COLUMNS:
            raise ValueError("RF low-drive HB CSV columns differ")
        rows = list(reader)
    if len(rows) != 1 or any(
        not math.isclose(float(rows[0][key]), rebuilt["metrics"][key], rel_tol=1e-10, abs_tol=1e-12)
        for key in _HB_COLUMNS
    ):
        raise ValueError("RF low-drive HB CSV differs from raw Spectre archive")
    return {"status": "verified", "run_id": run_dir.name, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a private OA-derived RF low-drive HB probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--create-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        payload = extract_pdk_rf_default_hb(args.run_dir, args.create_dir, args.baseline_dir)
        if (args.run_dir / "metrics.json").exists() or (args.run_dir / "hb_fundamental.csv").exists():
            raise FileExistsError("refusing to overwrite RF low-drive HB result")
        with (args.run_dir / "hb_fundamental.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_HB_COLUMNS)
            writer.writeheader()
            writer.writerow({key: payload["metrics"][key] for key in _HB_COLUMNS})
        write_json(args.run_dir / "metrics.json", payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_rf_default_hb(args.run_dir, args.create_dir, args.baseline_dir)
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
