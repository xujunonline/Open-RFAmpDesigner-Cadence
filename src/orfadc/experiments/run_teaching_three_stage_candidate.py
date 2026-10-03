from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner
from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage
from orfadc.config_loader import load_specs
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage import run_teaching_three_stage
from orfadc.schemas import Candidate, Spec


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def run_teaching_three_stage_candidate(
    config_path: Path, runs_root: Path, spec: Spec, candidate: Candidate, *,
    run_id: str | None = None, runner: RemoteRunner | None = None,
) -> tuple[Path, dict]:
    """Evaluate a bounded S1 teaching candidate; preserve raw Spectre evidence."""
    _require_private_path(runs_root)
    if (
        type(candidate.seed) is not int or candidate.seed < 0
        or candidate.spec_id != spec.id or spec.id != "S1" or not _ID.fullmatch(spec.id)
        or spec.band_edges_ghz[0] < 8 or spec.band_edges_ghz[1] > 12
        or not _ID.fullmatch(candidate.candidate_id)
        or candidate.passive_params.keys() != {"output_tune_ff", "output_secondary_nh"}
        or candidate.status != "teaching_three_stage_diagnostic"
        or candidate.active_params or candidate.power_ratio_list or candidate.notes
        or candidate.sim_result is not None
    ):
        raise ValueError("three-stage candidate has an unsafe context or parameter set")
    render_teaching_three_stage(
        output_tune_ff=candidate.passive_params["output_tune_ff"],
        output_secondary_nh=candidate.passive_params["output_secondary_nh"],
    )
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
        raise ValueError("three-stage candidate run ID is unsafe")
    run_dir = runs_root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / run_id
    cursor = runs_root
    for part in (spec.id, f"seed{candidate.seed}", candidate.candidate_id, run_id):
        cursor = cursor / part
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("three-stage candidate path is linked")
    if run_dir.exists() or run_dir.is_symlink():
        raise FileExistsError("three-stage candidate run ID already exists")
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = run_teaching_three_stage(
        config_path, run_dir,
        output_tune_ff=candidate.passive_params["output_tune_ff"],
        output_secondary_nh=candidate.passive_params["output_secondary_nh"],
        candidate=candidate, spec=spec, runner=runner,
    )
    if audit_teaching_three_stage(run_dir)["status"] != "verified":
        raise ValueError("three-stage candidate raw source audit failed")
    return run_dir, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded public MOS1 three-stage RF candidate")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output-secondary-nh", type=float, required=True)
    parser.add_argument("--output-tune-ff", type=float, default=0.0)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown three-stage candidate spec")
    candidate = Candidate(
        candidate_id=args.candidate_id, spec_id=args.spec, seed=args.seed,
        power_ratio_list=[], active_params={},
        passive_params={
            "output_tune_ff": args.output_tune_ff,
            "output_secondary_nh": args.output_secondary_nh,
        },
        status="teaching_three_stage_diagnostic", notes=[],
    )
    try:
        run_dir, payload = run_teaching_three_stage_candidate(
            args.config, args.runs_root, specs[args.spec], candidate,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} run_dir={run_dir.resolve()} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
