from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii, require_same_frequency_grid, summarize_noise
from orfadc.cadence.psfascii_reader import (
    magnitude_db, parse_complex_trace, parse_dc_values, parse_scalar_trace,
    parse_struct_values, parse_trace_kinds,
)
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_hybrid_ac_probe import (
    _NODES, ac_voltage_steps, audit_pdk_hybrid_ac_probe,
)
from orfadc.experiments.audit_pdk_hybrid_three_stage import (
    audit_pdk_hybrid_three_stage, validate_hybrid_topology,
)
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_OLD = "K12 mutual_inductor coupling=0.45 ind1=L12P ind2=L12S"
_NEW = "K12 mutual_inductor coupling=0.8 ind1=L12P ind2=L12S"
_COLUMNS = (
    "freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db",
    "first_coupler_voltage_db", "overall_voltage_db",
)
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv",
    "oa_netlist": "oa_netlist.scs", "netlist": "netlist.scs",
    "ade_companion": "ade_e.scs", "remote_netlist": "remote_netlist.scs",
    "remote_ade_companion": "remote_ade_e.scs", "sp_wrapper": "sp_wrapper.scs",
    "remote_sp_wrapper": "remote_sp_wrapper.scs", "ac_wrapper": "ac_wrapper.scs",
    "remote_ac_wrapper": "remote_ac_wrapper.scs", "run_status": "run_status.json",
    "spectre_log": "sp.log", "ac_log": "ac.log",
    "sp_stdout": "sp_stdout.log", "sp_stderr": "sp_stderr.log",
    "ac_stdout": "ac_stdout.log", "ac_stderr": "ac_stderr.log",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp",
    "noise_raw": "sp.noise.sp", "touchstone": "k12_0p8.s2p", "ac_raw": "ac.ac",
}


def require_single_k12_change(original: bytes, derived: bytes) -> None:
    source = original.decode("utf-8")
    variant = derived.decode("utf-8")
    if source.count(_OLD) != 1 or variant != source.replace(_OLD, _NEW, 1):
        raise ValueError("derived netlist is not exactly one K12 change")
    validate_hybrid_topology(source)
    validate_hybrid_topology(variant)


def _require_log(path: Path) -> None:
    log = path.read_text(encoding="utf-8", errors="replace")
    if (
        not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("K12 derivative Spectre completion or warning profile differs")


def extract_pdk_k12_sensitivity(
    run_dir: Path, baseline_sp: Path, baseline_ac: Path,
) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("K12 derivative run must be an ordinary directory")
    audit_pdk_hybrid_three_stage(baseline_sp)
    audit_pdk_hybrid_ac_probe(baseline_ac)
    baseline_metrics = read_evidenced_metrics(baseline_sp)
    baseline_ac_metrics = read_evidenced_metrics(baseline_ac)
    original = (run_dir / "oa_netlist.scs").read_bytes()
    derivative = (run_dir / "netlist.scs").read_bytes()
    require_single_k12_change(original, derivative)
    if (
        original != (baseline_sp / "netlist.scs").read_bytes()
        or original != (baseline_ac / "netlist.scs").read_bytes()
        or (run_dir / "ade_e.scs").read_bytes() != (baseline_sp / "ade_e.scs").read_bytes()
        or (run_dir / "remote_netlist.scs").read_bytes() != derivative
        or (run_dir / "remote_ade_e.scs").read_bytes() != (run_dir / "ade_e.scs").read_bytes()
        or any((run_dir / f"remote_{kind}_wrapper.scs").read_bytes() != (run_dir / f"{kind}_wrapper.scs").read_bytes()
               for kind in ("sp", "ac"))
    ):
        raise ValueError("K12 derivative source or baseline snapshots differ")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if (
        status.get("status") != "simulation_ok"
        or status.get("source") != "cadence_spectre"
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or status.get("probe_kind") != "one_factor_ideal_k12_sensitivity"
        or type(status.get("host_available_gib_before")) not in {int, float}
        or status["host_available_gib_before"] < 2.66
        or status.get("oa_netlist_sha256") != hashlib.sha256(original).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derivative).hexdigest()
        or status.get("oa_netlist_sha256_after") != status["oa_netlist_sha256"]
        or status.get("sp_returncode") != 0 or status.get("ac_returncode") != 0
        or status.get("downloads") != {name: True for name in (
            "sp.log", "dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp",
            "k12_0p8.s2p", "ac.log", "ac.ac",
        )}
    ):
        raise ValueError("K12 derivative remote run status differs")
    for kind in ("sp", "ac"):
        wrapper = (run_dir / f"{kind}_wrapper.scs").read_text(encoding="ascii").replace("\r\n", "\n")
        if not re.search(r'^include "[^"\n]+/netlist\.scs"$', wrapper, re.MULTILINE):
            raise ValueError("K12 derivative wrapper does not include archived netlist")
        if kind == "sp" and (
            "dcOpInfo info what=oppoint where=rawfile" not in wrapper
            or "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2]" not in wrapper
            or "donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport" not in wrapper
            or "VPROBE" in wrapper
        ):
            raise ValueError("K12 SP/noise wrapper differs")
        if kind == "ac" and (
            "VPROBE (in 0) vsource dc=0 mag=1" not in wrapper
            or "ac ac start=8G stop=12G lin=160" not in wrapper
            or len(wrapper.splitlines()) != 4
        ):
            raise ValueError("K12 AC wrapper differs")
        _require_log(run_dir / f"{kind}.log")

    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    if current_ma <= 0 or not math.isfinite(current_ma):
        raise ValueError("K12 derivative supply current invalid")
    device_currents = []
    for index in range(1, 7):
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance=f"M{index}", struct_type="bsim4")
        if any(not math.isfinite(op[name]) or op[name] <= 0 for name in ("ids", "vgs", "vds", "vdsat", "gm", "gds")) or op["vds"] <= op["vdsat"]:
            raise ValueError("K12 derivative MOS operating point invalid")
        device_currents.append(op["ids"])
    if (
        not math.isclose(device_currents[0], device_currents[1], rel_tol=1e-3)
        or not math.isclose(sum(device_currents[1:]), current_ma / 1e3, rel_tol=1e-4)
        or not math.isclose(current_ma, baseline_metrics["metrics"]["supply_current_ma"], rel_tol=1e-8)
    ):
        raise ValueError("K12 derivative DC KCL or baseline current differs")

    touchstone = parse_touchstone_2port(run_dir / "k12_0p8.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("K12 derivative Touchstone references differ")
    frequency = None
    sparams = {}
    max_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", signal)
        if frequency is None:
            frequency = grid
        elif grid != frequency:
            raise ValueError("K12 derivative S-parameter grids differ")
        sparams[signal] = values
        for sample_frequency, value, row in zip(grid, values, touchstone, strict=True):
            if not math.isclose(sample_frequency, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("K12 derivative Touchstone grid differs")
            max_touchstone_delta = max(max_touchstone_delta, abs(value - complex(row[f"{signal}_real"], row[f"{signal}_imag"])))
    if (
        frequency is None or len(frequency) != 161 or max_touchstone_delta > 1e-8
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
    ):
        raise ValueError("K12 derivative S-parameter data incomplete")
    noise_path = run_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    if any(kinds.get(name) != kind for name, kind in (
        ("NF", "dB"), ("NFmin", "dB"), ("F", "Noise factor"), ("Fmin", "Noise factor"),
    )):
        raise ValueError("K12 derivative noise units differ")
    noise = noise_rows_from_psfascii(noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin")
    srows = [
        {
            "freq_hz": sample, "freq_ghz": sample / 1e9,
            **{f"{signal}_db": magnitude_db([sparams[signal][index]])[0]
               for signal in ("s11", "s21", "s22")},
        }
        for index, sample in enumerate(frequency)
    ]
    require_same_frequency_grid(noise, srows)
    for factor, db in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        grid, values = parse_scalar_trace(noise_path, factor)
        if grid != frequency or any(value <= 0 or not math.isclose(10 * math.log10(value), row[db], abs_tol=1e-6)
                                    for value, row in zip(values, noise, strict=True)):
            raise ValueError("K12 derivative noise factor disagrees with noise figure")
    ac_traces = {name: parse_complex_trace(run_dir / "ac.ac", name) for name in _NODES}
    if any(ac_traces[name][0] != frequency for name in _NODES):
        raise ValueError("K12 derivative AC and SP frequency grids differ")
    rows = [
        {
            **srow, "nf_db": float(noise[index]["nf_db"]), "nfmin_db": float(noise[index]["nfmin_db"]),
            **{
                "first_coupler_voltage_db": steps["first_coupler"],
                "overall_voltage_db": steps["overall_voltage_db"],
            },
        }
        for index, srow in enumerate(srows)
        for steps in [ac_voltage_steps({name: ac_traces[name][1][index] for name in _NODES})]
    ]
    center = rows[80]
    if not math.isclose(center["freq_hz"], 10e9, rel_tol=1e-12):
        raise ValueError("K12 derivative lacks 10 GHz center")
    base_sp_grid, base_s21 = parse_complex_trace(baseline_sp / "sp.sp", "s21")
    base_ac_grid, base_ac_coupler = parse_complex_trace(baseline_ac / "ac.ac", "g2p")
    if base_sp_grid != frequency or base_ac_grid != frequency or len(base_ac_coupler) != 161:
        raise ValueError("K12 baseline grids differ")
    baseline_s21_db = magnitude_db([base_s21[80]])[0]
    baseline_coupler_db = baseline_ac_metrics["metrics"]["first_coupler_voltage_db_at_10ghz"]
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.1 * current_ma,
        "s21_db_at_10ghz": center["s21_db"],
        "s21_delta_db_at_10ghz": center["s21_db"] - baseline_s21_db,
        "first_coupler_voltage_db_at_10ghz": center["first_coupler_voltage_db"],
        "first_coupler_delta_db_at_10ghz": center["first_coupler_voltage_db"] - baseline_coupler_db,
        "overall_voltage_db_at_10ghz": center["overall_voltage_db"],
    }
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "pdk_hybrid_ideal_k12_derivative",
        "circuit_class": "pdk_hybrid_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "one-factor ideal coupling derivative, not OA schematic, qualified MCR, or LNA result",
        "analysis": ["dc", "op_info", "sp", "noise", "ac"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "design_parameters": {"k12_base": 0.45, "k12_variant": 0.8},
        "metrics": metrics, "points": len(rows),
        "maximum_touchstone_psfascii_complex_delta": max_touchstone_delta,
        "baseline_sp_run_id": baseline_sp.name, "baseline_ac_run_id": baseline_ac.name,
        "baseline_sp_manifest_sha256": hashlib.sha256((baseline_sp / "evidence_manifest.json").read_bytes()).hexdigest(),
        "baseline_ac_manifest_sha256": hashlib.sha256((baseline_ac / "evidence_manifest.json").read_bytes()).hexdigest(),
        "host_available_gib_before": status["host_available_gib_before"],
        "physical_qualification": False, "cdf_callback_validated": False,
        "spectre_warning_count_per_analysis": 5,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_k12_sensitivity(run_dir: Path, baseline_sp: Path, baseline_ac: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    entries = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8")).get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("K12 derivative evidence lacks required artifacts")
    rows, rebuilt = extract_pdk_k12_sensitivity(run_dir, baseline_sp, baseline_ac)
    if saved != rebuilt:
        raise ValueError("K12 derivative metrics differ from raw Spectre archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("K12 derivative waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(stored[name]), row[name], rel_tol=1e-10, abs_tol=1e-12)
        for stored, row in zip(stored_rows, rows, strict=True) for name in _COLUMNS
    ):
        raise ValueError("K12 derivative waveforms differ from raw Spectre archives")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private one-factor ideal K12 derivative")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--baseline-sp", required=True, type=Path)
    parser.add_argument("--baseline-ac", required=True, type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_pdk_k12_sensitivity(args.run_dir, args.baseline_sp, args.baseline_ac)
        if (args.run_dir / "metrics.json").exists() or (args.run_dir / "waveforms.csv").exists():
            raise FileExistsError("refusing to overwrite K12 derivative results")
        with (args.run_dir / "waveforms.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        write_json(args.run_dir / "metrics.json", payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_k12_sensitivity(args.run_dir, args.baseline_sp, args.baseline_ac)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
