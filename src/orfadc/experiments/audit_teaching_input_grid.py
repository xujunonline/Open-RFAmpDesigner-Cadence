from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from itertools import product
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.tools.cost_functions import stage2_cost


_COLUMNS = (
    "point_index", "run_id", "lgs_nh", "lss_ph", "nf_worst_db", "s11_worst_db",
    "s21_worst_db", "gain_ripple_db", "supply_current_ma", "nf_violation",
    "s11_violation", "diagnostic_cost", "minimum_k_sampled", "maximum_delta_abs_sampled",
)


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("symlinked teaching input metadata is not accepted")

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")

    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("teaching input metadata must be an object")
    return data


def _close(actual: object, expected: float, label: str) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-9, abs_tol=1e-9,
    ):
        raise ValueError(f"teaching input grid {label} disagrees with original data")


def audit_teaching_input_grid(grid_dir: Path) -> dict:
    """Read-only re-evaluation of a complete MOS1 teaching input grid."""
    if not grid_dir.is_dir() or grid_dir.is_symlink():
        raise ValueError("teaching input grid directory is missing or symlinked")
    summary = read_evidenced_metrics(grid_dir)
    config = _read_json(grid_dir / "sweep_config.json")
    lgs_values = config.get("lgs_values_nh")
    lss_values = config.get("lss_values_ph")
    if (
        config.get("schema_version") != 1
        or not isinstance(lgs_values, list) or not 2 <= len(lgs_values) <= 4
        or not isinstance(lss_values, list) or not 2 <= len(lss_values) <= 4
        or not 4 <= len(lgs_values) * len(lss_values) <= 12
        or any(type(x) not in {int, float} or not math.isfinite(x) for x in (*lgs_values, *lss_values))
        or len(set(lgs_values)) != len(lgs_values)
        or len(set(lss_values)) != len(lss_values)
        or config.get("output_ldd_nh") != 2.0
        or config.get("output_cblock_ff") != 5000.0
        or ("wmos_um" in config and config["wmos_um"] != 300.0)
    ):
        raise ValueError("invalid teaching input grid configuration")
    for key in ("vbias_v", "nf_user_db", "nf_headroom_db"):
        if type(config.get(key)) not in {int, float} or not math.isfinite(config[key]):
            raise ValueError(f"invalid teaching input {key}")
    if not 0.5 <= config["vbias_v"] <= 0.7 or not 0 <= config["nf_headroom_db"] < config["nf_user_db"]:
        raise ValueError("teaching input bias or NF target is outside its policy")
    expected_combinations = list(product(lgs_values, lss_values))
    if (
        summary.get("status") != "input_grid_complete"
        or summary.get("simulation_status") != "unknown"
        or summary.get("source") != "cadence_spectre_archives"
        or summary.get("circuit_class") != "teaching_mos1_common_source"
        or summary.get("model_kind") != "teaching_model"
        or summary.get("not_lna_result") is not True
        or summary.get("spec_pass") is not None
        or summary.get("run_id") != grid_dir.name
        or summary.get("points_requested") != len(expected_combinations)
        or summary.get("points_completed") != len(expected_combinations)
        or summary.get("failures") != []
    ):
        raise ValueError("teaching input grid summary is incomplete or misclassified")
    csv_path = grid_dir / "input_grid.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked teaching input CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(_COLUMNS):
            raise ValueError("teaching input CSV columns disagree with the contract")
        saved_csv = list(reader)
    saved_rows = summary.get("rows")
    saved_manifests = summary.get("source_manifests")
    if any(not isinstance(value, list) or len(value) != len(expected_combinations)
           for value in (saved_csv, saved_rows, saved_manifests)):
        raise ValueError("teaching input point count disagrees with raw runs")
    recomputed = []
    for index, (lgs_nh, lss_ph) in enumerate(expected_combinations):
        point_dir = grid_dir / f"point_{index:02d}"
        if point_dir.is_symlink():
            raise ValueError("symlinked teaching input point is not accepted")
        point = read_evidenced_metrics(point_dir)
        expected_parameters = {
            "vbias_v": config["vbias_v"], "lgs_nh": lgs_nh, "lss_ph": lss_ph,
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        }
        if "wmos_um" in config:
            expected_parameters["wmos_um"] = 300.0
        if (
            point.get("status") != "ok_with_warnings"
            or point.get("design_parameters") != expected_parameters
        ):
            raise ValueError(f"teaching input point {index} settings are inconsistent")
        audit = audit_teaching_lna(point_dir)
        metrics = audit["metrics"]
        stability = audit["stability"]
        cost = stage2_cost(metrics["nf_db"], config["nf_user_db"],
                           metrics["s11_db"], config["nf_headroom_db"])
        row = {
            "point_index": index, "run_id": point_dir.name,
            "lgs_nh": float(lgs_nh), "lss_ph": float(lss_ph),
            "nf_worst_db": metrics["nf_db"], "s11_worst_db": metrics["s11_db"],
            "s21_worst_db": metrics["s21_db"], "gain_ripple_db": metrics["ripple_db"],
            "supply_current_ma": metrics["supply_current_ma"],
            "nf_violation": cost["nf_violation"], "s11_violation": cost["s11_violation"],
            "diagnostic_cost": cost["cost"],
            "minimum_k_sampled": stability["minimum_k"],
            "maximum_delta_abs_sampled": stability["maximum_delta_abs"],
        }
        if saved_rows[index].get("run_id") != row["run_id"] or saved_csv[index].get("run_id") != row["run_id"]:
            raise ValueError(f"teaching input point {index} identity mismatch")
        for key in _COLUMNS:
            if key == "run_id":
                continue
            _close(saved_rows[index].get(key), row[key], f"point {index} JSON {key}")
            try:
                saved_number = float(saved_csv[index][key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"teaching input point {index} CSV {key} is invalid") from exc
            _close(saved_number, row[key], f"point {index} CSV {key}")
        digest = hashlib.sha256((point_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if saved_manifests[index] != {"run_id": point_dir.name, "evidence_manifest_sha256": digest}:
            raise ValueError(f"teaching input point {index} source manifest changed")
        recomputed.append(row)
    best = min(recomputed, key=lambda row: (row["diagnostic_cost"], row["s11_worst_db"], row["point_index"]))
    if summary.get("best_diagnostic_point") != best:
        raise ValueError("teaching input best point disagrees with raw results")
    return {"status": "verified", "run_id": grid_dir.name,
            "points_verified": len(recomputed), "best_diagnostic_point": best,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a complete teaching MOS1 input grid")
    parser.add_argument("grid_dir", type=Path)
    args = parser.parse_args()
    try:
        report = audit_teaching_input_grid(args.grid_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"teaching input grid audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points={report['points_verified']} run_id={report['run_id']}")
    print(f"best={report['best_diagnostic_point']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
