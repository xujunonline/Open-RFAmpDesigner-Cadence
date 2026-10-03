from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.compare_teaching_stage2 import audit_teaching_stage2_comparison
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SEED_COLUMNS = (
    "seed", "comparison_run_id", "random_run_id", "pso_run_id",
    "random_best_cost", "pso_best_cost", "pso_minus_random_cost",
)
_EVAL_COLUMNS = (
    "evaluations", "random_mean_best", "pso_mean_best",
    "random_median_best", "pso_median_best",
)


def _json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("teaching multiseed source is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("teaching multiseed metadata must be an object")
    return value


def _source_dirs(comparison_dir: Path) -> tuple[Path, Path]:
    _require_private_path(comparison_dir)
    if not comparison_dir.is_dir() or comparison_dir.is_symlink():
        raise ValueError("teaching comparison archive is missing or unsafe")
    config = _json(comparison_dir / "comparison_config.json")
    if config.get("schema_version") != 1 or set(config) != {
        "schema_version", "random_run_id", "pso_run_id",
    }:
        raise ValueError("teaching comparison source IDs are invalid")
    ids = (config["random_run_id"], config["pso_run_id"])
    if any(not isinstance(value, str) or _RUN_ID.fullmatch(value) is None for value in ids):
        raise ValueError("teaching comparison source ID is unsafe")
    return (
        _PRIVATE_ROOT / "teaching_matching_random" / ids[0],
        _PRIVATE_ROOT / "teaching_matching_pso" / ids[1],
    )


def _profile(config: dict, *, method: str) -> dict:
    if method == "random":
        return {key: value for key, value in config.items() if key not in {"seed", "points"}}
    return {key: value for key, value in config.items() if key != "seed"}


def build_teaching_stage2_multiseed(comparison_dirs: list[Path], run_id: str) -> tuple[list[dict], list[dict], dict]:
    if len(comparison_dirs) < 2 or len(set(comparison_dirs)) != len(comparison_dirs):
        raise ValueError("multiseed comparison needs distinct source archives")
    by_seed: dict[int, dict] = {}
    random_profile = pso_profile = budget = None
    for comparison_dir in comparison_dirs:
        random_dir, pso_dir = _source_dirs(comparison_dir)
        audit_teaching_stage2_comparison(comparison_dir, random_dir, pso_dir)
        comparison = read_evidenced_metrics(comparison_dir)
        random_config = _json(random_dir / "search_config.json")
        pso_config = _json(pso_dir / "search_config.json")
        seed = comparison["seed"]
        if type(seed) is not int or seed < 0 or seed in by_seed:
            raise ValueError("multiseed comparison has duplicate or invalid seeds")
        current_random = _profile(random_config, method="random")
        current_pso = _profile(pso_config, method="pso")
        if random_profile is None:
            random_profile, pso_profile, budget = current_random, current_pso, comparison["budget_per_method"]
        elif (random_profile, pso_profile, budget) != (
            current_random, current_pso, comparison["budget_per_method"],
        ):
            raise ValueError("multiseed comparisons differ in spec, domain, algorithm or budget")
        if comparison.get("not_lna_result") is not True or comparison.get("spec_pass") is not None:
            raise ValueError("teaching comparison claims an LNA result")
        by_seed[seed] = comparison
    seed_rows = []
    for seed, comparison in sorted(by_seed.items()):
        random_best = comparison["metrics"]["random_best_diagnostic_cost"]
        pso_best = comparison["metrics"]["pso_best_diagnostic_cost"]
        seed_rows.append({
            "seed": seed, "comparison_run_id": comparison["run_id"],
            "random_run_id": comparison["random_run_id"], "pso_run_id": comparison["pso_run_id"],
            "random_best_cost": random_best, "pso_best_cost": pso_best,
            "pso_minus_random_cost": pso_best - random_best,
        })
    eval_rows = []
    for index in range(budget):
        random_values = [by_seed[seed]["per_evaluation"][index]["random_best_cost"] for seed in sorted(by_seed)]
        pso_values = [by_seed[seed]["per_evaluation"][index]["pso_best_cost"] for seed in sorted(by_seed)]
        eval_rows.append({
            "evaluations": index + 1,
            "random_mean_best": statistics.mean(random_values),
            "pso_mean_best": statistics.mean(pso_values),
            "random_median_best": statistics.median(random_values),
            "pso_median_best": statistics.median(pso_values),
        })
    better_pso = sum(row["pso_minus_random_cost"] < -1e-9 for row in seed_rows)
    better_random = sum(row["pso_minus_random_cost"] > 1e-9 for row in seed_rows)
    report = {
        "schema_version": 1, "status": "teaching_multiseed_diagnostic_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": (
            "five-seed" if len(by_seed) == 5 else "multi-seed"
        ) + " teaching MOS1 equal-budget pilot; not PDK or paper pass@1/sample efficiency",
        "seeds": sorted(by_seed), "seed_count": len(by_seed), "budget_per_method": budget,
        "source_comparisons": [{
            "seed": seed, "run_id": by_seed[seed]["run_id"],
            "evidence_manifest_sha256": hashlib.sha256(
                (next(path for path in comparison_dirs if path.name == by_seed[seed]["run_id"])
                 / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        } for seed in sorted(by_seed)],
        "per_seed": seed_rows, "per_evaluation": eval_rows,
        "metrics": {
            "random_mean_final_best_cost": statistics.mean(row["random_best_cost"] for row in seed_rows),
            "pso_mean_final_best_cost": statistics.mean(row["pso_best_cost"] for row in seed_rows),
            "pso_lower_seed_count": better_pso,
            "random_lower_seed_count": better_random,
            "equal_seed_count": len(seed_rows) - better_pso - better_random,
        },
    }
    validate_metrics_payload(report)
    return seed_rows, eval_rows, report


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _verify_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict]) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError("multiseed CSV is missing or unsafe")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fieldnames:
            raise ValueError("multiseed CSV header differs")
        saved = list(reader)
    if len(saved) != len(rows):
        raise ValueError("multiseed CSV row count differs")
    for actual, expected in zip(saved, rows, strict=True):
        if set(actual) != set(expected):
            raise ValueError("multiseed CSV fields differ")
        for key, value in expected.items():
            if type(value) in {float, int}:
                if not math.isclose(float(actual[key]), value, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("multiseed CSV differs from source archives")
            elif actual[key] != value:
                raise ValueError("multiseed CSV differs from source archives")


def audit_teaching_stage2_multiseed(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("multiseed report directory is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config = _json(report_dir / "comparison_sources.json")
    ids = config.get("comparison_run_ids")
    if config.get("schema_version") != 1 or not isinstance(ids, list) or any(
        not isinstance(value, str) or _RUN_ID.fullmatch(value) is None for value in ids
    ) or set(config) != {"schema_version", "comparison_run_ids"}:
        raise ValueError("multiseed source list is invalid")
    dirs = [_PRIVATE_ROOT / "teaching_stage2_comparisons" / value for value in ids]
    seed_rows, eval_rows, rebuilt = build_teaching_stage2_multiseed(dirs, report_dir.name)
    if saved != rebuilt:
        raise ValueError("multiseed report differs from reaudited Spectre sources")
    _verify_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _verify_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    return {"status": "verified", "seed_count": len(seed_rows), "budget_per_method": len(eval_rows),
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or reaudit equal-budget teaching Stage 2 seeds")
    parser.add_argument("comparison_dirs", nargs="*", type=Path)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_multiseed")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_multiseed(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    seed_rows, eval_rows, report = build_teaching_stage2_multiseed(args.comparison_dirs, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "comparison_sources.json", {
        "schema_version": 1, "comparison_run_ids": [path.name for path in args.comparison_dirs],
    })
    _write_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _write_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "comparison_sources.json", "per_seed": "per_seed.csv",
        "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
    })
    result = audit_teaching_stage2_multiseed(report_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
