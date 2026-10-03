from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.audit_teaching_matching_random import _close, _read_json
from orfadc.experiments.run_teaching_matching_ga import _GA_COLUMNS
from orfadc.tools.cost_functions import stage2_cost
from orfadc.tools.stage2_ga import TeachingStage2GA


_SETTINGS = {
    "schema_version": 1, "method": "two_individual_ga_teaching",
    "population": 2, "crossover_alpha_range": [0.55, 0.9],
    "normalized_mutation_radius": 0.2,
    "lgs_nh_range": [0.7, 1.3], "lss_ph_range": [180.0, 320.0],
    "vbias_v": 0.65, "wmos_um": 300.0, "ldd_nh": 2.0, "cblock_ff": 5000.0,
    "scope": "MOS1 teaching diagnostic only; not scikit-opt, PDK or paper Stage 2",
}


def audit_teaching_matching_ga(search_dir: Path) -> dict:
    """Replay each GA proposal and score from its original Spectre archive."""
    if not search_dir.is_dir() or search_dir.is_symlink():
        raise ValueError("GA search directory is missing or symlinked")
    summary = read_evidenced_metrics(search_dir)
    config = _read_json(search_dir / "search_config.json")
    if set(config) != {*_SETTINGS, "seed", "budget", "nf_user_db", "nf_headroom_db"}:
        raise ValueError("GA config fields differ from the fixed comparison contract")
    if any(config[key] != value for key, value in _SETTINGS.items()):
        raise ValueError("GA method or fixed circuit settings changed")
    optimizer = TeachingStage2GA(config["seed"], config["budget"])
    nf_user_db = config["nf_user_db"]
    nf_headroom_db = config["nf_headroom_db"]
    if (
        any(type(value) not in {int, float} or not math.isfinite(value)
            for value in (nf_user_db, nf_headroom_db))
        or nf_user_db <= 0 or not 0 <= nf_headroom_db < nf_user_db
    ):
        raise ValueError("invalid GA NF objective")
    csv_path = search_dir / "search.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked GA CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _GA_COLUMNS:
            raise ValueError("GA CSV columns disagree with the contract")
        saved_csv = list(reader)
    if len(saved_csv) != optimizer.budget:
        raise ValueError("GA CSV point count differs from the budget")
    rows = []
    source_manifests = []
    for index in range(optimizer.budget):
        point = optimizer.ask()
        generation = optimizer.generation
        point_dir = search_dir / f"point_{index:02d}"
        if point_dir.is_symlink():
            raise ValueError("symlinked GA point is not accepted")
        original = read_evidenced_metrics(point_dir)
        if original.get("status") != "ok_with_warnings" or original.get("design_parameters") != {
            "vbias_v": 0.65, "wmos_um": 300.0, **point,
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        }:
            raise ValueError(f"GA point {index} differs from replayed proposal")
        audited = audit_teaching_lna(point_dir)
        metrics = audited["metrics"]
        cost = stage2_cost(metrics["nf_db"], nf_user_db, metrics["s11_db"], nf_headroom_db)
        optimizer.tell(cost["cost"])
        row = {
            "point_index": index, "run_id": point_dir.name, **point,
            "nf_worst_db": metrics["nf_db"], "s11_worst_db": metrics["s11_db"],
            "s21_worst_db": metrics["s21_db"],
            "nf_violation": cost["nf_violation"],
            "s11_violation": cost["s11_violation"],
            "diagnostic_cost": cost["cost"],
            "minimum_k_sampled": audited["stability"]["minimum_k"],
            "generation": generation, "best_cost_after": optimizer.best_cost,
        }
        if saved_csv[index].get("run_id") != point_dir.name:
            raise ValueError(f"GA point {index} CSV identity mismatch")
        for key in _GA_COLUMNS:
            if key == "run_id":
                continue
            try:
                value = float(saved_csv[index][key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"GA point {index} CSV {key} is invalid") from exc
            _close(value, row[key], f"GA point {index} CSV {key}")
        rows.append(row)
        source_manifests.append({
            "run_id": point_dir.name,
            "evidence_manifest_sha256": hashlib.sha256(
                (point_dir / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        })
    best = min(rows, key=lambda row: (row["diagnostic_cost"], row["point_index"]))
    rebuilt = {
        "schema_version": 1, "status": "ga_search_complete",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": search_dir.name,
        "scope": "bounded MOS1 Stage 2 teaching GA; not PDK or paper matching",
        "seed": config["seed"], "points_requested": optimizer.budget,
        "points_completed": optimizer.budget, "failures": [],
        "best_diagnostic_point": best,
        "source_manifests": source_manifests, "rows": rows,
    }
    if summary != rebuilt:
        raise ValueError("GA summary differs from replayed original Spectre archives")
    return {"status": "verified", "run_id": search_dir.name,
            "points_verified": len(rows), "best_diagnostic_point": best,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of teaching MOS1 matching GA")
    parser.add_argument("search_dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit_teaching_matching_ga(args.search_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"matching GA audit failed: {type(exc).__name__}")
    print(f"status={result['status']} points={result['points_verified']} run_id={result['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
