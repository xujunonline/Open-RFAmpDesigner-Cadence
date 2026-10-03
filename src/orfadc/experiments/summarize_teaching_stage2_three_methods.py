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
from orfadc.experiments.audit_teaching_matching_sa import audit_teaching_matching_sa
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_teaching_stage2_multiseed import audit_teaching_stage2_multiseed
from orfadc.metric_contract import validate_metrics_payload


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHARED_CONFIG = (
    "seed", "budget", "nf_user_db", "nf_headroom_db",
    "vbias_v", "wmos_um", "ldd_nh", "cblock_ff",
)
_SEED_COLUMNS = (
    "seed", "random_run_id", "pso_run_id", "sa_run_id",
    "random_best_cost", "pso_best_cost", "sa_best_cost",
)
_EVAL_COLUMNS = (
    "evaluations", "random_mean_best", "pso_mean_best", "sa_mean_best",
    "random_median_best", "pso_median_best", "sa_median_best",
)


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("three-method source metadata is missing or unsafe")

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("three-method source metadata is not an object")
    return value


def build_teaching_stage2_three_methods(
    baseline_dir: Path, sa_dirs: list[Path], run_id: str,
) -> tuple[list[dict], list[dict], dict]:
    _require_private_path(baseline_dir)
    if len(sa_dirs) < 2 or len(set(sa_dirs)) != len(sa_dirs):
        raise ValueError("three-method comparison needs distinct SA seed archives")
    audit_teaching_stage2_multiseed(baseline_dir)
    baseline = read_evidenced_metrics(baseline_dir)
    by_seed = {}
    sa_config_profile = None
    budget = baseline["budget_per_method"]
    for sa_dir in sa_dirs:
        _require_private_path(sa_dir)
        audit_teaching_matching_sa(sa_dir)
        sa = read_evidenced_metrics(sa_dir)
        config = _read_json(sa_dir / "search_config.json")
        seed = sa["seed"]
        if type(seed) is not int or seed < 0 or seed in by_seed or config["budget"] != budget:
            raise ValueError("SA seed or budget is duplicate or mismatched")
        profile = {key: value for key, value in config.items() if key != "seed"}
        if sa_config_profile is None:
            sa_config_profile = profile
        elif profile != sa_config_profile:
            raise ValueError("SA seed runs use different specs, domains or algorithms")
        by_seed[seed] = (sa_dir, sa, config)
    if set(by_seed) != set(baseline["seeds"]):
        raise ValueError("SA seeds differ from the audited random/PSO seeds")
    seed_rows = []
    sa_curves = {}
    for old_row in baseline["per_seed"]:
        seed = old_row["seed"]
        sa_dir, sa, sa_config = by_seed[seed]
        random_dir = _PRIVATE_ROOT / "teaching_matching_random" / old_row["random_run_id"]
        random = read_evidenced_metrics(random_dir)
        random_config = _read_json(random_dir / "search_config.json")
        if any(sa_config[key] != random_config[key] for key in _SHARED_CONFIG):
            raise ValueError("SA and random runs differ in seed, budget, circuit or objective")
        if any(sa["rows"][0][key] != random["rows"][0][key]
               for key in ("lgs_nh", "lss_ph")):
            raise ValueError("SA and random runs lack a shared initial point")
        if sa["points_completed"] != budget or random["points_completed"] != budget:
            raise ValueError("three-method source did not complete the shared budget")
        curve = []
        best = math.inf
        for row in sa["rows"]:
            best = min(best, row["diagnostic_cost"])
            curve.append(best)
        sa_curves[seed] = curve
        seed_rows.append({
            "seed": seed, "random_run_id": old_row["random_run_id"],
            "pso_run_id": old_row["pso_run_id"], "sa_run_id": sa_dir.name,
            "random_best_cost": old_row["random_best_cost"],
            "pso_best_cost": old_row["pso_best_cost"],
            "sa_best_cost": curve[-1],
        })
    eval_rows = []
    for index, old_row in enumerate(baseline["per_evaluation"]):
        if old_row["evaluations"] != index + 1:
            raise ValueError("baseline evaluation order changed")
        values = [sa_curves[seed][index] for seed in sorted(sa_curves)]
        eval_rows.append({
            **old_row, "sa_mean_best": statistics.mean(values),
            "sa_median_best": statistics.median(values),
        })
    payload = {
        "schema_version": 1, "status": "teaching_three_method_diagnostic_verified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "equal-budget MOS1 random/PSO/SA pilot; not PDK or paper sample efficiency",
        "seeds": sorted(by_seed), "seed_count": len(by_seed), "budget_per_method": budget,
        "baseline_run_id": baseline_dir.name,
        "baseline_manifest_sha256": hashlib.sha256(
            (baseline_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "sa_sources": [{
            "seed": seed, "run_id": by_seed[seed][0].name,
            "evidence_manifest_sha256": hashlib.sha256(
                (by_seed[seed][0] / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        } for seed in sorted(by_seed)],
        "per_seed": seed_rows, "per_evaluation": eval_rows,
        "metrics": {
            "random_mean_final_best_cost": statistics.mean(
                row["random_best_cost"] for row in seed_rows),
            "pso_mean_final_best_cost": statistics.mean(
                row["pso_best_cost"] for row in seed_rows),
            "sa_mean_final_best_cost": statistics.mean(
                row["sa_best_cost"] for row in seed_rows),
        },
    }
    validate_metrics_payload(payload)
    return seed_rows, eval_rows, payload


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _verify_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError("three-method CSV is missing or unsafe")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError("three-method CSV fields differ")
        saved = list(reader)
    if len(saved) != len(rows):
        raise ValueError("three-method CSV count differs")
    for actual, expected in zip(saved, rows, strict=True):
        for key in columns:
            if type(expected[key]) in {int, float}:
                if not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("three-method CSV differs from source archives")
            elif actual[key] != expected[key]:
                raise ValueError("three-method CSV differs from source archives")


def audit_teaching_stage2_three_methods(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("three-method report directory is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config = _read_json(report_dir / "source_runs.json")
    if set(config) != {"schema_version", "baseline_run_id", "sa_run_ids"} or config["schema_version"] != 1:
        raise ValueError("three-method source config differs")
    ids = [config["baseline_run_id"], *config["sa_run_ids"]]
    if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in ids):
        raise ValueError("three-method source ID is invalid")
    baseline_dir = _PRIVATE_ROOT / "teaching_stage2_multiseed" / ids[0]
    sa_dirs = [_PRIVATE_ROOT / "teaching_matching_sa" / value for value in ids[1:]]
    seed_rows, eval_rows, rebuilt = build_teaching_stage2_three_methods(baseline_dir, sa_dirs, report_dir.name)
    if saved != rebuilt:
        raise ValueError("three-method report differs from original Spectre sources")
    _verify_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _verify_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    return {"status": "verified", "seed_count": len(seed_rows),
            "budget_per_method": len(eval_rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or audit three teaching Stage 2 methods")
    parser.add_argument("sa_dirs", nargs="*", type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_three_methods")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_three_methods(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    if args.baseline_dir is None:
        parser.error("--baseline-dir is required to create a three-method report")
    _require_private_path(args.report_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    seed_rows, eval_rows, report = build_teaching_stage2_three_methods(args.baseline_dir, args.sa_dirs, run_id)
    report_dir = args.report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "source_runs.json", {
        "schema_version": 1, "baseline_run_id": args.baseline_dir.name,
        "sa_run_ids": [path.name for path in args.sa_dirs],
    })
    _write_csv(report_dir / "per_seed.csv", _SEED_COLUMNS, seed_rows)
    _write_csv(report_dir / "per_evaluation.csv", _EVAL_COLUMNS, eval_rows)
    write_json(report_dir / "metrics.json", report)
    write_evidence_manifest(report_dir, {
        "config": "source_runs.json", "per_seed": "per_seed.csv",
        "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
    })
    result = audit_teaching_stage2_three_methods(report_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
