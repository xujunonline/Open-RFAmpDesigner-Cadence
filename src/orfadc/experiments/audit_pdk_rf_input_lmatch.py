from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii, require_same_frequency_grid, summarize_noise
from orfadc.cadence.passive_quality import oneport_impedance
from orfadc.cadence.psfascii_reader import (
    magnitude_db, parse_complex_trace, parse_dc_values, parse_scalar_trace,
    parse_struct_values, parse_trace_kinds,
)
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.stability_metrics import summarize_sampled_stability
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_rf_input_lmatch import (
    render_input_lmatch, render_lmatch_wrapper, synthesize_input_lmatch,
)
from orfadc.metric_contract import validate_metrics_payload


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "ade_companion": "ade_e.scs", "wrapper": "wrapper.scs",
    "remote_netlist": "remote_netlist.scs", "remote_companion": "remote_ade_e.scs",
    "remote_wrapper": "remote_wrapper.scs", "run_status": "run_status.json",
    "spectre_log": "spectre.log", "stdout": "stdout.log", "stderr": "stderr.log",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp",
    "noise_raw": "sp.noise.sp", "touchstone": "matched.s2p",
}


def _source_dirs(status: dict) -> tuple[Path, Path]:
    active_id = status.get("source_active_run_id")
    create_id = status.get("source_create_run_id")
    if any(not isinstance(value, str) or _RUN_ID.fullmatch(value) is None
           for value in (active_id, create_id)):
        raise ValueError("RF input L-match source IDs are invalid")
    return (
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / active_id,
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / create_id,
    )


def extract_pdk_rf_input_lmatch(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("RF input L-match run directory is missing or unsafe")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    active_dir, create_dir = _source_dirs(status)
    audit_pdk_rf_default_three_stage(active_dir, create_dir)
    source = (active_dir / "netlist.scs").read_bytes()
    shunt_l_h, series_c_f = synthesize_input_lmatch(active_dir)
    derived = render_input_lmatch(source, shunt_l_h, series_c_f)
    wrapper = render_lmatch_wrapper()
    if (
        status.get("status") != "simulation_recorded"
        or status.get("run_id") != run_dir.name
        or status.get("spectre_returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or any(status.get(key) is not False for key in (
            "pdk_write", "user_oa_write", "physical_qualification", "cdf_callback_validated",
        ))
        or status.get("not_lna_result") is not True or status.get("spec_pass") is not None
        or status.get("source_oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derived).hexdigest()
        or status.get("wrapper_sha256") != hashlib.sha256(wrapper).hexdigest()
        or not math.isclose(status.get("shunt_l_h", float("nan")), shunt_l_h, rel_tol=1e-14)
        or not math.isclose(status.get("series_c_f", float("nan")), series_c_f, rel_tol=1e-14)
        or status.get("downloads") != dict.fromkeys((
            "spectre.log", "matched.s2p", "dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp",
            "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs",
        ), True)
        or any((run_dir / name).read_bytes() != expected for name, expected in (
            ("netlist.scs", derived), ("remote_netlist.scs", derived),
            ("wrapper.scs", wrapper), ("remote_wrapper.scs", wrapper),
            ("ade_e.scs", (active_dir / "ade_e.scs").read_bytes()),
            ("remote_ade_e.scs", (active_dir / "ade_e.scs").read_bytes()),
        ))
    ):
        raise ValueError("RF input L-match source, derivation, or archive differs")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    loaded = {}
    for name in ("wrapper", "netlist", "ade_e"):
        paths = re.findall(r"(?m)^Reading file:\s+(/[^\s]+/" + name + r"\.scs)$", log)
        if len(paths) != 1:
            raise ValueError("Spectre log lacks a unique derived source file")
        loaded[name] = paths[0].rsplit("/", 1)[0]
    if (
        len(set(loaded.values())) != 1
        or not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("RF input L-match Spectre completion or model-warning profile differs")
    reference_frequency, reference_s11 = parse_complex_trace(active_dir / "sp.sp", "s11")
    frequency = None
    sparams: dict[str, list[complex]] = {}
    for name in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", name)
        if frequency is None:
            frequency = grid
        elif frequency != grid:
            raise ValueError("RF input L-match S-parameter grids differ")
        sparams[name] = values
    if (
        frequency != reference_frequency or frequency is None or len(frequency) != 161
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
    ):
        raise ValueError("RF input L-match frequency grid differs from OA source")
    predicted = []
    for sample, old_s11 in zip(frequency, reference_s11, strict=True):
        omega = 2 * math.pi * sample
        z = oneport_impedance(old_s11, 50.0)
        transformed = 1 / (1 / z - 1j / (omega * shunt_l_h)) - 1j / (omega * series_c_f)
        predicted.append((transformed - 50) / (transformed + 50))
    prediction_delta = max(abs(expected - observed) for expected, observed in zip(
        predicted, sparams["s11"], strict=True,
    ))
    if prediction_delta > 1e-6:
        raise ValueError("raw Spectre S11 disagrees with derived lossless network equations")
    touchstone = parse_touchstone_2port(run_dir / "matched.s2p")
    if len(touchstone) != len(frequency) or any(
        row["reference_input_ohm"] != 50 or row["reference_output_ohm"] != 1787
        for row in touchstone
    ):
        raise ValueError("RF input L-match Touchstone port references differ")
    touchstone_delta = max(
        abs(value - complex(row[f"{name}_real"], row[f"{name}_imag"]))
        for name, values in sparams.items()
        for value, row in zip(values, touchstone, strict=True)
    )
    if touchstone_delta > 1e-8 or any(
        not math.isclose(sample, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3)
        for sample, row in zip(frequency, touchstone, strict=True)
    ):
        raise ValueError("RF input L-match Touchstone and raw PSF differ")
    noise_path = run_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    if any(kinds.get(name) != kind for name, kind in (
        ("NF", "dB"), ("NFmin", "dB"), ("F", "Noise factor"), ("Fmin", "Noise factor"),
    )):
        raise ValueError("RF input L-match noise units differ")
    noise = noise_rows_from_psfascii(noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin")
    rows = [{
        "freq_hz": sample, "freq_ghz": sample / 1e9,
        **{f"{name}_db": magnitude_db([sparams[name][index]])[0]
           for name in ("s11", "s21", "s22")},
        "nf_db": float(noise[index]["nf_db"]), "nfmin_db": float(noise[index]["nfmin_db"]),
    } for index, sample in enumerate(frequency)]
    require_same_frequency_grid(noise, rows)
    for factor, key in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        grid, values = parse_scalar_trace(noise_path, factor)
        if grid != frequency or any(
            value <= 0 or not math.isclose(10 * math.log10(value), row[key], abs_tol=1e-6)
            for value, row in zip(values, rows, strict=True)
        ):
            raise ValueError("RF input L-match noise factor and figure disagree")
    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    old_current = read_evidenced_metrics(active_dir)["metrics"]["supply_current_ma"]
    if current_ma <= 0 or not math.isclose(current_ma, old_current, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("RF input L-match changed the original DC bias")
    for index in range(1, 7):
        name = f"M{index}"
        original = parse_struct_values(active_dir / "dcOpInfo.info", instance=name, struct_type="bsim4")
        observed = parse_struct_values(run_dir / "dcOpInfo.info", instance=name, struct_type="bsim4")
        if any(not math.isclose(original[key], observed[key], rel_tol=1e-6, abs_tol=1e-9)
               for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds")):
            raise ValueError("RF input L-match changed a MOS DC operating point")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.1 * current_ma,
    }
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "pdk_rf_default_oa_derived_ideal_input_lmatch",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "one OA-netlist-derived ideal 10-GHz input L-match; not physical or broadband LNA",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": metrics, "points": len(rows),
        "stability": summarize_sampled_stability(*(sparams[name] for name in ("s11", "s21", "s12", "s22"))),
        "center_s11_db": rows[80]["s11_db"],
        "maximum_predicted_to_spectre_complex_s11_delta": prediction_delta,
        "maximum_touchstone_psfascii_complex_delta": touchstone_delta,
        "ideal_shunt_l_nh": shunt_l_h * 1e9,
        "ideal_series_c_ff": series_c_f * 1e15,
        "source_active_run_id": active_dir.name, "source_create_run_id": create_dir.name,
        "source_oa_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(derived).hexdigest(),
        "physical_qualification": False, "cdf_callback_validated": False,
        "host_available_gib_before": status["host_available_gib_before"],
        "spectre_warning_count": 5,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_rf_input_lmatch(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    if any(manifest["artifacts"].get(key, {}).get("path") != path
           for key, path in _ARTIFACTS.items()):
        raise ValueError("RF input L-match archive lacks a required source or raw artifact")
    rows, rebuilt = extract_pdk_rf_input_lmatch(run_dir)
    if saved != rebuilt:
        raise ValueError("RF input L-match metrics differ from raw Spectre archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("RF input L-match waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(stored[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for stored, row in zip(stored_rows, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("RF input L-match waveform CSV differs from raw Spectre data")
    return {"status": "verified", "points": len(rows), "not_lna_result": True,
            "physical_qualification": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private OA-netlist-derived RF input L-match")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        rows, payload = extract_pdk_rf_input_lmatch(args.run_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_rf_input_lmatch(args.run_dir)
    print(f"status={result['status']} points={result['points']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
