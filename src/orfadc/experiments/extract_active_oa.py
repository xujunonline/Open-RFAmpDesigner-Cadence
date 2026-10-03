from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import (
    noise_rows_from_psfascii,
    require_same_frequency_grid,
    summarize_noise,
)
from orfadc.cadence.psfascii_reader import (
    magnitude_db,
    parse_complex_trace,
    parse_dc_values,
    parse_scalar_trace,
    parse_struct_values,
    parse_trace_kinds,
)
from orfadc.cadence.stability_metrics import summarize_sampled_stability
from orfadc.config_loader import write_json
from orfadc.metric_contract import validate_metrics_payload


def extract_active_oa(
    psf_dir: Path,
    *,
    run_id: str,
    supply_voltage_v: float,
    supply_current_signal: str = "VDD:p",
    low_ghz: float = 0.1,
    high_ghz: float = 20.0,
    z0_ohm: float = 50.0,
    op_info_path: Path | None = None,
    device_instance: str | None = None,
    device_type: str | None = None,
    source_run_kind: str = "oa_generated_netlist_direct_spectre",
) -> tuple[list[dict[str, float]], dict]:
    if not math.isfinite(supply_voltage_v) or supply_voltage_v <= 0:
        raise ValueError("supply_voltage_v must be finite and positive")
    if not math.isfinite(z0_ohm) or z0_ohm <= 0:
        raise ValueError("z0_ohm must be finite and positive")
    if not run_id or not supply_current_signal:
        raise ValueError("run_id and supply_current_signal are required")
    if source_run_kind not in {
        "oa_generated_netlist_direct_spectre",
        "oa_netlist_derivative_ideal_matching_direct_spectre",
        "oa_netlist_derivative_bias_load_direct_spectre",
        "teaching_mos1_direct_spectre",
        "teaching_mos1_cascode_direct_spectre",
        "teaching_mos1_inductive_oa_netlist_direct_spectre",
    }:
        raise ValueError("unsupported source_run_kind for active OA extraction")

    dc = parse_dc_values(psf_dir / "dcOp.dc")
    if supply_current_signal not in dc:
        raise ValueError(f"missing supply current signal {supply_current_signal!r}")
    supply_current_ma = -dc[supply_current_signal] * 1e3
    if not math.isfinite(supply_current_ma) or supply_current_ma <= 0:
        raise ValueError("supply current must be finite and flow out of the positive supply")

    sp_path = psf_dir / "sp.sp"
    traces = {}
    complex_traces = {}
    frequency_traces = {}
    for signal in ("s11", "s21", "s12", "s22"):
        frequencies, values = parse_complex_trace(sp_path, signal)
        frequency_traces[signal] = frequencies
        complex_traces[signal] = values
        if signal != "s12":
            traces[signal] = (frequencies, magnitude_db(values))
    sp_frequencies = traces["s11"][0]
    if any(traces[signal][0] != sp_frequencies for signal in ("s21", "s22")):
        raise ValueError("S-parameter frequency grids differ")
    if frequency_traces["s12"] != sp_frequencies:
        raise ValueError("S12 frequency grid differs")

    noise_path = psf_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    required_kinds = {"NF": "dB", "NFmin": "dB", "F": "Noise factor", "Fmin": "Noise factor"}
    if any(kinds.get(name) != kind for name, kind in required_kinds.items()):
        raise ValueError("noise trace types must identify NF/NFmin as dB and F/Fmin as factors")
    noise_rows = noise_rows_from_psfascii(
        noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin"
    )
    sparameter_rows = [
        {
            "freq_hz": frequency,
            "freq_ghz": frequency / 1e9,
            "s11_db": traces["s11"][1][index],
            "s21_db": traces["s21"][1][index],
            "s22_db": traces["s22"][1][index],
        }
        for index, frequency in enumerate(sp_frequencies)
    ]
    require_same_frequency_grid(noise_rows, sparameter_rows)
    for factor_name, db_name in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        frequencies, factors = parse_scalar_trace(noise_path, factor_name, require_each_sweep=True)
        if len(frequencies) != len(noise_rows):
            raise ValueError(f"{factor_name} frequency grid differs")
        for frequency, factor, row in zip(frequencies, factors, noise_rows, strict=True):
            if not math.isclose(frequency, float(row["freq_hz"]), rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError(f"{factor_name} frequency grid differs")
            if not math.isfinite(factor) or factor <= 0 or not math.isclose(
                10 * math.log10(factor), float(row[db_name]), abs_tol=1e-6
            ):
                raise ValueError(f"{factor_name} disagrees with {db_name}")

    rows = [
        {**sparameter, "nf_db": float(noise["nf_db"]), "nfmin_db": float(noise["nfmin_db"])}
        for sparameter, noise in zip(sparameter_rows, noise_rows, strict=True)
    ]
    metrics = {
        **summarize_sparams(rows, low_ghz, high_ghz),
        **summarize_noise(noise_rows, low_ghz, high_ghz),
        "supply_current_ma": supply_current_ma,
        "supply_power_mw": supply_voltage_v * supply_current_ma,
    }
    stability = summarize_sampled_stability(
        *(complex_traces[signal] for signal in ("s11", "s21", "s12", "s22"))
    )
    payload = {
        "schema_version": 1,
        "status": "ok_with_warnings",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "raw_format": "psfascii",
        "source_run_kind": source_run_kind,
        "circuit_class": (
            "teaching_mos1_inductive_common_source"
            if source_run_kind == "teaching_mos1_inductive_oa_netlist_direct_spectre"
            else "active_common_source_smoke"
        ),
        "not_lna_result": True,
        "spec_pass": None,
        "spec": None,
        "candidate": None,
        "seed": None,
        "timeout_seconds": None,
        "run_id": run_id,
        "analysis": ["dc", "sp", "noise"],
        "frequency_band_ghz": {"low": low_ghz, "high": high_ghz},
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": z0_ohm},
        "reference_plane_evidence": (
            "declared_from_checked_testbench; not independently verified by parser"
            if source_run_kind == "oa_generated_netlist_direct_spectre"
            else "declared_from_checked_public_inductive_OA_netlist; not independently verified by parser"
            if source_run_kind == "teaching_mos1_inductive_oa_netlist_direct_spectre"
            else "declared_from_teaching_netlist; port connectivity reviewed; not independently verified by parser"
            if source_run_kind == "teaching_mos1_direct_spectre"
            else "declared_from_derived_netlist; port connectivity reviewed; not independently verified by parser"
        ),
        "units": {
            "s11_db": "dB", "s21_db": "dB", "s22_db": "dB", "ripple_db": "dB",
            "nf_db": "dB", "nfmin_db": "dB", "supply_current_ma": "mA",
            "supply_power_mw": "mW", "points_in_band": "count",
        },
        "metrics": metrics,
        "stability": stability,
        "points": len(rows),
        "warnings": (["MOS1 is an illustrative teaching model, not a foundry PDK or sign-off result"]
                     if source_run_kind in {
                         "teaching_mos1_direct_spectre",
                         "teaching_mos1_inductive_oa_netlist_direct_spectre",
                     }
                     else ["review Spectre log and PDK scalefactor warnings before sign-off"]),
    }
    if source_run_kind == "teaching_mos1_inductive_oa_netlist_direct_spectre":
        payload["model_kind"] = "teaching_model"
        payload["teaching_topology"] = "inductive"
    if not stability["unconditionally_stable_on_sampled_grid"]:
        payload["warnings"].append("unconditional two-port stability not established on sampled grid")
    if op_info_path is not None:
        if not device_instance or not device_type:
            raise ValueError("device_instance and device_type are required with op_info_path")
        op = parse_struct_values(op_info_path, instance=device_instance, struct_type=device_type)
        required_op = ("ids", "vgs", "vds", "vth", "vdsat", "gm", "gds")
        if any(name not in op or not math.isfinite(op[name]) for name in required_op):
            raise ValueError("required device operating-point fields must be finite")
        if op["ids"] <= 0 or op["gm"] <= 0 or op["gds"] <= 0:
            raise ValueError("device ids, gm and gds must be positive")
        payload["device_operating_point"] = {
            "instance": device_instance,
            "model_type": device_type,
            "ids_ma": op["ids"] * 1e3,
            "vgs_v": op["vgs"],
            "vds_v": op["vds"],
            "vth_v": op["vth"],
            "vdsat_v": op["vdsat"],
            "gm_ms": op["gm"] * 1e3,
            "gds_ms": op["gds"] * 1e3,
            "gm_over_id_per_v": op["gm"] / op["ids"],
            "ro_ohm": 1 / op["gds"],
            "vds_minus_vdsat_v": op["vds"] - op["vdsat"],
        }
    validate_metrics_payload(payload)
    return rows, payload


def write_active_oa_results(output_dir: Path, rows: list[dict[str, float]], payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "waveforms.csv"
    json_path = output_dir / "metrics.json"
    if csv_path.exists() or json_path.exists():
        raise FileExistsError("refusing to overwrite existing OA extraction results")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
        )
        writer.writeheader()
        writer.writerows(rows)
    write_json(json_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a non-LNA OA netlist Spectre smoke result")
    parser.add_argument("--psf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--supply-voltage-v", type=float, required=True)
    parser.add_argument("--supply-current-signal", default="VDD:p")
    parser.add_argument("--low-ghz", type=float, default=0.1)
    parser.add_argument("--high-ghz", type=float, default=20.0)
    parser.add_argument("--z0-ohm", type=float, default=50.0)
    parser.add_argument("--op-info-path", type=Path)
    parser.add_argument("--device-instance")
    parser.add_argument("--device-type")
    parser.add_argument(
        "--source-run-kind",
        choices=(
            "oa_generated_netlist_direct_spectre",
            "oa_netlist_derivative_ideal_matching_direct_spectre",
            "oa_netlist_derivative_bias_load_direct_spectre",
            "teaching_mos1_inductive_oa_netlist_direct_spectre",
        ),
        default="oa_generated_netlist_direct_spectre",
    )
    args = parser.parse_args()
    try:
        rows, payload = extract_active_oa(
            args.psf_dir,
            run_id=args.run_id,
            supply_voltage_v=args.supply_voltage_v,
            supply_current_signal=args.supply_current_signal,
            low_ghz=args.low_ghz,
            high_ghz=args.high_ghz,
            z0_ohm=args.z0_ohm,
            op_info_path=args.op_info_path,
            device_instance=args.device_instance,
            device_type=args.device_type,
            source_run_kind=args.source_run_kind,
        )
        write_active_oa_results(args.output_dir, rows, payload)
    except (OSError, ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"status={payload['status']} points={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
