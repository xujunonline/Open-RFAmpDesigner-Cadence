from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.passive_quality import oneport_impedance, summarize_inductor_oneport
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.cadence.touchstone import parse_touchstone_1port
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_TEMPLATE = Path(__file__).resolve().parents[3] / "circuit/spectre/teaching_inductor_quality.scs"
_ARTIFACTS = {
    "metrics": "metrics.json", "netlist": "netlist.scs", "remote_netlist": "remote_netlist.scs",
    "spectre_log": "spectre.log", "stdout": "stdout.log", "stderr": "stderr.log",
    "sp_raw": "sp.sp", "touchstone": "teaching_inductor_quality.s1p", "waveforms": "quality.csv",
}
_COLUMNS = ("freq_hz", "s11_real", "s11_imag", "z_real_ohm", "z_imag_ohm", "q", "l_effective_h")


def extract_passive_quality_reference(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("passive quality archive must be an ordinary directory")
    source = _TEMPLATE.read_bytes()
    if (run_dir / "netlist.scs").read_bytes() != source or (run_dir / "remote_netlist.scs").read_bytes() != source:
        raise ValueError("passive quality local and executed netlists differ from public reference")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if (not re.search(r"spectre completes with 0 errors,\s*0 warnings", log)
            or not re.search(r"^Reading file:\s+\S+/netlist\.scs$", log, re.MULTILINE)):
        raise ValueError("passive quality Spectre log is not clean")
    frequency, reflection = parse_complex_trace(run_dir / "sp.sp", "s11")
    touchstone = parse_touchstone_1port(run_dir / "teaching_inductor_quality.s1p")
    if (len(frequency) != 591 or len(touchstone) != len(frequency)
            or not math.isclose(frequency[0], 0.5e9, rel_tol=1e-12)
            or not math.isclose(frequency[-1], 30e9, rel_tol=1e-12)):
        raise ValueError("passive quality frequency grid is incomplete")
    rows = []
    maximum_touchstone_delta = 0.0
    maximum_analytic_relative_error = 0.0
    for sample, gamma, stone in zip(frequency, reflection, touchstone, strict=True):
        if stone["reference_ohm"] != 50 or not math.isclose(stone["freq_hz"], sample, rel_tol=1e-10):
            raise ValueError("passive quality port reference or frequency differs")
        maximum_touchstone_delta = max(
            maximum_touchstone_delta,
            abs(gamma - complex(stone["s11_real"], stone["s11_imag"])),
        )
        impedance = oneport_impedance(gamma, 50)
        omega = 2 * math.pi * sample
        series = 2 + 1j * omega * 1e-9
        analytic = 1 / (1 / series + 1j * omega * 100e-15)
        maximum_analytic_relative_error = max(
            maximum_analytic_relative_error, abs(impedance - analytic) / max(abs(analytic), 1e-30),
        )
        rows.append({
            "freq_hz": sample, "s11_real": gamma.real, "s11_imag": gamma.imag,
            "z_real_ohm": impedance.real, "z_imag_ohm": impedance.imag,
            "q": impedance.imag / impedance.real,
            "l_effective_h": impedance.imag / omega,
        })
    if maximum_touchstone_delta > 1e-8 or maximum_analytic_relative_error > 1e-5:
        raise ValueError("passive quality PSF/Touchstone or analytic reference differs")
    screen = summarize_inductor_oneport(
        frequency, reflection, reference_ohm=50,
        band_low_hz=8e9, band_high_hz=12e9,
        minimum_q=15, minimum_srf_ratio=1.2,
    )
    payload = {
        "schema_version": 1, "status": "reference_calibrated", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "teaching_lossy_rlc_oneport",
        "circuit_class": "passive_oneport", "model_kind": "teaching_lumped_reference",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "public R-L shunt-C one-port quality extraction calibration; not a PDK passive",
        "analysis": ["sp"], "oneport_reference_ohm": 50.0,
        "physical_qualification": False, "coupling_qualification": False,
        "points": len(rows), "metrics": screen,
        "maximum_touchstone_psfascii_complex_delta": maximum_touchstone_delta,
        "maximum_analytic_impedance_relative_error": maximum_analytic_relative_error,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_passive_quality_reference(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("passive quality evidence lacks required artifacts")
    rows, rebuilt = extract_passive_quality_reference(run_dir)
    if saved != rebuilt:
        raise ValueError("passive quality metrics differ from raw Spectre output")
    with (run_dir / "quality.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("passive quality CSV columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(item[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for item, row in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("passive quality CSV differs from raw Spectre output")
    return {"status": "verified", "run_id": run_dir.name,
            "physical_qualification": False, "not_lna_result": True}


def finalize_passive_quality_reference(run_dir: Path) -> dict:
    _require_private_path(run_dir)
    rows, payload = extract_passive_quality_reference(run_dir)
    with (run_dir / "quality.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(run_dir / "metrics.json", payload)
    write_evidence_manifest(run_dir, _ARTIFACTS)
    audit_passive_quality_reference(run_dir)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize/audit public one-port passive quality reference")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        finalize_passive_quality_reference(args.run_dir)
    result = audit_passive_quality_reference(args.run_dir)
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
