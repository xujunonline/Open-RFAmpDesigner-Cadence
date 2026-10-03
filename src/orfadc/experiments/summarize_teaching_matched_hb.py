from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.compression_metrics import extract_p1db
from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_hb import audit_teaching_hb
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_DESIGN_KEYS = (
    "frequency_ghz", "harmonics", "vbias_v", "ldd_nh", "cblock_ff",
    "rdamp_ohm", "sp_intervals", "sp_start_ghz", "sp_stop_ghz",
)
_COLUMNS = ("point_index", "run_id", "pin_dbm", "pout_dbm", "gain_db", "small_signal_s21_db")


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or symlinked HB source manifest")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _design(parameters: dict) -> dict:
    if not isinstance(parameters, dict) or set(parameters) != {"input_dbm", *_DESIGN_KEYS}:
        raise ValueError("matched HB point has incomplete design parameters")
    return {key: parameters[key] for key in _DESIGN_KEYS}


def build_matched_hb_summary(valid_runs: list[Path], rejected_run: Path, run_id: str) -> dict:
    if not isinstance(valid_runs, list) or not 4 <= len(valid_runs) <= 12:
        raise ValueError("matched HB summary needs 4..12 valid points")
    if len({path.resolve() for path in (*valid_runs, rejected_run)}) != len(valid_runs) + 1:
        raise ValueError("matched HB source runs must be distinct")
    rows = []
    manifests = []
    design = None
    reference_s21 = None
    for index, run_dir in enumerate(valid_runs):
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise ValueError("matched HB source directory is missing or symlinked")
        audited = audit_teaching_hb(run_dir)
        saved = read_evidenced_metrics(run_dir)
        parameters = saved.get("parameters")
        current_design = _design(parameters)
        if current_design.get("rdamp_ohm") is None or current_design.get("sp_start_ghz") != 8.0:
            raise ValueError("matched HB source is not the intended damped band candidate")
        if design is None:
            design = current_design
        elif current_design != design:
            raise ValueError("matched HB source designs differ")
        metrics = audited["metrics"]
        s21 = metrics["small_signal_s21_db"]
        if reference_s21 is None:
            reference_s21 = s21
        elif not math.isclose(s21, reference_s21, rel_tol=0, abs_tol=0.001):
            raise ValueError("matched HB points have different small-signal gain")
        power = parameters["input_dbm"]
        if rows and power <= rows[-1]["pin_dbm"]:
            raise ValueError("matched HB powers must increase strictly")
        rows.append({
            "point_index": index, "run_id": run_dir.name,
            "pin_dbm": power, "pout_dbm": metrics["output_power_dbm"],
            "gain_db": metrics["power_gain_db"], "small_signal_s21_db": s21,
        })
        manifests.append({"run_id": run_dir.name, "sha256": _sha(run_dir / "evidence_manifest.json")})
    if not rejected_run.is_dir() or rejected_run.is_symlink():
        raise ValueError("matched HB rejected point is missing or symlinked")
    rejected = read_evidenced_metrics(rejected_run)
    rejected_parameters = rejected.get("parameters")
    if (
        rejected.get("status") != "model_validity_warning"
        or rejected.get("simulation_status") != "ok"
        or rejected.get("source") != "cadence_spectre"
        or rejected.get("model_kind") != "teaching_model"
        or rejected.get("not_lna_result") is not True
        or rejected.get("spec_pass") is not None
        or rejected.get("metrics") is not None
        or _design(rejected_parameters) != design
        or rejected_parameters["input_dbm"] <= rows[-1]["pin_dbm"]
        or "spectre_warnings" not in rejected.get("quality_flags", [])
    ):
        raise ValueError("rejected HB point is not a same-design model-warning stop")
    compression = extract_p1db(rows, linear_points=3)
    if compression["status"] != "unbracketed":
        raise ValueError("this matched HB summary expects an unbracketed valid range")
    summary = {
        "schema_version": 1, "status": "unbracketed_model_warning_stop",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "damped MOS1 teaching HB; no valid IP1dB/OP1dB before model-warning stop",
        "analysis": ["dc", "sp", "noise", "hb"], "design_parameters": design,
        "points_completed": len(rows), "rows": rows, "source_manifests": manifests,
        "rejected_run_id": rejected_run.name,
        "rejected_manifest_sha256": _sha(rejected_run / "evidence_manifest.json"),
        "rejected_input_dbm": rejected_parameters["input_dbm"],
        "rejected_quality_flags": rejected["quality_flags"],
        "compression": compression, "metrics": compression,
    }
    validate_metrics_payload(summary)
    return summary


def audit_matched_hb_summary(summary_dir: Path, source_root: Path) -> dict:
    if not summary_dir.is_dir() or summary_dir.is_symlink():
        raise ValueError("matched HB summary directory is missing or symlinked")
    saved = read_evidenced_metrics(summary_dir)
    run_ids = [entry.get("run_id") for entry in saved.get("source_manifests", [])]
    rejected_id = saved.get("rejected_run_id")
    if any(not isinstance(value, str) or not value or "/" in value or "\\" in value or value in {".", ".."}
           for value in (*run_ids, rejected_id)):
        raise ValueError("invalid matched HB source identity")
    rebuilt = build_matched_hb_summary(
        [source_root / run_id for run_id in run_ids], source_root / rejected_id, summary_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("matched HB summary differs from source archives")
    csv_path = summary_dir / "power_sweep.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked matched HB CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(_COLUMNS):
            raise ValueError("matched HB CSV columns disagree with the contract")
        csv_rows = list(reader)
    if len(csv_rows) != len(rebuilt["rows"]):
        raise ValueError("matched HB CSV point count disagrees with the source")
    for saved_row, row in zip(csv_rows, rebuilt["rows"], strict=True):
        if saved_row["run_id"] != row["run_id"]:
            raise ValueError("matched HB CSV source identity changed")
        for key in _COLUMNS:
            if key == "run_id":
                continue
            try:
                value = float(saved_row[key])
            except (TypeError, ValueError) as exc:
                raise ValueError("matched HB CSV contains a nonnumeric value") from exc
            if not math.isclose(value, row[key], rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"matched HB CSV {key} differs from raw data")
    return {"status": "verified", "run_id": summary_dir.name,
            "points_verified": len(rebuilt["rows"]), "compression_status": "unbracketed",
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize archived matched MOS1 HB points")
    parser.add_argument("valid_runs", nargs=4, type=Path)
    parser.add_argument("--rejected-run", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_matched_hb_summaries")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
        summary = build_matched_hb_summary(args.valid_runs, args.rejected_run, output_dir.name)
        output_dir.mkdir(parents=True, exist_ok=False)
        with (output_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
            writer.writeheader()
            writer.writerows(summary["rows"])
        write_json(output_dir / "metrics.json", summary)
        write_evidence_manifest(output_dir, {"metrics": "metrics.json", "sweep": "power_sweep.csv"})
        audit_matched_hb_summary(output_dir, args.valid_runs[0].parent)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"matched HB summary failed: {type(exc).__name__}: {exc}")
    print(f"status={summary['status']} points={summary['points_completed']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
