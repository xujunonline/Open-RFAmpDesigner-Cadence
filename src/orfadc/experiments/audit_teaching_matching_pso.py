from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.audit_teaching_matching_random import _close, _read_json
from orfadc.experiments.run_teaching_matching_pso import _PSO_COLUMNS
from orfadc.tools.cost_functions import stage2_cost
from orfadc.tools.stage2_pso import TeachingStage2PSO


_SETTINGS = {
    "schema_version": 1, "method": "bounded_pso_teaching", "inertia": 0.55,
    "cognitive": 1.4, "social": 1.4, "max_normalized_velocity": 0.25,
    "normalized_initial_velocity": 0.2,
    "lgs_nh_range": [0.7, 1.3], "lss_ph_range": [180.0, 320.0],
    "vbias_v": 0.65, "wmos_um": 300.0, "ldd_nh": 2.0, "cblock_ff": 5000.0,
    "scope": "MOS1 teaching diagnostic only; not scikit-opt, PDK or paper Stage 2",
}


def audit_teaching_matching_pso(search_dir: Path) -> dict:
    """Replay every PSO transition using scores rebuilt from raw Spectre files."""
    if not search_dir.is_dir() or search_dir.is_symlink():
        raise ValueError("PSO search directory is missing or symlinked")
    summary = read_evidenced_metrics(search_dir)
    config = _read_json(search_dir / "search_config.json")
    if set(config) != {*_SETTINGS, "seed", "budget", "particles", "nf_user_db", "nf_headroom_db"}:
        raise ValueError("PSO config fields differ from the fixed comparison contract")
    if any(config[key] != value for key, value in _SETTINGS.items()):
        raise ValueError("PSO method or fixed circuit settings changed")
    optimizer = TeachingStage2PSO(config["seed"], config["budget"], particles=config["particles"])
    nf_user_db = config["nf_user_db"]
    nf_headroom_db = config["nf_headroom_db"]
    if (
        any(type(value) not in {int, float} or not math.isfinite(value)
            for value in (nf_user_db, nf_headroom_db))
        or nf_user_db <= 0 or not 0 <= nf_headroom_db < nf_user_db
    ):
        raise ValueError("invalid PSO NF objective")
    if (
        summary.get("status") != "pso_search_complete"
        or summary.get("simulation_status") != "unknown"
        or summary.get("source") != "cadence_spectre_archives"
        or summary.get("circuit_class") != "teaching_mos1_common_source"
        or summary.get("model_kind") != "teaching_model"
        or summary.get("not_lna_result") is not True
        or summary.get("spec_pass") is not None
        or summary.get("run_id") != search_dir.name
        or summary.get("seed") != config["seed"]
        or summary.get("points_requested") != optimizer.budget
        or summary.get("points_completed") != optimizer.budget
        or summary.get("failures") != []
    ):
        raise ValueError("PSO search summary is incomplete or misclassified")
    csv_path = search_dir / "search.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked PSO CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _PSO_COLUMNS:
            raise ValueError("PSO CSV columns disagree with the contract")
        saved_csv = list(reader)
    saved_rows = summary.get("rows")
    saved_manifests = summary.get("source_manifests")
    if any(not isinstance(value, list) or len(value) != optimizer.budget
           for value in (saved_csv, saved_rows, saved_manifests)):
        raise ValueError("PSO point count disagrees with the budget")
    recomputed = []
    for index in range(optimizer.budget):
        point = optimizer.ask()
        point_dir = search_dir / f"point_{index:02d}"
        if point_dir.is_symlink():
            raise ValueError("symlinked PSO point is not accepted")
        original = read_evidenced_metrics(point_dir)
        if original.get("status") != "ok_with_warnings" or original.get("design_parameters") != {
            "vbias_v": 0.65, "wmos_um": 300.0, **point,
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        }:
            raise ValueError(f"PSO point {index} differs from the replayed proposal")
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
            "generation": index // optimizer.particles, "particle": index % optimizer.particles,
        }
        if saved_rows[index].get("run_id") != row["run_id"] or saved_csv[index].get("run_id") != row["run_id"]:
            raise ValueError(f"PSO point {index} identity mismatch")
        for key in _PSO_COLUMNS:
            if key == "run_id":
                continue
            _close(saved_rows[index].get(key), row[key], f"PSO point {index} JSON {key}")
            try:
                saved_number = float(saved_csv[index][key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"PSO point {index} CSV {key} is invalid") from exc
            _close(saved_number, row[key], f"PSO point {index} CSV {key}")
        digest = hashlib.sha256((point_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if saved_manifests[index] != {"run_id": point_dir.name, "evidence_manifest_sha256": digest}:
            raise ValueError(f"PSO point {index} manifest changed")
        optimizer.tell(cost["cost"])
        recomputed.append(row)
    best = min(recomputed, key=lambda row: (row["diagnostic_cost"], row["point_index"]))
    if summary.get("best_diagnostic_point") != best:
        raise ValueError("PSO best point differs from replayed source evidence")
    return {"status": "verified", "run_id": search_dir.name,
            "points_verified": len(recomputed), "best_diagnostic_point": best,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a teaching MOS1 matching PSO")
    parser.add_argument("search_dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit_teaching_matching_pso(args.search_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"matching PSO audit failed: {type(exc).__name__}")
    print(f"status={result['status']} points={result['points_verified']} run_id={result['run_id']}")
    print(f"best={result['best_diagnostic_point']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
