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

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_rf_default_hb_sweep import summarize_diagnostic_p1db
from orfadc.experiments.audit_pdk_rf_input_ladder import audit_pdk_rf_input_ladder
from orfadc.experiments.audit_pdk_rf_ladder_hb import audit_pdk_rf_ladder_hb
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COLUMNS = ("point_index", "run_id", "pin_dbm", "pout_dbm", "gain_db", "gain_compression_db")


def build_pdk_rf_ladder_hb_sweep(
    ladder_dir: Path, point_dirs: list[Path], run_id: str,
) -> tuple[list[dict], dict]:
    _require_private_path(ladder_dir)
    if not _ID.fullmatch(run_id) or not 4 <= len(point_dirs) <= 20 or len(set(point_dirs)) != len(point_dirs):
        raise ValueError("ladder HB sweep needs 4..20 distinct points and a safe run ID")
    audit_pdk_rf_input_ladder(ladder_dir)
    rows: list[dict] = []
    sources: list[dict] = []
    for index, point_dir in enumerate(point_dirs):
        _require_private_path(point_dir)
        audit_pdk_rf_ladder_hb(point_dir, ladder_dir)
        point = read_evidenced_metrics(point_dir)
        metrics = point["metrics"]
        drive = metrics["input_available_power_dbm"]
        if (
            point.get("ladder_run_id") != ladder_dir.name
            or point.get("not_lna_result") is not True
            or point.get("spec_pass") is not None
            or point.get("physical_qualification") is not False
            or point.get("cdf_callback_validated") is not False
            or point.get("harmonics") != 7
            or point.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}
            or not math.isclose(drive, point["input_drive_dbm"], abs_tol=0.01)
            or (rows and drive <= rows[-1]["pin_dbm"])
        ):
            raise ValueError("ladder HB sweep point does not match the shared candidate")
        rows.append({
            "point_index": index, "run_id": point_dir.name,
            "pin_dbm": drive, "pout_dbm": metrics["output_power_dbm"],
            "gain_db": metrics["power_gain_db"], "gain_compression_db": 0.0,
        })
        sources.append({
            "run_id": point_dir.name,
            "evidence_manifest_sha256": hashlib.sha256(
                (point_dir / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        })
    if not math.isclose(rows[0]["pin_dbm"], -70.0, abs_tol=0.01):
        raise ValueError("ladder HB sweep lacks the -70 dBm linear reference")
    compression = summarize_diagnostic_p1db(rows)
    for row in rows:
        row["gain_compression_db"] = compression["small_signal_gain_db"] - row["gain_db"]
    status = {
        "ok": "diagnostic_p1db_bracketed",
        "quality_warning": "diagnostic_p1db_quality_warning",
        "coarse_bracket": "diagnostic_p1db_coarse_bracket",
        "unbracketed": "diagnostic_p1db_unbracketed",
    }[compression["status"]]
    payload = {
        "schema_version": 1, "status": status,
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_ideal_input_ladder_probe",
        "model_kind": "authorized_pdk_private", "not_lna_result": True,
        "spec_pass": None, "run_id": run_id,
        "scope": "same derived ideal-input-ladder DC/SP/noise/HB drive sweep; not a qualified LNA IP1dB",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "ladder_run_id": ladder_dir.name,
        "ladder_manifest_sha256": hashlib.sha256(
            (ladder_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "source_points": sources, "points_completed": len(rows),
        "compression": compression,
        "metrics": {
            "diagnostic_ip1db_dbm": compression["ip1db_dbm"],
            "diagnostic_op1db_dbm": compression["op1db_dbm"],
            "small_signal_gain_db": compression["small_signal_gain_db"],
        },
        "physical_qualification": False, "cdf_callback_validated": False,
        "model_warning_resolved": False,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_rf_ladder_hb_sweep(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("ladder HB sweep report is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    entries = json.loads((report_dir / "evidence_manifest.json").read_text(
        encoding="utf-8"
    )).get("artifacts", {})
    required = {"config": "sweep_config.json", "search": "power_sweep.csv",
                "metrics": "metrics.json"}
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in required.items()):
        raise ValueError("ladder HB sweep evidence lacks required artifacts")
    config_path = report_dir / "sweep_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("ladder HB sweep source config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "ladder_run_id", "point_run_ids"}
        or config["schema_version"] != 1
        or not isinstance(config["ladder_run_id"], str)
        or not _ID.fullmatch(config["ladder_run_id"])
        or not isinstance(config["point_run_ids"], list)
        or any(not isinstance(value, str) or not _ID.fullmatch(value)
               for value in config["point_run_ids"])
    ):
        raise ValueError("ladder HB sweep source IDs are unsafe")
    ladder_dir = _PRIVATE_ROOT / "pdk_rf_input_ladder" / config["ladder_run_id"]
    point_dirs = [_PRIVATE_ROOT / "pdk_rf_ladder_hb" / value for value in config["point_run_ids"]]
    rows, rebuilt = build_pdk_rf_ladder_hb_sweep(ladder_dir, point_dirs, report_dir.name)
    if saved != rebuilt:
        raise ValueError("ladder HB sweep differs from raw Spectre sources")
    csv_path = report_dir / "power_sweep.csv"
    if not csv_path.is_file() or csv_path.is_symlink():
        raise ValueError("ladder HB sweep CSV is missing or unsafe")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("ladder HB sweep CSV columns differ")
        stored = list(reader)
    if len(stored) != len(rows):
        raise ValueError("ladder HB sweep CSV row count differs")
    for actual, expected in zip(stored, rows, strict=True):
        if actual["run_id"] != expected["run_id"]:
            raise ValueError("ladder HB sweep CSV point identity differs")
        for key in _COLUMNS:
            if key == "run_id":
                continue
            if not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("ladder HB sweep CSV differs from source points")
    return {"status": "verified_diagnostic_only", "run_id": report_dir.name,
            "points_verified": len(rows), "compression_status": rebuilt["compression"]["status"],
            "not_lna_result": True, "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or audit an RF input-ladder HB sweep")
    parser.add_argument("point_dirs", nargs="*", type=Path)
    parser.add_argument("--ladder-dir", type=Path)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_ladder_hb_sweeps")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_pdk_rf_ladder_hb_sweep(args.audit_dir)
        print(f"status={result['status']} points={result['points_verified']}")
        return 0
    if args.ladder_dir is None:
        parser.error("--ladder-dir is required to build a report")
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows, payload = build_pdk_rf_ladder_hb_sweep(args.ladder_dir, args.point_dirs, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "sweep_config.json", {
        "schema_version": 1, "ladder_run_id": args.ladder_dir.name,
        "point_run_ids": [path.name for path in args.point_dirs],
    })
    with (report_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(report_dir / "metrics.json", payload)
    write_evidence_manifest(report_dir, {
        "config": "sweep_config.json", "search": "power_sweep.csv", "metrics": "metrics.json",
    })
    result = audit_pdk_rf_ladder_hb_sweep(report_dir)
    print(f"status={result['status']} points={result['points_verified']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
