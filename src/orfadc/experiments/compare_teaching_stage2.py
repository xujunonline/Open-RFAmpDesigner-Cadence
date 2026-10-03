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
from orfadc.experiments.audit_teaching_matching_pso import audit_teaching_matching_pso
from orfadc.experiments.audit_teaching_matching_random import audit_teaching_matching_random
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_SHARED_CONFIG = (
    "seed", "budget", "nf_user_db", "nf_headroom_db",
    "vbias_v", "wmos_um", "ldd_nh", "cblock_ff",
)
_COLUMNS = ("evaluations", "random_cost", "pso_cost", "random_best_cost", "pso_best_cost")


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("comparison source metadata is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("comparison source metadata must be an object")
    return value


def sample_efficiency_rows(random_rows: list[dict], pso_rows: list[dict]) -> list[dict]:
    if not random_rows or len(random_rows) != len(pso_rows):
        raise ValueError("comparison requires the same nonzero number of evaluated points")
    rows = []
    random_best = pso_best = math.inf
    for index, (random_point, pso_point) in enumerate(zip(random_rows, pso_rows, strict=True), 1):
        if random_point.get("point_index") != index - 1 or pso_point.get("point_index") != index - 1:
            raise ValueError("comparison points are not in evaluation order")
        random_cost = random_point.get("diagnostic_cost")
        pso_cost = pso_point.get("diagnostic_cost")
        if any(type(value) not in {int, float} or not math.isfinite(value) or value < 0
               for value in (random_cost, pso_cost)):
            raise ValueError("comparison contains an invalid diagnostic cost")
        random_best = min(random_best, random_cost)
        pso_best = min(pso_best, pso_cost)
        rows.append({
            "evaluations": index, "random_cost": random_cost, "pso_cost": pso_cost,
            "random_best_cost": random_best, "pso_best_cost": pso_best,
        })
    return rows


def build_teaching_stage2_comparison(random_dir: Path, pso_dir: Path, run_id: str) -> tuple[list[dict], dict]:
    audit_teaching_matching_random(random_dir)
    audit_teaching_matching_pso(pso_dir)
    random = read_evidenced_metrics(random_dir)
    pso = read_evidenced_metrics(pso_dir)
    random_config = _read_json(random_dir / "search_config.json")
    pso_config = _read_json(pso_dir / "search_config.json")
    if any(random_config.get(key) != pso_config.get(key) for key in _SHARED_CONFIG):
        raise ValueError("random and PSO runs do not share spec, seed and budget")
    if (random.get("points_completed") != pso.get("points_completed")
            or pso.get("points_completed") != random_config["budget"]):
        raise ValueError("comparison completed point counts differ")
    initial = pso_config["particles"]
    if any(
        any(random["rows"][index][key] != pso["rows"][index][key] for key in ("lgs_nh", "lss_ph"))
        for index in range(initial)
    ):
        raise ValueError("random and PSO do not share their initial particles")
    rows = sample_efficiency_rows(random["rows"], pso["rows"])
    random_best = rows[-1]["random_best_cost"]
    pso_best = rows[-1]["pso_best_cost"]
    report = {
        "schema_version": 1, "status": "teaching_stage2_same_budget_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "one-seed, equal-budget MOS1 diagnostic comparison; not PDK or paper sample efficiency",
        "seed": random_config["seed"], "budget_per_method": random_config["budget"],
        "shared_initial_points": initial,
        "objective": {"nf_user_db": random_config["nf_user_db"],
                      "nf_headroom_db": random_config["nf_headroom_db"], "s11_threshold_db": -20.0},
        "random_run_id": random_dir.name, "pso_run_id": pso_dir.name,
        "random_manifest_sha256": hashlib.sha256((random_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "pso_manifest_sha256": hashlib.sha256((pso_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "per_evaluation": rows,
        "metrics": {
            "random_best_diagnostic_cost": random_best,
            "pso_best_diagnostic_cost": pso_best,
            "pso_minus_random_best_cost": pso_best - random_best,
        },
        "interpretation": "equal_observed_best" if math.isclose(
            pso_best, random_best, rel_tol=0.0, abs_tol=1e-9,
        )
                          else "different_observed_best_without_significance_claim",
    }
    validate_metrics_payload(report)
    return rows, report


def audit_teaching_stage2_comparison(report_dir: Path, random_dir: Path, pso_dir: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("comparison report directory is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config = _read_json(report_dir / "comparison_config.json")
    if config != {
        "schema_version": 1, "random_run_id": random_dir.name, "pso_run_id": pso_dir.name,
    }:
        raise ValueError("comparison config disagrees with selected source archives")
    rows, rebuilt = build_teaching_stage2_comparison(random_dir, pso_dir, report_dir.name)
    if saved != rebuilt:
        raise ValueError("comparison report differs from original Spectre archives")
    with (report_dir / "comparison.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("comparison CSV columns differ")
        saved_rows = list(reader)
    if len(saved_rows) != len(rows):
        raise ValueError("comparison CSV count differs")
    for actual, expected in zip(saved_rows, rows, strict=True):
        if any(not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12)
               for key in _COLUMNS):
            raise ValueError("comparison CSV differs from original Spectre archives")
    return {"status": "verified", "run_id": report_dir.name, "budget_per_method": len(rows),
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare or audit equal-budget teaching random and PSO runs")
    parser.add_argument("--random-dir", type=Path, required=True)
    parser.add_argument("--pso-dir", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_comparisons")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_comparison(args.audit_dir, args.random_dir, args.pso_dir)
        print(f"status={result['status']} budget={result['budget_per_method']} run_id={result['run_id']}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows, report = build_teaching_stage2_comparison(args.random_dir, args.pso_dir, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "comparison_config.json", {
        "schema_version": 1, "random_run_id": args.random_dir.name, "pso_run_id": args.pso_dir.name,
    })
    with (report_dir / "comparison.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "comparison_config.json", "comparison": "comparison.csv", "metrics": "metrics.json",
    })
    result = audit_teaching_stage2_comparison(report_dir, args.random_dir, args.pso_dir)
    print(f"status={result['status']} budget={result['budget_per_method']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
