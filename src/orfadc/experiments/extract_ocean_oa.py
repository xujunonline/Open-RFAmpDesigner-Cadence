from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import summarize_noise
from orfadc.cadence.ocean_ascii import read_ocean_rf_data, read_ocean_vdd_current
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.metric_contract import validate_metrics_payload


def extract_ocean_oa(
    export_dir: Path,
    *,
    ocean_log: Path,
    spectre_log: Path,
    run_id: str,
    supply_voltage_v: float,
    low_ghz: float = 0.1,
    high_ghz: float = 20.0,
    z0_ohm: float = 50.0,
    teaching_model: bool = False,
    teaching_topology: str = "flat",
    ocn_precision_digits: int = 6,
) -> tuple[list[dict[str, float]], dict]:
    if not run_id or not math.isfinite(supply_voltage_v) or supply_voltage_v <= 0:
        raise ValueError("run_id and positive finite supply voltage are required")
    if not math.isfinite(z0_ohm) or z0_ohm <= 0:
        raise ValueError("z0_ohm must be finite and positive")
    if type(teaching_model) is not bool:
        raise ValueError("teaching_model must be a boolean")
    if teaching_topology not in {"flat", "inductive", "damped", "cascode"} or (not teaching_model and teaching_topology != "flat"):
        raise ValueError("teaching_topology requires the public teaching model")
    if type(ocn_precision_digits) is not int or ocn_precision_digits not in {6, 15}:
        raise ValueError("ocn_precision_digits must be 6 or 15")
    ocean_text = ocean_log.read_text(encoding="utf-8")
    spectre_text = spectre_log.read_text(encoding="utf-8")
    if "ADE-3071" not in ocean_text or "Simulation completed successfully" not in ocean_text:
        raise ValueError("OCEAN log lacks ADE completion evidence")
    if "spectre completes with 0 errors" not in spectre_text or "SPECTRE-25" in spectre_text:
        raise ValueError("Spectre log lacks clean completion evidence")

    if ocn_precision_digits == 15:
        for name in (
            *(f"{signal}_{component}.txt" for signal in ("s11", "s21", "s12", "s22")
              for component in ("real", "imag")),
            "NF.txt", "NFmin.txt", "F.txt", "Fmin.txt",
        ):
            lines = (export_dir / name).read_text(encoding="utf-8").splitlines()
            if not any(
                len(fields := line.split()) == 2 and re.search(r"\.\d{13,}[eE]", fields[1])
                for line in lines
            ):
                raise ValueError(f"{name} lacks 15-digit OCEAN export evidence")
    rows, stability = read_ocean_rf_data(
        export_dir, frequency_rel_tol=1e-12 if ocn_precision_digits == 15 else 5e-6,
    )
    supply_current_ma = read_ocean_vdd_current(export_dir / "report.txt")
    metrics = {
        **summarize_sparams(rows, low_ghz, high_ghz),
        **summarize_noise(rows, low_ghz, high_ghz),
        "supply_current_ma": supply_current_ma,
        "supply_power_mw": supply_voltage_v * supply_current_ma,
    }
    payload = {
        "schema_version": 1,
        "status": "ok_with_warnings",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "raw_format": "ocean_ocnprint_from_psfxl",
        "source_run_kind": (
            ({"flat": "teaching_mos1_oa_ocean_classic_batch",
              "inductive": "teaching_mos1_inductive_oa_ocean_classic_batch",
              "damped": "teaching_mos1_damped_oa_ocean_classic_batch",
              "cascode": "teaching_mos1_cascode_oa_ocean_classic_batch"}[teaching_topology]) if teaching_model
            else "oa_schematic_ocean_classic_batch"
        ),
        "circuit_class": (
            {"flat": "teaching_mos1_common_source",
             "inductive": "teaching_mos1_inductive_common_source",
             "damped": "teaching_mos1_damped_common_source",
             "cascode": "teaching_mos1_cascode"}[teaching_topology]
        ) if teaching_model else "active_common_source_smoke",
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
            "declared_from_checked_public_teaching_OA_testbench; not independently verified by parser"
            if teaching_model else "declared_from_checked_OA_testbench; not independently verified by parser"
        ),
        "units": {
            "s11_db": "dB", "s21_db": "dB", "s22_db": "dB", "ripple_db": "dB",
            "nf_db": "dB", "nfmin_db": "dB", "supply_current_ma": "mA",
            "supply_power_mw": "mW", "points_in_band": "count",
        },
        "metrics": metrics,
        "stability": stability,
        "points": len(rows),
        "ocn_precision_digits": ocn_precision_digits,
        "warnings": [
            "MOS1 is an illustrative teaching model, not a foundry PDK or sign-off result"
            if teaching_model else "review Spectre log and PDK scalefactor warnings before sign-off",
            *(["ocnPrint default six-digit output limits waveform precision"]
              if ocn_precision_digits == 6 else []),
        ],
    }
    if teaching_model:
        payload["model_kind"] = "teaching_model"
        payload["teaching_topology"] = teaching_topology
    if stability is None:
        payload["stability_quality"] = "unavailable_without_s12"
        payload["warnings"].append("S12 was not exported; sampled-grid stability is unavailable")
    elif ocn_precision_digits == 6:
        payload["stability_quality"] = "insufficient_export_precision"
        payload["warnings"].append("six-digit complex S export cannot resolve near-boundary Rollett K")
    elif not stability["unconditionally_stable_on_sampled_grid"]:
        payload["stability_quality"] = "fails_sampled_grid"
        payload["warnings"].append("unconditional two-port stability not established on sampled grid")
    elif stability["minimum_k"] is not None and stability["minimum_k"] < 1.001:
        payload["stability_quality"] = "near_boundary_on_sampled_grid"
        payload["warnings"].append("Rollett K is near unity; sampled-grid result is not an engineering stability sign-off")
    else:
        payload["stability_quality"] = "sampled_grid_only"
    validate_metrics_payload(payload)
    return rows, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract an OA common-source OCEAN/PSFXL smoke result")
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--ocean-log", type=Path, required=True)
    parser.add_argument("--spectre-log", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--supply-voltage-v", type=float, required=True)
    parser.add_argument("--low-ghz", type=float, default=0.1)
    parser.add_argument("--high-ghz", type=float, default=20.0)
    parser.add_argument("--z0-ohm", type=float, default=50.0)
    parser.add_argument("--teaching-model", action="store_true")
    parser.add_argument("--teaching-topology", choices=("flat", "inductive"), default="flat")
    parser.add_argument("--ocn-precision-digits", type=int, choices=(6, 15), default=6)
    args = parser.parse_args()
    try:
        rows, payload = extract_ocean_oa(
            args.export_dir,
            ocean_log=args.ocean_log,
            spectre_log=args.spectre_log,
            run_id=args.run_id,
            supply_voltage_v=args.supply_voltage_v,
            low_ghz=args.low_ghz,
            high_ghz=args.high_ghz,
            z0_ohm=args.z0_ohm,
            teaching_model=args.teaching_model,
            teaching_topology=args.teaching_topology,
            ocn_precision_digits=args.ocn_precision_digits,
        )
        write_active_oa_results(args.output_dir, rows, payload)
    except (OSError, ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"status={payload['status']} points={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
