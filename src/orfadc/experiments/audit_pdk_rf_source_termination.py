from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.noise_parameters import (
    matched_load_transducer_gain, noise_factor_at_source, read_noise_parameter_points,
    source_reflection_from_admittance,
)
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_dc_values
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_rf_source_termination import (
    _BASE, _CREATE, _RAW, render_source_termination_netlist,
    render_source_termination_wrapper,
)
from orfadc.metric_contract import validate_metrics_payload


_COLUMNS = (
    "freq_hz", "nf_50_db", "nf_100_pred_db", "nf_100_measured_db",
    "s21_50_db", "gain_100_pred_db", "s21_100_measured_db",
    "gamma_opt_real", "gamma_opt_imag",
)
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "prediction.csv", "netlist": "netlist.scs",
    "spectre_log": "spectre.log", "wrapper": "wrapper.scs", "ade_companion": "ade_e.scs",
    "status": "run_status.json", "touchstone": "source_termination.s2p",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp",
    "noise_raw": "sp.noise.sp", "stdout": "stdout.log", "stderr": "stderr.log",
    "remote_netlist": "remote_netlist.scs", "remote_wrapper": "remote_wrapper.scs",
    "remote_ade": "remote_ade_e.scs",
}


def _read(path: Path) -> bytes:
    _require_private_path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("source termination artifact is missing or unsafe")
    return path.read_bytes()


def extract_pdk_rf_source_termination(run_dir: Path) -> tuple[list[dict], dict]:
    _require_private_path(run_dir)
    base_root = _PRIVATE_ROOT / "pdk_three_stage_fixed"
    base_dir, create_dir = base_root / _BASE, base_root / _CREATE
    audit_pdk_rf_default_three_stage(base_dir, create_dir)
    status = json.loads(_read(run_dir / "run_status.json").decode("utf-8"))
    base_source = _read(base_dir / "netlist.scs")
    derived = render_source_termination_netlist(base_source, 100)
    wrapper = render_source_termination_wrapper()
    expected_downloads = dict.fromkeys((
        "spectre.log", "source_termination.s2p", *_RAW,
        "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs",
    ), True)
    if (
        status.get("status") != "simulation_recorded" or status.get("run_id") != run_dir.name
        or status.get("source_active_run_id") != _BASE
        or status.get("source_create_run_id") != _CREATE
        or status.get("source_manifest_sha256") != hashlib.sha256(
            _read(base_dir / "evidence_manifest.json")
        ).hexdigest()
        or status.get("source_oa_netlist_sha256") != hashlib.sha256(base_source).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derived).hexdigest()
        or status.get("wrapper_sha256") != hashlib.sha256(wrapper).hexdigest()
        or status.get("source_ohm") != 100 or status.get("spectre_returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("downloads") != expected_downloads
        or any(status.get(flag) is not False for flag in (
            "pdk_write", "user_oa_write", "physical_qualification", "cdf_callback_validated",
        ))
        or status.get("not_lna_result") is not True or status.get("spec_pass") is not None
        or _read(run_dir / "netlist.scs") != derived
        or _read(run_dir / "remote_netlist.scs") != derived
        or _read(run_dir / "wrapper.scs") != wrapper
        or _read(run_dir / "remote_wrapper.scs") != wrapper
        or _read(run_dir / "ade_e.scs") != _read(base_dir / "ade_e.scs")
        or _read(run_dir / "remote_ade_e.scs") != _read(base_dir / "ade_e.scs")
    ):
        raise ValueError("source termination run lacks its bounded OA/Spectre context")
    log = _read(run_dir / "spectre.log").decode("utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*5 warnings", log):
        raise ValueError("source termination Spectre log lacks expected completion")
    base_dc = parse_dc_values(base_dir / "dcOp.dc")
    new_dc = parse_dc_values(run_dir / "dcOp.dc")
    if base_dc != new_dc:
        raise ValueError("source resistance changed the fixed circuit DC operating point")
    base_noise = read_noise_parameter_points(base_dir / "sp.noise.sp")
    new_noise = read_noise_parameter_points(run_dir / "sp.noise.sp")
    base_freq, base_s11 = parse_complex_trace(base_dir / "sp.sp", "s11")
    _, base_s21 = parse_complex_trace(base_dir / "sp.sp", "s21")
    s_names = ("s11", "s21", "s12", "s22")
    new_s = {name: parse_complex_trace(run_dir / "sp.sp", name) for name in s_names}
    new_freq, new_s21 = new_s["s21"]
    if (
        len(base_noise) != 161 or len(new_noise) != 161
        or base_freq != new_freq
        or any(frequencies != new_freq for frequencies, _ in new_s.values())
        or [point.frequency_hz for point in base_noise] != base_freq
        or [point.frequency_hz for point in new_noise] != base_freq
    ):
        raise ValueError("source termination frequency grids differ")
    touchstone = parse_touchstone_2port(run_dir / "source_termination.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 100.0
        or row.get("reference_output_ohm") != 1787.0
        or not math.isclose(row["freq_hz"], frequency, rel_tol=1e-12, abs_tol=1e-3)
        for row, frequency in zip(touchstone, new_freq, strict=True)
    ):
        raise ValueError("source termination Touchstone references or frequencies disagree")
    for name in s_names:
        if any(
            abs(complex(row[f"{name}_real"], row[f"{name}_imag"]) - actual) > 1e-10
            for row, actual in zip(touchstone, new_s[name][1], strict=True)
        ):
            raise ValueError(f"source termination Touchstone and raw {name} disagree")
    gamma_s = source_reflection_from_admittance(0.01 + 0j, 50)
    rows = []
    nf_residuals = []
    gain_residuals = []
    for frequency, source, new, s11, s21, measured_s21 in zip(
        base_freq, base_noise, new_noise, base_s11, base_s21, new_s21, strict=True,
    ):
        if not math.isclose(noise_factor_at_source(source, 0.02 + 0j), source.measured_f,
                            rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("baseline 50-ohm noise parameters do not reproduce its F")
        if not math.isclose(noise_factor_at_source(new, 0.01 + 0j), new.measured_f,
                            rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("new 100-ohm noise parameters do not reproduce its F")
        predicted_nf = 10 * math.log10(noise_factor_at_source(source, 0.01 + 0j))
        predicted_gain = 10 * math.log10(matched_load_transducer_gain(s11, s21, gamma_s))
        measured_gain = 20 * math.log10(abs(measured_s21))
        nf_residuals.append(abs(predicted_nf - new.measured_nf_db))
        gain_residuals.append(abs(predicted_gain - measured_gain))
        gamma_opt = source_reflection_from_admittance(source.yopt_s, 50)
        rows.append({
            "freq_hz": frequency, "nf_50_db": source.measured_nf_db,
            "nf_100_pred_db": predicted_nf, "nf_100_measured_db": new.measured_nf_db,
            "s21_50_db": 20 * math.log10(abs(s21)),
            "gain_100_pred_db": predicted_gain, "s21_100_measured_db": measured_gain,
            "gamma_opt_real": gamma_opt.real, "gamma_opt_imag": gamma_opt.imag,
        })
    if max(nf_residuals) > 1e-6 or max(gain_residuals) > 1e-6:
        raise ValueError("source termination prediction differs from independent Spectre run")
    report = {
        "schema_version": 1, "status": "source_termination_prediction_verified",
        "simulation_status": "ok", "source": "cadence_spectre",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "ideal 100-ohm source termination of default RF OA netlist; not a physical match or LNA result",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "source_active_run_id": _BASE, "source_create_run_id": _CREATE,
        "source_manifest_sha256": status["source_manifest_sha256"],
        "source_ohm": 100, "baseline_source_ohm": 50,
        "points": len(rows), "spectre_warning_count": 5,
        "max_abs_nf_prediction_delta_db": max(nf_residuals),
        "max_abs_gain_prediction_delta_db": max(gain_residuals),
        "baseline_worst_nf_db": max(row["nf_50_db"] for row in rows),
        "terminated_worst_nf_db": max(row["nf_100_measured_db"] for row in rows),
        "baseline_worst_s21_db": min(row["s21_50_db"] for row in rows),
        "terminated_worst_s21_db": min(row["s21_100_measured_db"] for row in rows),
        "gamma_opt_abs_10ghz": abs(complex(rows[80]["gamma_opt_real"], rows[80]["gamma_opt_imag"])),
        "host_available_gib_before": status["host_available_gib_before"],
        "pdk_write": False, "user_oa_write": False,
        "cdf_callback_validated": False, "physical_qualification": False,
    }
    validate_metrics_payload(report)
    return rows, report


def audit_pdk_rf_source_termination(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads(_read(run_dir / "evidence_manifest.json").decode("utf-8"))
    if any(manifest.get("artifacts", {}).get(key, {}).get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("source termination evidence lacks required raw artifacts")
    rows, rebuilt = extract_pdk_rf_source_termination(run_dir)
    if saved != rebuilt:
        raise ValueError("source termination summary differs from raw Spectre evidence")
    path = run_dir / "prediction.csv"
    if path.is_symlink():
        raise ValueError("source termination prediction CSV is symlinked")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("source termination prediction columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(actual[key]), expected[key], rel_tol=1e-10, abs_tol=1e-10)
        for actual, expected in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("source termination prediction CSV differs from original Spectre data")
    return {"status": "verified", "points": len(rows), "not_lna_result": True}


def finalize_pdk_rf_source_termination(run_dir: Path) -> dict:
    rows, report = extract_pdk_rf_source_termination(run_dir)
    with (run_dir / "prediction.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(run_dir / "metrics.json", report)
    write_evidence_manifest(run_dir, _ARTIFACTS)
    audit_pdk_rf_source_termination(run_dir)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit controlled RF source termination")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = (finalize_pdk_rf_source_termination(args.run_dir) if args.finalize
              else audit_pdk_rf_source_termination(args.run_dir))
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
