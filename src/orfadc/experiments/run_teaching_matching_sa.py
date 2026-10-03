from __future__ import annotations

import argparse
import csv
import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_lna import run_teaching_lna
from orfadc.experiments.run_teaching_matching_random import _COLUMNS
from orfadc.metric_contract import validate_metrics_payload
from orfadc.tools.cost_functions import stage2_cost
from orfadc.tools.stage2_sa import TeachingStage2SA


_SA_COLUMNS = (*_COLUMNS, "temperature", "accepted", "current_cost_after")


def run_teaching_matching_sa(
    config_path: Path, search_dir: Path, *, seed: int, budget: int,
    nf_user_db: float = 2.0, nf_headroom_db: float = 0.2,
) -> dict:
    _require_private_path(search_dir)
    optimizer = TeachingStage2SA(seed, budget)
    if (
        any(type(value) not in {int, float} or not math.isfinite(value)
            for value in (nf_user_db, nf_headroom_db))
        or nf_user_db <= 0 or not 0 <= nf_headroom_db < nf_user_db
    ):
        raise ValueError("teaching NF target/headroom must be finite, positive and ordered")
    search_dir.mkdir(parents=True, exist_ok=False)
    write_json(search_dir / "search_config.json", {
        "schema_version": 1, "method": "bounded_sa_teaching", "seed": seed,
        "budget": budget, "initial_temperature": 500.0, "cooling": 0.65,
        "normalized_neighbor_radius": 0.25,
        "lgs_nh_range": [0.7, 1.3], "lss_ph_range": [180.0, 320.0],
        "nf_user_db": nf_user_db, "nf_headroom_db": nf_headroom_db,
        "vbias_v": 0.65, "wmos_um": 300.0, "ldd_nh": 2.0, "cblock_ff": 5000.0,
        "scope": "MOS1 teaching diagnostic only; not scikit-opt, PDK or paper Stage 2",
    })
    rows: list[dict] = []
    source_manifests: list[dict] = []
    failures: list[dict] = []
    for index in range(budget):
        point = optimizer.ask()
        point_dir = search_dir / f"point_{index:02d}"
        try:
            result = run_teaching_lna(
                config_path, point_dir, vbias_v=0.65, wmos_um=300.0,
                lgs_nh=point["lgs_nh"], lss_ph=point["lss_ph"],
            )
            if read_evidenced_metrics(point_dir) != result:
                raise ValueError("teaching point differs from its evidence")
            if result.get("status") != "ok_with_warnings":
                failures.append({"point_index": index, "run_id": point_dir.name,
                                 "backend_status": result.get("status")})
                break
            if result.get("design_parameters") != {
                "vbias_v": 0.65, "wmos_um": 300.0, **point,
                "ldd_nh": 2.0, "cblock_ff": 5000.0,
            }:
                raise ValueError("teaching point design parameters changed")
            audited = audit_teaching_lna(point_dir)
            metrics = audited["metrics"]
            cost = stage2_cost(metrics["nf_db"], nf_user_db, metrics["s11_db"], nf_headroom_db)
            temperature = optimizer.temperature
            accepted = optimizer.tell(cost["cost"])
            rows.append({
                "point_index": index, "run_id": point_dir.name, **point,
                "nf_worst_db": metrics["nf_db"], "s11_worst_db": metrics["s11_db"],
                "s21_worst_db": metrics["s21_db"],
                "nf_violation": cost["nf_violation"],
                "s11_violation": cost["s11_violation"],
                "diagnostic_cost": cost["cost"],
                "minimum_k_sampled": audited["stability"]["minimum_k"],
                "temperature": temperature, "accepted": int(accepted),
                "current_cost_after": optimizer.current_cost,
            })
            source_manifests.append({
                "run_id": point_dir.name,
                "evidence_manifest_sha256": hashlib.sha256(
                    (point_dir / "evidence_manifest.json").read_bytes()
                ).hexdigest(),
            })
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, ZeroDivisionError) as exc:
            failures.append({"point_index": index, "run_id": point_dir.name,
                             "failure_type": type(exc).__name__})
            break
    best = min(rows, key=lambda row: (row["diagnostic_cost"], row["point_index"])) if rows else None
    payload = {
        "schema_version": 1, "status": "sa_search_complete" if not failures else "incomplete",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": search_dir.name,
        "scope": "bounded MOS1 Stage 2 teaching SA; not PDK or paper matching",
        "seed": seed, "points_requested": budget, "points_completed": len(rows),
        "failures": failures, "best_diagnostic_point": best,
        "source_manifests": source_manifests, "rows": rows,
    }
    validate_metrics_payload(payload)
    with (search_dir / "search.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_SA_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(search_dir / "metrics.json", payload)
    write_evidence_manifest(search_dir, {
        "metrics": "metrics.json", "config": "search_config.json", "search": "search.csv",
    })
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Spectre MOS1 matching teaching SA")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_matching_sa")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--budget", type=int, default=4)
    parser.add_argument("--nf-user-db", type=float, default=2.0)
    parser.add_argument("--nf-headroom-db", type=float, default=0.2)
    args = parser.parse_args()
    search_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        result = run_teaching_matching_sa(
            args.config, search_dir, seed=args.seed, budget=args.budget,
            nf_user_db=args.nf_user_db, nf_headroom_db=args.nf_headroom_db,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(f"teaching SA failed before archiving: {type(exc).__name__}")
    print(f"status={result['status']} points={result['points_completed']} output={search_dir.resolve()}")
    return 0 if result["status"] == "sa_search_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
