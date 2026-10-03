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
from orfadc.experiments.audit_teaching_matching_bo import audit_teaching_matching_bo
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_teaching_stage2_four_methods import (
    _EVAL_COLUMNS as _FOUR_EVAL_COLUMNS,
    _SEED_COLUMNS as _FOUR_SEED_COLUMNS,
    audit_teaching_stage2_four_methods,
)
from orfadc.experiments.summarize_teaching_stage2_three_methods import (
    _SHARED_CONFIG, _read_json, _verify_csv, _write_csv,
)
from orfadc.metric_contract import validate_metrics_payload


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SEED_COLUMNS = (*_FOUR_SEED_COLUMNS, "bo_run_id", "bo_best_cost")
_EVAL_COLUMNS = (*_FOUR_EVAL_COLUMNS, "bo_mean_best", "bo_median_best")


def build_teaching_stage2_five_methods(
    four_dir: Path, bo_dirs: list[Path], run_id: str,
) -> tuple[list[dict], list[dict], dict]:
    _require_private_path(four_dir)
    if len(bo_dirs) < 2 or len(set(bo_dirs)) != len(bo_dirs):
        raise ValueError("five-method comparison needs distinct BO archives")
    audit_teaching_stage2_four_methods(four_dir)
    baseline = read_evidenced_metrics(four_dir)
    budget = baseline["budget_per_method"]
    by_seed = {}
    profile = None
    for bo_dir in bo_dirs:
        _require_private_path(bo_dir)
        audit_teaching_matching_bo(bo_dir)
        bo = read_evidenced_metrics(bo_dir)
        config = _read_json(bo_dir / "search_config.json")
        seed = bo["seed"]
        if type(seed) is not int or seed < 0 or seed in by_seed or config["budget"] != budget:
            raise ValueError("BO seed or budget is duplicate or mismatched")
        candidate_profile = {key: value for key, value in config.items()
                             if key not in {"seed", "initial_points"}}
        if profile is None:
            profile = candidate_profile
        elif candidate_profile != profile:
            raise ValueError("BO seed runs use different domains, objectives or algorithms")
        by_seed[seed] = bo_dir, bo, config
    if set(by_seed) != set(baseline["seeds"]):
        raise ValueError("BO seeds differ from the audited four-method seeds")
    seed_rows = []
    bo_curves = {}
    for old_row in baseline["per_seed"]:
        seed = old_row["seed"]
        bo_dir, bo, bo_config = by_seed[seed]
        random_dir = _PRIVATE_ROOT / "teaching_matching_random" / old_row["random_run_id"]
        random = read_evidenced_metrics(random_dir)
        random_config = _read_json(random_dir / "search_config.json")
        if any(bo_config[key] != random_config[key] for key in _SHARED_CONFIG):
            raise ValueError("BO and random runs differ in seed, budget, circuit or objective")
        if bo["points_completed"] != budget or random["points_completed"] != budget:
            raise ValueError("five-method source did not complete the shared budget")
        for index in range(2):
            if any(bo["rows"][index][key] != random["rows"][index][key]
                   for key in ("lgs_nh", "lss_ph", "diagnostic_cost")):
                raise ValueError("BO and random runs lack two identical initialization results")
        best = math.inf
        curve = []
        for row in bo["rows"]:
            best = min(best, row["diagnostic_cost"])
            curve.append(best)
        bo_curves[seed] = curve
        seed_rows.append({**old_row, "bo_run_id": bo_dir.name, "bo_best_cost": curve[-1]})
    eval_rows = []
    for index, old_row in enumerate(baseline["per_evaluation"]):
        if old_row["evaluations"] != index + 1:
            raise ValueError("four-method evaluation order changed")
        values = [bo_curves[seed][index] for seed in sorted(bo_curves)]
        eval_rows.append({
            **old_row, "bo_mean_best": statistics.mean(values),
            "bo_median_best": statistics.median(values),
        })
    payload = {
        "schema_version": 1, "status": "teaching_five_method_diagnostic_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "equal-budget MOS1 random/PSO/SA/GA/BO pilot; not PDK or paper sample efficiency",
        "seeds": sorted(by_seed), "seed_count": len(by_seed), "budget_per_method": budget,
        "four_method_run_id": four_dir.name,
        "four_method_manifest_sha256": hashlib.sha256(
            (four_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "bo_sources": [{
            "seed": seed, "run_id": by_seed[seed][0].name,
            "evidence_manifest_sha256": hashlib.sha256(
                (by_seed[seed][0] / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        } for seed in sorted(by_seed)],
        "per_seed": seed_rows, "per_evaluation": eval_rows,
        "metrics": {
            f"{method}_mean_final_best_cost": statistics.mean(
                row[f"{method}_best_cost"] for row in seed_rows
            ) for method in ("random", "pso", "sa", "ga", "bo")
        },
    }
    validate_metrics_payload(payload)
    return seed_rows, eval_rows, payload


def audit_teaching_stage2_five_methods(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("five-method report directory is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config = _read_json(report_dir / "source_runs.json")
    if set(config) != {"schema_version", "four_method_run_id", "bo_run_ids"} or config["schema_version"] != 1:
        raise ValueError("five-method source config differs")
    ids = [config["four_method_run_id"], *config["bo_run_ids"]]
    if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in ids):
        raise ValueError("five-method source ID is invalid")
    four_dir = _PRIVATE_ROOT / "teaching_stage2_four_methods" / ids[0]
    bo_dirs = [_PRIVATE_ROOT / "teaching_matching_bo" / value for value in ids[1:]]
    seed_rows, eval_rows, rebuilt = build_teaching_stage2_five_methods(four_dir, bo_dirs, report_dir.name)
    if saved != rebuilt:
        raise ValueError("five-method report differs from original Spectre sources")
    _verify_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _verify_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    return {"status": "verified", "seed_count": len(seed_rows),
            "budget_per_method": len(eval_rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or audit five teaching Stage 2 methods")
    parser.add_argument("bo_dirs", nargs="*", type=Path)
    parser.add_argument("--four-method-dir", type=Path)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_five_methods")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_five_methods(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    if args.four_method_dir is None:
        parser.error("--four-method-dir is required to create a five-method report")
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    seed_rows, eval_rows, report = build_teaching_stage2_five_methods(
        args.four_method_dir, args.bo_dirs, run_id,
    )
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "source_runs.json", {
        "schema_version": 1, "four_method_run_id": args.four_method_dir.name,
        "bo_run_ids": [path.name for path in args.bo_dirs],
    })
    _write_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _write_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "source_runs.json", "per_seed": "per_seed.csv",
        "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
    })
    result = audit_teaching_stage2_five_methods(report_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
