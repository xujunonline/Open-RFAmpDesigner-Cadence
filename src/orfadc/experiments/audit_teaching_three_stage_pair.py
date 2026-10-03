from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.ocean_ascii import read_ocnprint_trace
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage_hb import audit_teaching_three_stage_hb
from orfadc.experiments.audit_teaching_three_stage_oa import (
    _components, audit_teaching_three_stage_oa,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_DEFAULT_DIRECT = _PRIVATE_ROOT / "teaching_three_stage/probe_7eecbf34a74a"


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("three-stage pair source file is missing or symlinked")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_circuit(oa_netlist: str, hb_netlist: str) -> None:
    oa = _components(oa_netlist)
    hb = _components(hb_netlist)
    if set(oa) != set(hb) or len(oa) != 47:
        raise ValueError("three-stage pair component identities differ")
    for name in oa:
        if name not in {"PORT1", "PORT2"} and oa[name] != hb[name]:
            raise ValueError(f"three-stage pair circuit component differs: {name}")
    if (oa["PORT1"] != "PORT1 (in 0) port r=50 num=1 type=sine"
            or hb["PORT1"] != "PORT1 (in 0) port r=50 num=1 type=sine dbm=-70 freq=10000000000"
            or oa["PORT2"] != "PORT2 (outp outn) port r=1787 num=2 type=sine"
            or hb["PORT2"] != "PORT2 (outp outn) port r=1787 num=2"):
        raise ValueError("three-stage pair changes port references beyond the approved HB stimulus")


def build_three_stage_pair(oa_dir: Path, hb_dir: Path, direct_dir: Path, run_id: str) -> dict:
    if any(not path.is_dir() or path.is_symlink() for path in (oa_dir, hb_dir, direct_dir)):
        raise ValueError("three-stage pair sources must be ordinary directories")
    audit_teaching_three_stage_oa(oa_dir, direct_dir)
    audit_teaching_three_stage_hb(hb_dir)
    oa = read_evidenced_metrics(oa_dir)
    hb = read_evidenced_metrics(hb_dir)
    if (oa.get("source_run_kind") != "teaching_mos1_three_stage_oa_ocean"
            or hb.get("source_run_kind") != "teaching_mos1_three_stage_hb_low_drive"
            or oa.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}
            or hb.get("port_reference_ohm") != oa["port_reference_ohm"]
            or hb.get("parameters") != {"input_dbm": -70.0, "output_secondary_nh": 1.0,
                                         "frequency_ghz": 10.0, "harmonics": 7}):
        raise ValueError("three-stage OA/HB contexts are incompatible")
    _same_circuit(
        (oa_dir / "netlist.scs").read_text(encoding="utf-8"),
        (hb_dir / "netlist.scs").read_text(encoding="ascii"),
    )
    if (oa_dir / "teaching_mos1_model.scs").read_bytes() != (
        hb_dir / "teaching_mos1_model.scs"
    ).read_bytes():
        raise ValueError("three-stage OA/HB use different public MOS1 models")
    maximum_s_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid_real, real = read_ocnprint_trace(
            oa_dir / f"ocnprint/{signal}_real.txt", header_fragment=f'real(getData("{signal}"',
        )
        grid_imag, imag = read_ocnprint_trace(
            oa_dir / f"ocnprint/{signal}_imag.txt", header_fragment=f'imag(getData("{signal}"',
        )
        grid_hb, hb_values = parse_complex_trace(hb_dir / "sp.sp", signal)
        if grid_real != grid_hb or grid_imag != grid_hb:
            raise ValueError("three-stage OA/HB small-signal frequency grids differ")
        maximum_s_delta = max(maximum_s_delta, *(
            abs(complex(r, i) - value)
            for r, i, value in zip(real, imag, hb_values, strict=True)
        ))
    if maximum_s_delta > 1e-8:
        raise ValueError("three-stage OA/HB small-signal S disagree")
    for key in ("s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db", "ripple_db", "supply_current_ma"):
        if not math.isclose(oa["metrics"][key], hb["metrics"][key], rel_tol=1e-5, abs_tol=1e-8):
            raise ValueError(f"three-stage OA/HB metric differs: {key}")
    if abs(hb["metrics"]["hb_minus_s21_db"]) > 0.01:
        raise ValueError("three-stage HB is not in the low-drive linear range")
    report = {
        "schema_version": 1, "status": "verified_same_circuit_incomplete_fullchain",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "same public MOS1 three-stage OA small signal and low-drive HB; no compression or qualified LNA",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "oa_run_id": oa_dir.name, "hb_run_id": hb_dir.name, "direct_reference_run_id": direct_dir.name,
        "oa_manifest_sha256": _sha256(oa_dir / "evidence_manifest.json"),
        "hb_manifest_sha256": _sha256(hb_dir / "evidence_manifest.json"),
        "direct_manifest_sha256": _sha256(direct_dir / "evidence_manifest.json"),
        "same_circuit_except_hb_stimulus": True,
        "same_public_model": True,
        "maximum_oa_hb_complex_s_delta": maximum_s_delta,
        "compression_status": "not_measured",
        "metrics": {
            **oa["metrics"],
            "low_drive_hb_input_dbm": hb["metrics"]["input_available_power_dbm"],
            "low_drive_hb_output_dbm": hb["metrics"]["output_power_dbm"],
            "low_drive_hb_gain_db": hb["metrics"]["power_gain_db"],
            "low_drive_hb_minus_s21_db": hb["metrics"]["hb_minus_s21_db"],
        },
    }
    validate_metrics_payload(report)
    return report


def audit_three_stage_pair_report(report_dir: Path, oa_dir: Path, hb_dir: Path, direct_dir: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("three-stage pair report is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    rebuilt = build_three_stage_pair(oa_dir, hb_dir, direct_dir, report_dir.name)
    if saved != rebuilt:
        raise ValueError("three-stage pair report differs from source archives")
    return {"status": "verified", "run_id": report_dir.name,
            "compression_status": "not_measured", "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit public MOS1 three-stage OA/HB same-circuit evidence")
    parser.add_argument("oa_dir", type=Path)
    parser.add_argument("hb_dir", type=Path)
    parser.add_argument("--direct-dir", type=Path, default=_DEFAULT_DIRECT)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_pairs")
    args = parser.parse_args()
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    report = build_three_stage_pair(args.oa_dir, args.hb_dir, args.direct_dir, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
    result = audit_three_stage_pair_report(report_dir, args.oa_dir, args.hb_dir, args.direct_dir)
    print(f"status={result['status']} compression={result['compression_status']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
