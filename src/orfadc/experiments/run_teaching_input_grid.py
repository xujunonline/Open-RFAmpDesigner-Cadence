from __future__ import annotations

import argparse
import csv
import hashlib
import math
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_lna import render_teaching_lna_netlist, run_teaching_lna
from orfadc.metric_contract import validate_metrics_payload
from orfadc.tools.cost_functions import stage2_cost


_COLUMNS = (
    "point_index", "run_id", "lgs_nh", "lss_ph", "nf_worst_db", "s11_worst_db",
    "s21_worst_db", "gain_ripple_db", "supply_current_ma", "nf_violation",
    "s11_violation", "diagnostic_cost", "minimum_k_sampled", "maximum_delta_abs_sampled",
)


def run_teaching_input_grid(
    config_path: Path, grid_dir: Path, *, lgs_values_nh: list[float],
    lss_values_ph: list[float], vbias_v: float = 0.65,
    nf_user_db: float = 2.0, nf_headroom_db: float = 0.2,
) -> dict:
    _require_private_path(grid_dir)
    if (
        not isinstance(lgs_values_nh, list) or not 2 <= len(lgs_values_nh) <= 4
        or not isinstance(lss_values_ph, list) or not 2 <= len(lss_values_ph) <= 4
        or len(lgs_values_nh) * len(lss_values_ph) > 12
        or any(type(value) not in {int, float} or not math.isfinite(value)
               for value in (*lgs_values_nh, *lss_values_ph))
        or len(set(lgs_values_nh)) != len(lgs_values_nh)
        or len(set(lss_values_ph)) != len(lss_values_ph)
    ):
        raise ValueError("teaching input grid needs 2..4 distinct values per axis and at most 12 points")
    for value in (nf_user_db, nf_headroom_db):
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("teaching NF target and headroom must be finite")
    if nf_user_db <= 0 or not 0 <= nf_headroom_db < nf_user_db:
        raise ValueError("teaching NF target/headroom must be positive and ordered")
    combinations = list(product(lgs_values_nh, lss_values_ph))
    for lgs_nh, lss_ph in combinations:
        render_teaching_lna_netlist(vbias_v, lgs_nh=lgs_nh, lss_ph=lss_ph)
    grid_dir.mkdir(parents=True, exist_ok=False)
    write_json(grid_dir / "sweep_config.json", {
        "schema_version": 1, "lgs_values_nh": lgs_values_nh,
        "lss_values_ph": lss_values_ph, "vbias_v": vbias_v,
        "wmos_um": 300.0,
        "nf_user_db": nf_user_db, "nf_headroom_db": nf_headroom_db,
        "output_ldd_nh": 2.0, "output_cblock_ff": 5000.0,
        "scope": "MOS1 teaching input matching only; not a foundry or paper result",
    })
    rows = []
    manifests = []
    failures = []
    for index, (lgs_nh, lss_ph) in enumerate(combinations):
        point_dir = grid_dir / f"point_{index:02d}"
        try:
            result = run_teaching_lna(
                config_path, point_dir, vbias_v=vbias_v,
                wmos_um=300.0, lgs_nh=lgs_nh, lss_ph=lss_ph,
            )
            if read_evidenced_metrics(point_dir) != result:
                raise ValueError("teaching input point differs from its evidence manifest")
            if result["status"] != "ok_with_warnings":
                failures.append({"point_index": index, "run_id": point_dir.name,
                                 "backend_status": result["status"]})
                break
            if result.get("design_parameters") != {
                "vbias_v": vbias_v, "lgs_nh": lgs_nh, "lss_ph": lss_ph,
                "ldd_nh": 2.0, "cblock_ff": 5000.0, "wmos_um": 300.0,
            }:
                raise ValueError("teaching input point parameters changed")
            verified = audit_teaching_lna(point_dir)
            metrics = verified["metrics"]
            cost = stage2_cost(metrics["nf_db"], nf_user_db, metrics["s11_db"], nf_headroom_db)
            row = {
                "point_index": index, "run_id": point_dir.name,
                "lgs_nh": float(lgs_nh), "lss_ph": float(lss_ph),
                "nf_worst_db": metrics["nf_db"], "s11_worst_db": metrics["s11_db"],
                "s21_worst_db": metrics["s21_db"], "gain_ripple_db": metrics["ripple_db"],
                "supply_current_ma": metrics["supply_current_ma"],
                "nf_violation": cost["nf_violation"], "s11_violation": cost["s11_violation"],
                "diagnostic_cost": cost["cost"],
                "minimum_k_sampled": verified["stability"]["minimum_k"],
                "maximum_delta_abs_sampled": verified["stability"]["maximum_delta_abs"],
            }
            rows.append(row)
            manifests.append({
                "run_id": point_dir.name,
                "evidence_manifest_sha256": hashlib.sha256(
                    (point_dir / "evidence_manifest.json").read_bytes()
                ).hexdigest(),
            })
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, ZeroDivisionError) as exc:
            failures.append({"point_index": index, "run_id": point_dir.name,
                             "failure_type": type(exc).__name__})
            break
    best = min(rows, key=lambda row: (row["diagnostic_cost"], row["s11_worst_db"], row["point_index"])) if rows else None
    summary = {
        "schema_version": 1, "status": "input_grid_complete" if not failures else "incomplete",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": grid_dir.name,
        "scope": "bounded MOS1 NF/S11 diagnostic; not a PDK LNA or paper Stage 2 completion",
        "points_requested": len(combinations), "points_completed": len(rows),
        "failures": failures, "best_diagnostic_point": best,
        "source_manifests": manifests, "rows": rows,
    }
    validate_metrics_payload(summary)
    with (grid_dir / "input_grid.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(grid_dir / "metrics.json", summary)
    write_evidence_manifest(grid_dir, {
        "metrics": "metrics.json", "config": "sweep_config.json", "grid": "input_grid.csv",
    })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Spectre MOS1 input matching diagnostic grid")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_input_grids")
    parser.add_argument("--lgs-nh", type=float, nargs="+", required=True)
    parser.add_argument("--lss-ph", type=float, nargs="+", required=True)
    parser.add_argument("--vbias-v", type=float, default=0.65)
    parser.add_argument("--nf-user-db", type=float, default=2.0)
    parser.add_argument("--nf-headroom-db", type=float, default=0.2)
    args = parser.parse_args()
    grid_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        result = run_teaching_input_grid(
            args.config, grid_dir, lgs_values_nh=args.lgs_nh,
            lss_values_ph=args.lss_ph, vbias_v=args.vbias_v,
            nf_user_db=args.nf_user_db, nf_headroom_db=args.nf_headroom_db,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(f"teaching input grid failed before archiving: {type(exc).__name__}: {exc}")
    print(f"status={result['status']} points={result['points_completed']} output={grid_dir.resolve()}")
    return 0 if result["status"] == "input_grid_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
