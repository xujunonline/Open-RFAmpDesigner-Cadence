from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage_hb import audit_teaching_three_stage_hb
from orfadc.experiments.audit_teaching_three_stage_hb_sweep import _SIGNALS, _source_dirs
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_HARMONICS = (7, 9, 11)
_POWERS = (-13.2, -12.5)


def build_three_stage_harmonic_comparison(hb_root: Path, ids: list[str], run_id: str) -> dict:
    if not isinstance(ids, list) or len(ids) != 6:
        raise ValueError("three-stage harmonic comparison requires six source runs")
    sources = _source_dirs(hb_root, ids)
    points = []
    reference_traces = {}
    model_hash = None
    for index, source_dir in enumerate(sources):
        audit_teaching_three_stage_hb(source_dir)
        point = read_evidenced_metrics(source_dir)
        parameters = point["parameters"]
        expected_power = _POWERS[index // 3]
        expected_harmonics = _HARMONICS[index % 3]
        if (not math.isclose(parameters["input_dbm"], expected_power, rel_tol=0, abs_tol=1e-12)
                or parameters["harmonics"] != expected_harmonics
                or parameters["output_secondary_nh"] != 1.0
                or parameters["frequency_ghz"] != 10.0
                or point["port_reference_ohm"] != {"input": 50.0, "output": 1787.0}
                or point["model_kind"] != "teaching_model"
                or point["not_lna_result"] is not True or point["spec_pass"] is not None):
            raise ValueError("three-stage harmonic comparison point is not in the expected matrix")
        digest = hashlib.sha256((source_dir / "teaching_mos1_model.scs").read_bytes()).hexdigest()
        if model_hash is None:
            model_hash = digest
        elif digest != model_hash:
            raise ValueError("three-stage harmonic comparison model differs")
        for signal in _SIGNALS:
            grid, values = parse_complex_trace(source_dir / "sp.sp", signal)
            if signal not in reference_traces:
                reference_traces[signal] = (grid, values)
            else:
                expected_grid, expected_values = reference_traces[signal]
                if grid != expected_grid or any(
                    abs(left - right) > 1e-8 for left, right in zip(values, expected_values, strict=True)
                ):
                    raise ValueError("three-stage harmonic comparison SP results differ")
        points.append({
            "run_id": source_dir.name, "pin_dbm": expected_power,
            "harmonics": expected_harmonics,
            "pout_dbm": point["metrics"]["output_power_dbm"],
            "gain_db": point["metrics"]["power_gain_db"],
            "s21_db": point["metrics"]["small_signal_s21_db"],
            "manifest_sha256": hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        })
    crossings = []
    for harmonic_index, harmonics in enumerate(_HARMONICS):
        low = points[harmonic_index]
        high = points[harmonic_index + 3]
        if not math.isclose(low["s21_db"], high["s21_db"], rel_tol=0, abs_tol=1e-8):
            raise ValueError("three-stage harmonic comparison S21 references differ")
        low_drop = low["s21_db"] - low["gain_db"]
        high_drop = high["s21_db"] - high["gain_db"]
        if not 0 <= low_drop < 1 <= high_drop:
            raise ValueError("three-stage harmonic comparison does not bracket 1 dB compression")
        fraction = (1 - low_drop) / (high_drop - low_drop)
        crossings.append({
            "harmonics": harmonics,
            "ip1db_sp_reference_dbm": low["pin_dbm"] + fraction * (high["pin_dbm"] - low["pin_dbm"]),
            "op1db_sp_reference_dbm": low["pout_dbm"] + fraction * (high["pout_dbm"] - low["pout_dbm"]),
        })
    max_7_9 = max(abs(points[offset]["gain_db"] - points[offset + 1]["gain_db"])
                  for offset in (0, 3))
    max_9_11 = max(abs(points[offset + 1]["gain_db"] - points[offset + 2]["gain_db"])
                   for offset in (0, 3))
    report = {
        "schema_version": 1, "status": "diagnostic_harmonic_sensitivity_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "public MOS1 three-stage 10 GHz HB 7/9/11-harmonic comparison near 1 dB crossing",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "point_run_ids": ids, "points": points, "crossings": crossings,
        "metrics": {"max_gain_delta_7_9_db": max_7_9,
                    "max_gain_delta_9_11_db": max_9_11,
                    "max_ip_delta_7_11_dbm": max(
                        abs(crossings[0]["ip1db_sp_reference_dbm"] - item["ip1db_sp_reference_dbm"])
                        for item in crossings[1:]
                    )},
    }
    validate_metrics_payload(report)
    return report


def audit_three_stage_harmonic_comparison(report_dir: Path, hb_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("three-stage harmonic report directory is unsafe")
    saved = read_evidenced_metrics(report_dir)
    config_path = report_dir / "comparison_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("three-stage harmonic comparison config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"schema_version", "point_run_ids"} or config["schema_version"] != 1:
        raise ValueError("three-stage harmonic comparison config is invalid")
    rebuilt = build_three_stage_harmonic_comparison(hb_root, config["point_run_ids"], report_dir.name)
    if saved != rebuilt:
        raise ValueError("three-stage harmonic comparison differs from raw source archives")
    return {"status": "verified", "run_id": report_dir.name, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/audit public MOS1 three-stage HB harmonic comparison")
    parser.add_argument("point_run_ids", nargs="*")
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_hb")
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_harmonics")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir:
        result = audit_three_stage_harmonic_comparison(args.audit_dir, args.hb_root)
        print(f"status={result['status']} output={args.audit_dir.resolve()}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    report = build_three_stage_harmonic_comparison(args.hb_root, args.point_run_ids, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "comparison_config.json", {"schema_version": 1, "point_run_ids": args.point_run_ids})
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {"config": "comparison_config.json", "metrics": "metrics.json"})
    result = audit_three_stage_harmonic_comparison(report_dir, args.hb_root)
    print(f"status={result['status']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
