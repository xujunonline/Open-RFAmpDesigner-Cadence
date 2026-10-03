from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.compression_metrics import extract_p1db
from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_hb import audit_pdk_rf_default_hb
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COLUMNS = ("point_index", "run_id", "pin_dbm", "pout_dbm", "gain_db", "gain_compression_db")


def summarize_diagnostic_p1db(rows: list[dict]) -> dict:
    compression = extract_p1db(rows, linear_points=3)
    crossing = compression["crossing_indices"]
    width = rows[crossing[1]]["pin_dbm"] - rows[crossing[0]]["pin_dbm"] if crossing else None
    if width is not None and width > 2.0:
        compression = {
            **compression, "status": "coarse_bracket",
            "ip1db_dbm": None, "op1db_dbm": None,
            "quality_flags": sorted({*compression["quality_flags"], "bracket_over_2_db"}),
        }
    compression["bracket_width_db"] = width
    compression["interpolation_kind"] = "linear_between_adjacent_measured_points" if width is not None else None
    return compression


def _source_dirs(hb_root: Path, ids: list[str]) -> list[Path]:
    if not hb_root.is_dir() or hb_root.is_symlink():
        raise ValueError("RF HB source root is missing or unsafe")
    if not isinstance(ids, list) or not 4 <= len(ids) <= 20:
        raise ValueError("RF HB sweep needs 4..20 source archives")
    if any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("RF HB sweep source IDs are duplicate or unsafe")
    dirs = [hb_root / value for value in ids]
    if any(not path.is_dir() or path.is_symlink() for path in dirs):
        raise ValueError("RF HB source archive is missing or unsafe")
    return dirs


def build_pdk_rf_default_hb_sweep(
    hb_root: Path, ids: list[str], create_dir: Path, baseline_dir: Path, run_id: str,
) -> tuple[list[dict], dict]:
    if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id):
        raise ValueError("RF HB sweep report ID is unsafe")
    rows: list[dict] = []
    source_hashes: list[str] = []
    geometry_signature: str | None = None
    for index, source_dir in enumerate(_source_dirs(hb_root, ids)):
        audit_pdk_rf_default_hb(source_dir, create_dir, baseline_dir)
        point = read_evidenced_metrics(source_dir)
        metrics = point["metrics"]
        drive = metrics["input_available_power_dbm"]
        expected_drive = -70 if index == 0 else point.get("input_drive_dbm")
        if (
            point.get("not_lna_result") is not True
            or point.get("spec_pass") is not None
            or point.get("physical_qualification") is not False
            or point.get("oa_create_run_id") != create_dir.name
            or point.get("baseline_run_id") != baseline_dir.name
            or point.get("harmonics", 7) != 7
            or point.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}
            or not math.isclose(drive, expected_drive, abs_tol=0.01)
            or (rows and drive <= rows[-1]["pin_dbm"])
            or (index == 0 and source_dir.name != ids[0])
        ):
            raise ValueError("RF HB sweep point has incompatible provenance or drive order")
        signature = point["default_geometry_signature_sha256"]
        if geometry_signature is None:
            geometry_signature = signature
        elif geometry_signature != signature:
            raise ValueError("RF HB sweep geometry differs between points")
        rows.append({
            "point_index": index, "run_id": source_dir.name,
            "pin_dbm": drive, "pout_dbm": metrics["output_power_dbm"],
            "gain_db": metrics["power_gain_db"],
            "gain_compression_db": 0.0,
        })
        source_hashes.append(hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest())
    if not math.isclose(rows[0]["pin_dbm"], -70.0, abs_tol=0.01):
        raise ValueError("RF HB sweep must include the audited -70 dBm reference point first")
    compression = summarize_diagnostic_p1db(rows)
    for row in rows:
        row["gain_compression_db"] = compression["small_signal_gain_db"] - row["gain_db"]
    status = {
        "ok": "diagnostic_p1db_bracketed",
        "quality_warning": "diagnostic_p1db_quality_warning",
        "coarse_bracket": "diagnostic_p1db_coarse_bracket",
        "unbracketed": "diagnostic_p1db_unbracketed",
    }[compression["status"]]
    report = {
        "schema_version": 1, "status": status, "simulation_status": "unknown",
        "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "OA-derived default-RF-device HB drive sweep with ideal passives; not a qualified LNA IP1dB",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "oa_create_run_id": create_dir.name, "baseline_run_id": baseline_dir.name,
        "default_geometry_signature_sha256": geometry_signature,
        "point_run_ids": ids, "source_manifest_sha256": source_hashes,
        "input_powers_dbm": [row["pin_dbm"] for row in rows],
        "points_completed": len(rows), "compression": compression,
        "metrics": {
            "diagnostic_ip1db_dbm": compression["ip1db_dbm"],
            "diagnostic_op1db_dbm": compression["op1db_dbm"],
            "small_signal_gain_db": compression["small_signal_gain_db"],
        },
        "model_warning_status": "5 repeated model-configuration warnings per point; not sign-off",
    }
    validate_metrics_payload(report)
    return rows, report


def audit_pdk_rf_default_hb_sweep(
    report_dir: Path, hb_root: Path, create_dir: Path, baseline_dir: Path,
) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("RF HB sweep report directory is unsafe")
    saved = read_evidenced_metrics(report_dir)
    config_path = report_dir / "sweep_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("RF HB sweep config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "point_run_ids", "oa_create_run_id", "baseline_run_id"}
        or config["schema_version"] != 1
        or config["oa_create_run_id"] != create_dir.name
        or config["baseline_run_id"] != baseline_dir.name
    ):
        raise ValueError("RF HB sweep config differs from requested OA sources")
    rows, rebuilt = build_pdk_rf_default_hb_sweep(
        hb_root, config["point_run_ids"], create_dir, baseline_dir, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("RF HB sweep report differs from raw source archives")
    with (report_dir / "power_sweep.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("RF HB sweep CSV columns differ")
        recorded = list(reader)
    if len(recorded) != len(rows):
        raise ValueError("RF HB sweep CSV point count differs")
    for actual, expected in zip(recorded, rows, strict=True):
        if actual["run_id"] != expected["run_id"] or int(actual["point_index"]) != expected["point_index"]:
            raise ValueError("RF HB sweep CSV point identity differs")
        if any(not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12)
               for key in _COLUMNS[2:]):
            raise ValueError("RF HB sweep CSV differs from raw points")
    return {"status": "verified", "run_id": report_dir.name,
            "compression_status": rebuilt["compression"]["status"], "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or audit a private RF default HB drive sweep")
    parser.add_argument("point_run_ids", nargs="*")
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "pdk_three_stage_fixed")
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_hb_sweeps")
    parser.add_argument("--create-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir:
        result = audit_pdk_rf_default_hb_sweep(
            args.audit_dir, args.hb_root, args.create_dir, args.baseline_dir,
        )
        print(f"status={result['status']} compression={result['compression_status']} output={args.audit_dir.resolve()}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows, report = build_pdk_rf_default_hb_sweep(
        args.hb_root, args.point_run_ids, args.create_dir, args.baseline_dir, run_id,
    )
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "sweep_config.json", {
        "schema_version": 1, "point_run_ids": args.point_run_ids,
        "oa_create_run_id": args.create_dir.name,
        "baseline_run_id": args.baseline_dir.name,
    })
    with (report_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "sweep_config.json", "waveforms": "power_sweep.csv", "metrics": "metrics.json",
    })
    result = audit_pdk_rf_default_hb_sweep(report_dir, args.hb_root, args.create_dir, args.baseline_dir)
    print(f"status={result['status']} compression={result['compression_status']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
