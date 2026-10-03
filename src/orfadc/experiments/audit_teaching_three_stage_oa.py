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
from orfadc.cadence.noise_metrics import summarize_noise
from orfadc.cadence.ocean_ascii import (
    read_ocnprint_trace, read_ocean_device_op, read_ocean_rf_data, read_ocean_vdd_current,
)
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = {
    "create": _ROOT / "circuit/ocean/create_teaching_three_stage_oa.ocn",
    "run": _ROOT / "circuit/ocean/run_teaching_mos1_oa.ocn",
    "export": _ROOT / "circuit/ocean/export_teaching_three_stage_oa.ocn",
}
_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "schematic": "sch.oa",
    "schematic_check": "schematic_check.txt", "netlist": "netlist.scs", "ade": "ade_e.scs",
    "public_model": "teaching_mos1_model.scs", "remote_model": "remote_teaching_mos1_model.scs",
    "create_script": "create_teaching_three_stage_oa.ocn",
    "remote_create_script": "remote_create_teaching_three_stage_oa.ocn",
    "run_script": "run_teaching_mos1_oa.ocn", "remote_run_script": "remote_run_teaching_mos1_oa.ocn",
    "export_script": "export_teaching_three_stage_oa.ocn",
    "remote_export_script": "remote_export_teaching_three_stage_oa.ocn",
    "ocean_create_log": "ocean_create.log", "ocean_run_log": "ocean_run.log",
    "ocean_export_log": "ocean_export.log", "spectre_log": "spectre.out",
    "ocean_run_report": "ocean_run_report.txt", "dc_raw": "dcOp.dc",
    "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
    "ocean_export_report": "ocnprint/teaching_three_stage_export_report.txt",
    "device_op": "ocnprint/device_op.txt",
}
for _signal in ("s11", "s21", "s12", "s22"):
    for _part in ("real", "imag"):
        _ARTIFACTS[f"{_signal}_{_part}"] = f"ocnprint/{_signal}_{_part}.txt"
for _signal in ("NF", "NFmin", "F", "Fmin"):
    _ARTIFACTS[f"noise_{_signal.lower()}"] = f"ocnprint/{_signal}.txt"

_SOURCE_DC = {
    "VDD": "1.2", "VBIAS1": "0.65", "VCAS": "1.05", "VBIAS2": "0.65", "VBIAS3": "0.65",
}
_ELEMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s+(?:\(|mutual_inductor\b)")
_INSTANCES = tuple(f"M{index}" for index in range(1, 7))
_OP_FIELDS = ("id", "vgs", "vds", "vdsat", "gm", "gds", "cgs", "cgd")


def _components(netlist: str) -> dict[str, str]:
    elements: dict[str, str] = {}
    for line in netlist.splitlines():
        match = _ELEMENT_RE.match(line)
        if not match:
            continue
        name = match[1]
        if name in elements:
            raise ValueError(f"duplicate three-stage component: {name}")
        normalized = " ".join(line.split()).replace(" type=dc", "")
        for parameter, value in _SOURCE_DC.items():
            normalized = normalized.replace(f"dc={parameter}", f"dc={value}")
        elements[name] = normalized
    return elements


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_teaching_three_stage_oa(
    run_dir: Path, direct_dir: Path,
) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("three-stage OA source must be an ordinary directory")
    direct_audit = audit_teaching_three_stage(direct_dir)
    if direct_audit["points"] != 161:
        raise ValueError("direct Spectre reference grid differs")
    direct = read_evidenced_metrics(direct_dir)
    if direct.get("design_parameters") or direct.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}:
        raise ValueError("direct Spectre reference is not the baseline topology")
    for kind, source in _SCRIPTS.items():
        if (run_dir / source.name).read_bytes() != source.read_bytes() or (
            run_dir / f"remote_{source.name}"
        ).read_bytes() != source.read_bytes():
            raise ValueError(f"three-stage OA {kind} script differs from remote execution")
    if ((run_dir / "teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()
            or (run_dir / "remote_teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()):
        raise ValueError("three-stage OA public model differs from remote execution")
    if (run_dir / "sch.oa").stat().st_size == 0:
        raise ValueError("three-stage OA schematic view is empty")
    check = (run_dir / "schematic_check.txt").read_text(encoding="utf-8")
    if ("check_return=(0 0)" not in check or "save_return=t instances=64 nets=26" not in check
            or len(re.findall(r"^net=", check, re.MULTILINE)) != 26):
        raise ValueError("three-stage OA schematic check or net count differs")
    expected = _components(render_teaching_three_stage().decode("ascii"))
    actual = _components((run_dir / "netlist.scs").read_text(encoding="utf-8"))
    if len(expected) != 47 or actual != expected:
        raise ValueError("three-stage OA netlist components differ from direct public topology")
    log = (run_dir / "spectre.out").read_text(encoding="utf-8", errors="replace")
    if (not re.search(r"spectre completes with 0 errors,\s*0 warnings", log)
            or not re.search(r"^Reading file:\s+\S+/input\.scs$", log, re.MULTILINE)
            or "SPECTRE-25" in log):
        raise ValueError("three-stage OA Spectre log is not clean")
    for path in ("ocean_create.log", "ocean_run.log", "ocean_export.log"):
        content = (run_dir / path).read_text(encoding="utf-8", errors="replace")
        if "*Error*" in content or "ERROR" in content:
            raise ValueError(f"three-stage OA {path} contains an error")
    run_report = (run_dir / "ocean_run_report.txt").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r'run_result="([^"]+/results)"', run_report)
    if not match:
        raise ValueError("three-stage OA result path is missing")
    psf = match[1] + "/psf"
    export_report = run_dir / "ocnprint/teaching_three_stage_export_report.txt"
    if "sp_outputs=" not in export_report.read_text(encoding="utf-8") or (
        f'?resultsDir "{psf}"' not in (run_dir / "ocnprint/s11_real.txt").read_text(encoding="utf-8")
    ):
        raise ValueError("three-stage OA export source differs from OCEAN run")
    rows, stability = read_ocean_rf_data(run_dir / "ocnprint", frequency_rel_tol=1e-12)
    if len(rows) != 161 or rows[0]["freq_hz"] != 8e9 or rows[-1]["freq_hz"] != 12e9 or stability is None:
        raise ValueError("three-stage OA S/noise export grid is incomplete")
    maximum_s_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        real_grid, real = read_ocnprint_trace(
            run_dir / f"ocnprint/{signal}_real.txt", header_fragment=f'real(getData("{signal}"',
        )
        imag_grid, imag = read_ocnprint_trace(
            run_dir / f"ocnprint/{signal}_imag.txt", header_fragment=f'imag(getData("{signal}"',
        )
        direct_grid, direct_values = parse_complex_trace(direct_dir / "sp.sp", signal)
        for grid in (real_grid, imag_grid):
            if len(grid) != len(direct_grid) or any(
                not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-3)
                for left, right in zip(grid, direct_grid, strict=True)
            ):
                raise ValueError("three-stage OA and direct Spectre S grids differ")
        maximum_s_delta = max(maximum_s_delta, *(
            abs(complex(r, i) - reference)
            for r, i, reference in zip(real, imag, direct_values, strict=True)
        ))
    if maximum_s_delta > 1e-8:
        raise ValueError("three-stage OA and direct Spectre complex S differ")
    with (direct_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        direct_rows = list(csv.DictReader(stream))
    if len(direct_rows) != len(rows):
        raise ValueError("three-stage OA and direct Spectre waveform count differs")
    maximum_noise_delta = max(
        abs(row[key] - float(reference[key]))
        for row, reference in zip(rows, direct_rows, strict=True)
        for key in ("nf_db", "nfmin_db")
    )
    if maximum_noise_delta > 1e-6:
        raise ValueError("three-stage OA and direct Spectre noise differ")
    device_op = read_ocean_device_op(
        run_dir / "ocnprint/device_op.txt", expected_psf=psf, instances=_INSTANCES,
    )
    maximum_op_delta = 0.0
    for instance in _INSTANCES:
        reference = direct["device_op"][instance]
        for field in _OP_FIELDS:
            value = device_op[instance][field]
            expected_value = reference["ids" if field == "id" else field]
            if not math.isclose(value, expected_value, rel_tol=1e-6, abs_tol=1e-18):
                raise ValueError("three-stage OA and direct Spectre MOS operating points differ")
            maximum_op_delta = max(maximum_op_delta, abs(value - expected_value))
    current = read_ocean_vdd_current(export_report)
    if not math.isclose(current, direct["metrics"]["supply_current_ma"], rel_tol=1e-5):
        raise ValueError("three-stage OA and direct Spectre supply current differs")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(rows, 8.0, 12.0),
        "supply_current_ma": current, "supply_power_mw": 1.2 * current,
    }
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "teaching_mos1_three_stage_oa_ocean",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "public MOS1 three-stage OA/OCEAN crosscheck; not a qualified LNA or paper result",
        "analysis": ["dc", "op_info", "sp", "noise"], "points": 161,
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "load_capacitance_ff": 62.0, "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": metrics, "stability": stability, "device_op": device_op,
        "direct_source_run_id": direct_dir.name,
        "direct_source_manifest_sha256": _sha256(direct_dir / "evidence_manifest.json"),
        "maximum_oa_direct_complex_s_delta": maximum_s_delta,
        "maximum_oa_direct_noise_db_delta": maximum_noise_delta,
        "maximum_oa_direct_device_op_absolute_delta": maximum_op_delta,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_teaching_three_stage_oa(run_dir: Path, direct_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("three-stage OA evidence lacks required artifacts")
    rows, rebuilt = extract_teaching_three_stage_oa(run_dir, direct_dir)
    if saved != rebuilt:
        raise ValueError("three-stage OA metrics differ from source archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("three-stage OA waveform columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(item[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for item, row in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("three-stage OA waveform CSV differs from OCEAN source")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a public MOS1 three-stage OA/OCEAN crosscheck")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("direct_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_teaching_three_stage_oa(args.run_dir, args.direct_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_teaching_three_stage_oa(args.run_dir, args.direct_dir)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
