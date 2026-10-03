from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_hb import audit_pdk_rf_default_hb
from orfadc.experiments.audit_pdk_rf_default_hb_sweep import _source_dirs
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_HARMONICS = (7, 9, 11)
_POWERS = (-11, -10)
_COLUMNS = ("run_id", "pin_dbm", "harmonics", "pout_dbm", "gain_db", "s21_db", "compression_sp_reference_db")


def local_harmonic_crossings(points: list[dict]) -> list[dict]:
    if len(points) != 6:
        raise ValueError("harmonic comparison needs the complete two-by-three matrix")
    crossings = []
    for harmonic_index, harmonics in enumerate(_HARMONICS):
        low = points[harmonic_index]
        high = points[harmonic_index + 3]
        if (
            low["harmonics"] != harmonics or high["harmonics"] != harmonics
            or not math.isclose(low["pin_dbm"], -11, abs_tol=0.01)
            or not math.isclose(high["pin_dbm"], -10, abs_tol=0.01)
            or not math.isclose(low["s21_db"], high["s21_db"], abs_tol=1e-8)
        ):
            raise ValueError("harmonic comparison matrix or small-signal reference differs")
        lower_drop = low["compression_sp_reference_db"]
        upper_drop = high["compression_sp_reference_db"]
        if not 0 <= lower_drop < 1 <= upper_drop:
            raise ValueError("SP-referenced 1 dB crossing is not bracketed")
        fraction = (1 - lower_drop) / (upper_drop - lower_drop)
        crossings.append({
            "harmonics": harmonics,
            "ip1db_sp_reference_dbm": low["pin_dbm"] + fraction * (high["pin_dbm"] - low["pin_dbm"]),
            "op1db_sp_reference_dbm": low["pout_dbm"] + fraction * (high["pout_dbm"] - low["pout_dbm"]),
        })
    return crossings


def build_pdk_rf_harmonic_comparison(
    hb_root: Path, ids: list[str], create_dir: Path, baseline_dir: Path, run_id: str,
) -> tuple[list[dict], dict]:
    if not isinstance(ids, list) or len(ids) != 6:
        raise ValueError("RF harmonic comparison needs six source runs")
    sources = _source_dirs(hb_root, ids)
    points = []
    source_hashes = []
    geometry_signature = None
    for index, source_dir in enumerate(sources):
        audit_pdk_rf_default_hb(source_dir, create_dir, baseline_dir)
        point = read_evidenced_metrics(source_dir)
        power = _POWERS[index // 3]
        harmonics = _HARMONICS[index % 3]
        metrics = point["metrics"]
        if (
            point.get("input_drive_dbm") != power
            or point.get("harmonics", 7) != harmonics
            or not math.isclose(metrics["input_available_power_dbm"], power, abs_tol=0.01)
            or point.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}
            or point.get("oa_create_run_id") != create_dir.name
            or point.get("baseline_run_id") != baseline_dir.name
            or point.get("not_lna_result") is not True or point.get("spec_pass") is not None
            or point.get("physical_qualification") is not False
        ):
            raise ValueError("RF harmonic comparison point has incompatible context")
        signature = point["default_geometry_signature_sha256"]
        if geometry_signature is None:
            geometry_signature = signature
        elif signature != geometry_signature:
            raise ValueError("RF harmonic comparison geometry differs between points")
        points.append({
            "run_id": source_dir.name, "pin_dbm": metrics["input_available_power_dbm"],
            "harmonics": harmonics, "pout_dbm": metrics["output_power_dbm"],
            "gain_db": metrics["power_gain_db"], "s21_db": metrics["small_signal_s21_db"],
            "compression_sp_reference_db": metrics["small_signal_s21_db"] - metrics["power_gain_db"],
        })
        source_hashes.append(hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest())
    crossings = local_harmonic_crossings(points)
    max_7_9 = max(abs(points[offset]["gain_db"] - points[offset + 1]["gain_db"]) for offset in (0, 3))
    max_9_11 = max(abs(points[offset + 1]["gain_db"] - points[offset + 2]["gain_db"]) for offset in (0, 3))
    report = {
        "schema_version": 1, "status": "diagnostic_harmonic_sensitivity_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "OA-derived RF default 10 GHz HB 7/9/11-harmonic comparison at two drive points; not qualified LNA P1dB",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "oa_create_run_id": create_dir.name, "baseline_run_id": baseline_dir.name,
        "default_geometry_signature_sha256": geometry_signature,
        "point_run_ids": ids, "source_manifest_sha256": source_hashes,
        "points": points, "crossings_sp_reference": crossings,
        "metrics": {
            "maximum_gain_delta_7_to_9_db": max_7_9,
            "maximum_gain_delta_9_to_11_db": max_9_11,
            "maximum_local_ip_delta_7_to_11_dbm": max(
                abs(crossings[0]["ip1db_sp_reference_dbm"] - item["ip1db_sp_reference_dbm"])
                for item in crossings[1:]
            ),
        },
        "reference_limit": "SP-referenced local crossings only; 9/11-harmonic linear HB reference was not independently swept",
    }
    validate_metrics_payload(report)
    return points, report


def audit_pdk_rf_harmonic_comparison(
    report_dir: Path, hb_root: Path, create_dir: Path, baseline_dir: Path,
) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("RF harmonic report directory is unsafe")
    saved = read_evidenced_metrics(report_dir)
    config_path = report_dir / "comparison_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("RF harmonic comparison config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "point_run_ids", "oa_create_run_id", "baseline_run_id"}
        or config["schema_version"] != 1
        or config["oa_create_run_id"] != create_dir.name
        or config["baseline_run_id"] != baseline_dir.name
    ):
        raise ValueError("RF harmonic comparison config differs from requested OA sources")
    points, rebuilt = build_pdk_rf_harmonic_comparison(
        hb_root, config["point_run_ids"], create_dir, baseline_dir, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("RF harmonic comparison differs from raw sources")
    with (report_dir / "comparison.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("RF harmonic comparison CSV columns differ")
        rows = list(reader)
    if len(rows) != len(points):
        raise ValueError("RF harmonic comparison CSV count differs")
    for actual, expected in zip(rows, points, strict=True):
        if actual["run_id"] != expected["run_id"]:
            raise ValueError("RF harmonic comparison CSV run ID differs")
        if any(not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12)
               for key in _COLUMNS[1:]):
            raise ValueError("RF harmonic comparison CSV differs from raw sources")
    return {"status": "verified", "run_id": report_dir.name, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or audit a private RF HB harmonic comparison")
    parser.add_argument("point_run_ids", nargs="*")
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "pdk_three_stage_fixed")
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_harmonics")
    parser.add_argument("--create-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir:
        result = audit_pdk_rf_harmonic_comparison(
            args.audit_dir, args.hb_root, args.create_dir, args.baseline_dir,
        )
        print(f"status={result['status']} output={args.audit_dir.resolve()}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    points, report = build_pdk_rf_harmonic_comparison(
        args.hb_root, args.point_run_ids, args.create_dir, args.baseline_dir, run_id,
    )
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "comparison_config.json", {
        "schema_version": 1, "point_run_ids": args.point_run_ids,
        "oa_create_run_id": args.create_dir.name, "baseline_run_id": args.baseline_dir.name,
    })
    with (report_dir / "comparison.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(points)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "comparison_config.json", "waveforms": "comparison.csv", "metrics": "metrics.json",
    })
    result = audit_pdk_rf_harmonic_comparison(report_dir, args.hb_root, args.create_dir, args.baseline_dir)
    print(f"status={result['status']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
