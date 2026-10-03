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
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage_hb import audit_teaching_three_stage_hb
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SIGNALS = ("s11", "s21", "s12", "s22")
_COLUMNS = ("point_index", "run_id", "pin_dbm", "pout_dbm", "gain_db", "hb_minus_s21_db")


def _source_dirs(hb_root: Path, ids: list[str]) -> list[Path]:
    if not hb_root.is_dir() or hb_root.is_symlink():
        raise ValueError("three-stage HB source root is missing or unsafe")
    if not isinstance(ids, list) or not 4 <= len(ids) <= 20:
        raise ValueError("three-stage HB sweep needs 4..20 source runs")
    if (any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("three-stage HB source run IDs are duplicate or unsafe")
    dirs = [hb_root / value for value in ids]
    if any(not path.is_dir() or path.is_symlink() for path in dirs):
        raise ValueError("three-stage HB source run is missing or unsafe")
    return dirs


def build_three_stage_hb_sweep(hb_root: Path, ids: list[str], run_id: str) -> tuple[list[dict], dict]:
    if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id):
        raise ValueError("three-stage HB sweep report ID is unsafe")
    source_dirs = _source_dirs(hb_root, ids)
    rows = []
    manifest_hashes = []
    reference_traces: dict[str, tuple[list[float], list[complex]]] = {}
    reference_model = None
    reference_settings = None
    for index, source_dir in enumerate(source_dirs):
        audit_teaching_three_stage_hb(source_dir)
        point = read_evidenced_metrics(source_dir)
        settings = point["parameters"]
        power = settings["input_dbm"]
        common = {key: settings[key] for key in ("output_secondary_nh", "frequency_ghz", "harmonics")}
        if reference_settings is None:
            reference_settings = common
        elif common != reference_settings:
            raise ValueError("three-stage HB sweep settings differ between points")
        if (not 0.5 <= settings["output_secondary_nh"] <= 16
                or settings["frequency_ghz"] != 10.0
                or settings["harmonics"] != 7
                or point["port_reference_ohm"] != {"input": 50.0, "output": 1787.0}
                or point["model_kind"] != "teaching_model"
                or point["not_lna_result"] is not True or point["spec_pass"] is not None):
            raise ValueError("three-stage HB sweep point has incompatible circuit context")
        if rows and power <= rows[-1]["pin_dbm"]:
            raise ValueError("three-stage HB input powers must be strictly increasing")
        model_hash = hashlib.sha256((source_dir / "teaching_mos1_model.scs").read_bytes()).hexdigest()
        if reference_model is None:
            reference_model = model_hash
        elif model_hash != reference_model:
            raise ValueError("three-stage HB model differs between points")
        for signal in _SIGNALS:
            trace = parse_complex_trace(source_dir / "sp.sp", signal)
            if signal not in reference_traces:
                reference_traces[signal] = trace
            else:
                grid, values = reference_traces[signal]
                if trace[0] != grid or any(
                    abs(left - right) > 1e-8 for left, right in zip(trace[1], values, strict=True)
                ):
                    raise ValueError("three-stage HB small-signal S changes across the drive sweep")
        metrics = point["metrics"]
        rows.append({
            "point_index": index, "run_id": source_dir.name,
            "pin_dbm": power, "pout_dbm": metrics["output_power_dbm"],
            "gain_db": metrics["power_gain_db"],
            "hb_minus_s21_db": metrics["hb_minus_s21_db"],
        })
        manifest_hashes.append(hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest())
    compression = extract_p1db(rows, linear_points=3)
    status = {
        "ok": "diagnostic_p1db_bracketed",
        "quality_warning": "diagnostic_p1db_quality_warning",
        "unbracketed": "diagnostic_p1db_unbracketed",
    }[compression["status"]]
    report = {
        "schema_version": 1, "status": status, "simulation_status": "unknown",
        "source": "cadence_spectre_archives", "circuit_class": "teaching_mos1_three_stage_probe",
        "model_kind": "teaching_model", "not_lna_result": True, "spec_pass": None,
        "run_id": run_id,
        "scope": "same public MOS1 three-stage 10 GHz HB drive sweep; not a qualified LNA IP1dB",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "point_run_ids": ids, "source_manifest_sha256": manifest_hashes,
        **({"parameters": reference_settings} if reference_settings["output_secondary_nh"] != 1.0 else {}),
        "input_powers_dbm": [row["pin_dbm"] for row in rows],
        "points_completed": len(rows), "compression": compression,
        "metrics": {"diagnostic_ip1db_dbm": compression["ip1db_dbm"],
                    "diagnostic_op1db_dbm": compression["op1db_dbm"],
                    "small_signal_gain_db": compression["small_signal_gain_db"]},
    }
    validate_metrics_payload(report)
    return rows, report


def audit_three_stage_hb_sweep(report_dir: Path, hb_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("three-stage HB sweep report directory is unsafe")
    saved = read_evidenced_metrics(report_dir)
    config_path = report_dir / "sweep_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("three-stage HB sweep config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"schema_version", "point_run_ids"} or config["schema_version"] != 1:
        raise ValueError("three-stage HB sweep config is invalid")
    rows, rebuilt = build_three_stage_hb_sweep(hb_root, config["point_run_ids"], report_dir.name)
    if saved != rebuilt:
        raise ValueError("three-stage HB sweep report differs from raw source archives")
    with (report_dir / "power_sweep.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("three-stage HB sweep CSV columns differ")
        recorded = list(reader)
    if len(recorded) != len(rows):
        raise ValueError("three-stage HB sweep CSV row count differs")
    for actual, expected in zip(recorded, rows, strict=True):
        if actual["run_id"] != expected["run_id"] or int(actual["point_index"]) != expected["point_index"]:
            raise ValueError("three-stage HB sweep CSV point identity differs")
        if any(not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12)
               for key in _COLUMNS[2:]):
            raise ValueError("three-stage HB sweep CSV differs from raw points")
    return {"status": "verified", "run_id": report_dir.name,
            "compression_status": rebuilt["compression"]["status"], "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/audit public MOS1 three-stage HB drive sweep")
    parser.add_argument("point_run_ids", nargs="*")
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_hb")
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_hb_sweeps")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir:
        result = audit_three_stage_hb_sweep(args.audit_dir, args.hb_root)
        print(f"status={result['status']} output={args.audit_dir.resolve()}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows, report = build_three_stage_hb_sweep(args.hb_root, args.point_run_ids, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "sweep_config.json", {"schema_version": 1, "point_run_ids": args.point_run_ids})
    with (report_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "sweep_config.json", "waveforms": "power_sweep.csv", "metrics": "metrics.json",
    })
    result = audit_three_stage_hb_sweep(report_dir, args.hb_root)
    print(f"status={result['status']} compression={result['compression_status']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
