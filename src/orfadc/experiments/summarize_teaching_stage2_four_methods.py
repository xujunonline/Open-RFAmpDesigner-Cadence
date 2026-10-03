from __future__ import annotations

import argparse
import hashlib
import math
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_matching_ga import audit_teaching_matching_ga
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_teaching_stage2_three_methods import (
    _SHARED_CONFIG, _read_json, _verify_csv, _write_csv,
    audit_teaching_stage2_three_methods,
)
from orfadc.metric_contract import validate_metrics_payload


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SEED_COLUMNS = (
    "seed", "random_run_id", "pso_run_id", "sa_run_id", "ga_run_id",
    "random_best_cost", "pso_best_cost", "sa_best_cost", "ga_best_cost",
)
_EVAL_COLUMNS = (
    "evaluations", "random_mean_best", "pso_mean_best", "sa_mean_best", "ga_mean_best",
    "random_median_best", "pso_median_best", "sa_median_best", "ga_median_best",
)


def build_teaching_stage2_four_methods(
    three_dir: Path, ga_dirs: list[Path], run_id: str,
) -> tuple[list[dict], list[dict], dict]:
    _require_private_path(three_dir)
    if len(ga_dirs) < 2 or len(set(ga_dirs)) != len(ga_dirs):
        raise ValueError("four-method comparison needs distinct GA archives")
    audit_teaching_stage2_three_methods(three_dir)
    baseline = read_evidenced_metrics(three_dir)
    budget = baseline["budget_per_method"]
    by_seed = {}
    profile = None
    for ga_dir in ga_dirs:
        _require_private_path(ga_dir)
        audit_teaching_matching_ga(ga_dir)
        ga = read_evidenced_metrics(ga_dir)
        config = _read_json(ga_dir / "search_config.json")
        seed = ga["seed"]
        if type(seed) is not int or seed < 0 or seed in by_seed or config["budget"] != budget:
            raise ValueError("GA seed or budget is duplicate or mismatched")
        candidate_profile = {key: value for key, value in config.items() if key != "seed"}
        if profile is None:
            profile = candidate_profile
        elif candidate_profile != profile:
            raise ValueError("GA seed runs use different domains, objectives or algorithms")
        by_seed[seed] = ga_dir, ga, config
    if set(by_seed) != set(baseline["seeds"]):
        raise ValueError("GA seeds differ from the audited three-method seeds")
    seed_rows = []
    ga_curves = {}
    for old_row in baseline["per_seed"]:
        seed = old_row["seed"]
        ga_dir, ga, ga_config = by_seed[seed]
        random_dir = _PRIVATE_ROOT / "teaching_matching_random" / old_row["random_run_id"]
        random = read_evidenced_metrics(random_dir)
        random_config = _read_json(random_dir / "search_config.json")
        if any(ga_config[key] != random_config[key] for key in _SHARED_CONFIG):
            raise ValueError("GA and random runs differ in seed, budget, circuit or objective")
        if ga["points_completed"] != budget or random["points_completed"] != budget:
            raise ValueError("four-method source did not complete the shared budget")
        if any(ga["rows"][0][key] != random["rows"][0][key]
               for key in ("lgs_nh", "lss_ph")):
            raise ValueError("GA and random runs lack a shared initial point")
        best = math.inf
        curve = []
        for row in ga["rows"]:
            best = min(best, row["diagnostic_cost"])
            curve.append(best)
        ga_curves[seed] = curve
        seed_rows.append({
            **old_row, "ga_run_id": ga_dir.name, "ga_best_cost": curve[-1],
        })
    eval_rows = []
    for index, old_row in enumerate(baseline["per_evaluation"]):
        if old_row["evaluations"] != index + 1:
            raise ValueError("three-method evaluation order changed")
        values = [ga_curves[seed][index] for seed in sorted(ga_curves)]
        eval_rows.append({
            **old_row, "ga_mean_best": statistics.mean(values),
            "ga_median_best": statistics.median(values),
        })
    payload = {
        "schema_version": 1, "status": "teaching_four_method_diagnostic_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "equal-budget MOS1 random/PSO/SA/GA pilot; not PDK or paper sample efficiency",
        "seeds": sorted(by_seed), "seed_count": len(by_seed), "budget_per_method": budget,
        "three_method_run_id": three_dir.name,
        "three_method_manifest_sha256": hashlib.sha256(
            (three_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "ga_sources": [{
            "seed": seed, "run_id": by_seed[seed][0].name,
            "evidence_manifest_sha256": hashlib.sha256(
                (by_seed[seed][0] / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        } for seed in sorted(by_seed)],
        "per_seed": seed_rows, "per_evaluation": eval_rows,
        "metrics": {
            f"{method}_mean_final_best_cost": statistics.mean(
                row[f"{method}_best_cost"] for row in seed_rows
            ) for method in ("random", "pso", "sa", "ga")
        },
    }
    validate_metrics_payload(payload)
    return seed_rows, eval_rows, payload


def audit_teaching_stage2_four_methods(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("four-method report directory is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config = _read_json(report_dir / "source_runs.json")
    if set(config) != {"schema_version", "three_method_run_id", "ga_run_ids"} or config["schema_version"] != 1:
        raise ValueError("four-method source config differs")
    ids = [config["three_method_run_id"], *config["ga_run_ids"]]
    if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in ids):
        raise ValueError("four-method source ID is invalid")
    three_dir = _PRIVATE_ROOT / "teaching_stage2_three_methods" / ids[0]
    ga_dirs = [_PRIVATE_ROOT / "teaching_matching_ga" / value for value in ids[1:]]
    seed_rows, eval_rows, rebuilt = build_teaching_stage2_four_methods(three_dir, ga_dirs, report_dir.name)
    if saved != rebuilt:
        raise ValueError("four-method report differs from original Spectre sources")
    _verify_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _verify_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    return {"status": "verified", "seed_count": len(seed_rows),
            "budget_per_method": len(eval_rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or audit four teaching Stage 2 methods")
    parser.add_argument("ga_dirs", nargs="*", type=Path)
    parser.add_argument("--three-method-dir", type=Path)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_four_methods")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_four_methods(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    if args.three_method_dir is None:
        parser.error("--three-method-dir is required to create a four-method report")
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    seed_rows, eval_rows, report = build_teaching_stage2_four_methods(
        args.three_method_dir, args.ga_dirs, run_id,
    )
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "source_runs.json", {
        "schema_version": 1, "three_method_run_id": args.three_method_dir.name,
        "ga_run_ids": [path.name for path in args.ga_dirs],
    })
    _write_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _write_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "source_runs.json", "per_seed": "per_seed.csv",
        "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
    })
    result = audit_teaching_stage2_four_methods(report_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
