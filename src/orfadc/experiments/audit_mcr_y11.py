from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.experiments.run_mcr_calibration import render_mcr_netlist
from orfadc.tools.mcr_lumped import symmetric_parallel_mcr
from orfadc.tools.mcr_model import MCRParameters, paper_equation_3, y11_dimensional_candidate


def audit_mcr_y11(run_dir: Path) -> dict:
    """Compare archived ideal AC port admittance with printed and candidate Y11."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("MCR run directory must exist and must not be a symlink")
    evidence = read_evidenced_metrics(run_dir)
    if (
        evidence.get("status") != "ok"
        or evidence.get("simulation_status") != "ok"
        or evidence.get("source") != "cadence_spectre"
        or evidence.get("circuit_class") != "ideal_passive_mcr"
        or evidence.get("not_lna_result") is not True
        or evidence.get("spec_pass") is not None
        or evidence.get("run_id") != run_dir.name
        or evidence.get("calibration_pass") is not True
    ):
        raise ValueError("run is not a successful, verified ideal MCR calibration")
    manifest_path = run_dir / "evidence_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("symlinked MCR manifest is not accepted")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_entry = manifest.get("artifacts", {}).get("ac_raw")
    if not isinstance(raw_entry, dict) or raw_entry.get("path") != "ac.ac":
        raise ValueError("AC raw data are not in the verified manifest")
    p = evidence.get("parameters")
    if not isinstance(p, dict):
        raise ValueError("MCR parameters are missing")
    model = symmetric_parallel_mcr(
        2 * math.pi * p["f0_ghz"] * 1e9, p["q0"], p["capacitance_ff"] * 1e-15,
        p["coupling_k"],
    )
    if not math.isclose(p["resistance_ohm"], model.resistance_ohm, rel_tol=1e-12):
        raise ValueError("archived resistance disagrees with MCR configuration")
    start_hz, stop_hz = p["start_ghz"] * 1e9, p["stop_ghz"] * 1e9
    if (run_dir / "netlist.scs").read_text(encoding="ascii") != render_mcr_netlist(
        model, start_hz, stop_hz, p["points"]
    ):
        raise ValueError("archived netlist disagrees with the ideal MCR testbench")
    params = MCRParameters(
        coupling_k=model.coupling_k,
        omega0_rad_s=2 * math.pi * p["f0_ghz"] * 1e9,
        q0=p["q0"], source_resistance_ohm=model.resistance_ohm,
        output_resistance_ohm=model.resistance_ohm,
        source_capacitance_f=model.capacitance_f, gm_s=1.0,
    )
    frequencies, voltages = parse_complex_trace(run_dir / "ac.ac", "n1")
    if len(frequencies) != p["points"] or not frequencies or any(value == 0 for value in voltages):
        raise ValueError("archived AC input trace is incomplete")
    printed_errors, candidate_errors, scale = [], [], 0.0
    for index, (frequency, voltage) in enumerate(zip(frequencies, voltages, strict=True)):
        expected_frequency = start_hz + (stop_hz - start_hz) * index / (p["points"] - 1)
        if not math.isclose(frequency, expected_frequency, rel_tol=1e-9, abs_tol=1e-3):
            raise ValueError("archived AC frequency grid disagrees with the netlist")
        measured = 1 / voltage  # The archived netlist injects 1 A into n1.
        printed = paper_equation_3(frequency, params).y11_s
        candidate = y11_dimensional_candidate(frequency, params)
        printed_errors.append(abs(measured - printed))
        candidate_errors.append(abs(measured - candidate))
        scale = max(scale, abs(measured))
    if scale == 0:
        raise ValueError("zero AC admittance scale")
    return {
        "run_id": run_dir.name,
        "source": "cadence_spectre",
        "circuit_class": "ideal_passive_mcr",
        "not_lna_result": True,
        "points_verified": len(frequencies),
        "printed_y11_max_error_s": max(printed_errors),
        "candidate_y11_max_error_s": max(candidate_errors),
        "printed_y11_max_error_normalized": max(printed_errors) / scale,
        "candidate_y11_max_error_normalized": max(candidate_errors) / scale,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only archived ideal MCR Y11 equation audit")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        report = audit_mcr_y11(args.run_dir)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(f"MCR Y11 audit failed: {type(exc).__name__}: {exc}")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
