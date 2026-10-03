from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.experiments.audit_mcr_y11 import audit_mcr_y11
from orfadc.experiments.run_mcr_calibration import render_mcr_netlist
from orfadc.tools.mcr_lumped import lumped_mcr_response, symmetric_parallel_mcr


def _archive(root: Path) -> Path:
    run = root / "mcr001"
    run.mkdir()
    model = symmetric_parallel_mcr(2 * math.pi * 30e9, 3.0, 100e-15, 0.4)
    (run / "netlist.scs").write_text(render_mcr_netlist(model, 20e9, 40e9, 3), encoding="ascii")
    (run / "spectre.log").write_text("spectre completes with 0 errors", encoding="ascii")
    lines = ["VALUE"]
    for frequency in (20e9, 30e9, 40e9):
        voltage = 1 / lumped_mcr_response(frequency, model).input_admittance_s
        lines.extend((f'"freq" {frequency:.17g}',
                      f'"n1" ({voltage.real:.17g} {voltage.imag:.17g})'))
    lines.append("END")
    (run / "ac.ac").write_text("\n".join(lines) + "\n", encoding="ascii")
    (run / "metrics.json").write_text(json.dumps({
        "schema_version": 1, "status": "ok", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "ideal_passive_mcr",
        "not_lna_result": True, "spec_pass": None, "run_id": run.name,
        "calibration_pass": True,
        "parameters": {
            "f0_ghz": 30.0, "q0": 3.0, "capacitance_ff": 100.0,
            "coupling_k": 0.4, "start_ghz": 20.0, "stop_ghz": 40.0,
            "points": 3, "resistance_ohm": model.resistance_ohm,
        },
        "metrics": {"max_z21_error_ohm": 0.0},
    }), encoding="utf-8")
    write_evidence_manifest(run, {
        "metrics": "metrics.json", "netlist": "netlist.scs",
        "spectre_log": "spectre.log", "ac_raw": "ac.ac",
    })
    return run


def test_y11_audit_compares_both_equations_to_raw_ac(tmp_path: Path) -> None:
    report = audit_mcr_y11(_archive(tmp_path))
    assert report["points_verified"] == 3
    assert report["candidate_y11_max_error_normalized"] < 1e-12
    assert report["printed_y11_max_error_normalized"] > 1
    assert report["not_lna_result"] is True


def test_y11_audit_rejects_unverified_raw_change(tmp_path: Path) -> None:
    run = _archive(tmp_path)
    raw = run / "ac.ac"
    raw.write_text(raw.read_text(encoding="ascii") + "changed", encoding="ascii")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        audit_mcr_y11(run)
