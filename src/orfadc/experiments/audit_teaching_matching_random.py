from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.tools.cost_functions import stage2_cost
from orfadc.tools.stage2_sampling import sample_teaching_stage2

from .run_teaching_matching_random import _COLUMNS


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("symlinked matching metadata is not accepted")

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("matching metadata must be an object")
    return value


def _close(actual: object, expected: float, label: str) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-9, abs_tol=1e-9,
    ):
        raise ValueError(f"matching {label} disagrees with raw evidence")


def audit_teaching_matching_random(search_dir: Path) -> dict:
    """Independently re-score every completed teaching random-search point."""
    if not search_dir.is_dir() or search_dir.is_symlink():
        raise ValueError("matching search directory is missing or symlinked")
    summary = read_evidenced_metrics(search_dir)
    config = _read_json(search_dir / "search_config.json")
    if config.get("schema_version") != 1 or config.get("method") != "seeded_uniform_random":
        raise ValueError("invalid matching search method")
    points = sample_teaching_stage2(config.get("seed"), config.get("budget"))
    if config.get("points") != points or any(config.get(key) != value for key, value in {
        "vbias_v": 0.65, "wmos_um": 300.0, "ldd_nh": 2.0, "cblock_ff": 5000.0,
    }.items()):
        raise ValueError("matching search plan or fixed circuit settings changed")
    nf_user_db = config.get("nf_user_db")
    nf_headroom_db = config.get("nf_headroom_db")
    if (
        any(type(value) not in {int, float} or not math.isfinite(value)
            for value in (nf_user_db, nf_headroom_db))
        or nf_user_db <= 0 or not 0 <= nf_headroom_db < nf_user_db
    ):
        raise ValueError("invalid matching NF objective")
    if (
        summary.get("status") != "random_search_complete"
        or summary.get("simulation_status") != "unknown"
        or summary.get("source") != "cadence_spectre_archives"
        or summary.get("circuit_class") != "teaching_mos1_common_source"
        or summary.get("model_kind") != "teaching_model"
        or summary.get("not_lna_result") is not True
        or summary.get("spec_pass") is not None
        or summary.get("run_id") != search_dir.name
        or summary.get("seed") != config["seed"]
        or summary.get("points_requested") != len(points)
        or summary.get("points_completed") != len(points)
        or summary.get("failures") != []
    ):
        raise ValueError("matching search summary is incomplete or misclassified")
    csv_path = search_dir / "search.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked matching CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(_COLUMNS):
            raise ValueError("matching CSV columns disagree with the contract")
        saved_csv = list(reader)
    saved_rows = summary.get("rows")
    saved_manifests = summary.get("source_manifests")
    if any(not isinstance(value, list) or len(value) != len(points)
           for value in (saved_csv, saved_rows, saved_manifests)):
        raise ValueError("matching point count disagrees with the plan")
    recomputed = []
    for index, point in enumerate(points):
        point_dir = search_dir / f"point_{index:02d}"
        if point_dir.is_symlink():
            raise ValueError("symlinked matching point is not accepted")
        original = read_evidenced_metrics(point_dir)
        if original.get("status") != "ok_with_warnings" or original.get("design_parameters") != {
            "vbias_v": 0.65, "wmos_um": 300.0, **point,
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        }:
            raise ValueError(f"matching point {index} does not match the planned circuit")
        audit = audit_teaching_lna(point_dir)
        metrics = audit["metrics"]
        cost = stage2_cost(metrics["nf_db"], nf_user_db, metrics["s11_db"], nf_headroom_db)
        row = {
            "point_index": index, "run_id": point_dir.name, **point,
            "nf_worst_db": metrics["nf_db"], "s11_worst_db": metrics["s11_db"],
            "s21_worst_db": metrics["s21_db"],
            "nf_violation": cost["nf_violation"],
            "s11_violation": cost["s11_violation"],
            "diagnostic_cost": cost["cost"],
            "minimum_k_sampled": audit["stability"]["minimum_k"],
        }
        if saved_rows[index].get("run_id") != row["run_id"] or saved_csv[index].get("run_id") != row["run_id"]:
            raise ValueError(f"matching point {index} identity mismatch")
        for key in _COLUMNS:
            if key == "run_id":
                continue
            _close(saved_rows[index].get(key), row[key], f"point {index} JSON {key}")
            try:
                saved_number = float(saved_csv[index][key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"matching point {index} CSV {key} is invalid") from exc
            _close(saved_number, row[key], f"point {index} CSV {key}")
        digest = hashlib.sha256((point_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if saved_manifests[index] != {"run_id": point_dir.name, "evidence_manifest_sha256": digest}:
            raise ValueError(f"matching point {index} manifest changed")
        recomputed.append(row)
    best = min(recomputed, key=lambda row: (row["diagnostic_cost"], row["point_index"]))
    if summary.get("best_diagnostic_point") != best:
        raise ValueError("matching best point disagrees with the raw evidence")
    return {"status": "verified", "run_id": search_dir.name,
            "points_verified": len(recomputed), "best_diagnostic_point": best,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a MOS1 matching random search")
    parser.add_argument("search_dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit_teaching_matching_random(args.search_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"matching random audit failed: {type(exc).__name__}: {exc}")
    print(f"status={result['status']} points={result['points_verified']} run_id={result['run_id']}")
    print(f"best={result['best_diagnostic_point']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
