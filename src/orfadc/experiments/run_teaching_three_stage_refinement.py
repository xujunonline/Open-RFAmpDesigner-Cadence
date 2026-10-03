from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import RemoteRunner
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage_candidate import run_teaching_three_stage_candidate
from orfadc.schemas import Candidate, Spec


_LOAD_CAPACITANCE_FF = 62.0


def resonance_seed_nh(spec: Spec) -> float:
    if spec.id != "S1" or not 8 <= spec.fc_ghz <= 12:
        raise ValueError("teaching resonance seed only supports the S1 8..12 GHz domain")
    return round(1e9 / ((2 * math.pi * spec.fc_ghz * 1e9) ** 2 * _LOAD_CAPACITANCE_FF * 1e-15), 6)


def _source(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("feedback source path is not portable")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("feedback source path escapes the private root")
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("feedback source path is linked")
    if not cursor.is_dir() or not cursor.resolve().is_relative_to(root.resolve()):
        raise ValueError("feedback source directory is absent or unsafe")
    return cursor


def _require_candidate_location(run_dir: Path, runs_root: Path, candidate: Candidate) -> str:
    relative = run_dir.resolve().relative_to(runs_root.resolve())
    if (
        len(relative.parts) != 4
        or relative.parts[:3] != (candidate.spec_id, f"seed{candidate.seed}", candidate.candidate_id)
        or relative.parts[3] != run_dir.name
    ):
        raise ValueError("teaching archive path does not match candidate identity")
    return relative.as_posix()


def _proposal(first_dir: Path, runs_root: Path, spec: Spec, seed: int) -> tuple[Candidate, dict, dict]:
    _require_private_path(first_dir)
    if not first_dir.resolve().is_relative_to(runs_root.resolve()):
        raise ValueError("initial teaching archive is outside the candidate run root")
    evidence = read_evidenced_metrics(first_dir)
    if not isinstance(evidence.get("candidate"), dict):
        raise ValueError("initial teaching archive lacks a bounded candidate")
    first = Candidate(**evidence["candidate"])
    if (
        first.spec_id != spec.id or first.seed != seed
        or first.status != "teaching_three_stage_diagnostic"
        or first.active_params or first.power_ratio_list or first.notes
        or set(first.passive_params) != {"output_tune_ff", "output_secondary_nh"}
        or first.passive_params["output_tune_ff"] != 0
    ):
        raise ValueError("initial three-stage candidate is not the bounded untuned source")
    first_relative = _require_candidate_location(first_dir, runs_root, first)
    observed = observe_teaching_three_stage_candidate(first_dir, spec, first)
    target = resonance_seed_nh(spec)
    if (
        observed["s22_worst_db"] <= -10
        or observed["s21_worst_db"] >= spec.gain_db
        or first.passive_params["output_secondary_nh"] >= target
        or not 0.5 <= target <= 16
    ):
        raise ValueError("initial raw result does not justify this one-step resonance seed")
    candidate = Candidate(
        candidate_id=f"{spec.id}_seed{seed}_teach3_resonance",
        spec_id=spec.id, seed=seed, power_ratio_list=[], active_params={},
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": target},
        status="teaching_three_stage_diagnostic", notes=[],
    )
    proposal = {
        "schema_version": 1, "status": "planned_teaching_resonance_seed",
        "spec": asdict(spec), "seed": seed,
        "first_run_relative": first_relative,
        "first_candidate_id": first.candidate_id,
        "first_manifest_sha256": observed["evidence_manifest_sha256"],
        "first_observation": observed,
        "load_capacitance_ff": _LOAD_CAPACITANCE_FF,
        "target_output_secondary_nh": target,
        "second_candidate": candidate.to_dict(),
        "not_lna_result": True, "spec_pass": None,
    }
    return candidate, observed, proposal


def rebuild_teaching_three_stage_feedback(trace_dir: Path, runs_root: Path) -> dict:
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    proposal = json.loads((trace_dir / "proposal.json").read_text(encoding="utf-8"))
    if (trace_dir / "evaluation_unverified.json").exists():
        raise ValueError("teaching feedback evaluation failed outside the recovery protocol")
    if (trace_dir / "dispatch_uncertain.json").exists() and not (
        trace_dir / "recovery_ack.json"
    ).is_file():
        raise ValueError("teaching feedback dispatch remains unverified")
    try:
        spec = Spec(**proposal["spec"])
        first_dir = _source(runs_root, proposal["first_run_relative"])
        second_dir = _source(runs_root, proposal["second_run_relative"])
        second = Candidate(**proposal["second_candidate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("teaching feedback proposal context is invalid") from exc
    recomputed, first_observation, expected_proposal = _proposal(
        first_dir, runs_root, spec, proposal["seed"],
    )
    expected_proposal["second_run_relative"] = proposal["second_run_relative"]
    if proposal != expected_proposal or second.to_dict() != recomputed.to_dict():
        raise ValueError("teaching feedback proposal differs from the original raw source")
    _require_candidate_location(second_dir, runs_root, second)
    second_observation = observe_teaching_three_stage_candidate(second_dir, spec, second)
    if (trace_dir / "dispatch_uncertain.json").exists():
        expected_ack = _recovery_ack(trace_dir, proposal, second_dir, second_observation)
        ack_path = trace_dir / "recovery_ack.json"
        if not ack_path.is_file() or json.loads(ack_path.read_text(encoding="utf-8")) != expected_ack:
            raise ValueError("teaching feedback dispatch remains unverified")
    elif (trace_dir / "recovery_ack.json").exists():
        raise ValueError("teaching feedback has an unexpected recovery acknowledgement")
    return {
        "schema_version": 1, "status": "audited_teaching_three_stage_feedback",
        "spec_id": spec.id, "seed": proposal["seed"],
        "first_run_relative": proposal["first_run_relative"],
        "second_run_relative": proposal["second_run_relative"],
        "first_observation": first_observation,
        "second_observation": second_observation,
        "delta_s21_worst_db": second_observation["s21_worst_db"] - first_observation["s21_worst_db"],
        "delta_s22_worst_db": second_observation["s22_worst_db"] - first_observation["s22_worst_db"],
        "compression_status": "not_measured",
        "not_lna_result": True, "spec_pass": None,
    }


def audit_teaching_three_stage_feedback(trace_dir: Path, runs_root: Path) -> dict:
    expected = rebuild_teaching_three_stage_feedback(trace_dir, runs_root)
    saved = json.loads((trace_dir / "feedback_summary.json").read_text(encoding="utf-8"))
    if saved != expected:
        raise ValueError("teaching feedback summary differs from source-audited observations")
    return expected


def _recovery_ack(trace_dir: Path, proposal: dict, second_dir: Path, observation: dict) -> dict:
    marker = json.loads((trace_dir / "dispatch_uncertain.json").read_text(encoding="utf-8"))
    if marker != {
        "schema_version": 1, "status": "unverified_candidate_dispatch",
        "second_run_relative": proposal["second_run_relative"],
        "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
    }:
        raise ValueError("teaching feedback uncertainty marker differs from planned dispatch")
    status = json.loads((second_dir / "probe_status.json").read_text(encoding="utf-8"))
    if status.get("dispatch_protocol_version") != 4 or status.get("recovery_mode") != "remote_quiescent_raw":
        raise ValueError("teaching feedback second candidate lacks audited remote recovery")
    return {
        "schema_version": 1, "status": "recovered_no_redispatch",
        "second_run_relative": proposal["second_run_relative"],
        "second_manifest_sha256": observation["evidence_manifest_sha256"],
        "not_lna_result": True, "spec_pass": None,
    }


def finalize_teaching_three_stage_feedback(trace_dir: Path, runs_root: Path) -> dict:
    """Close a recovered second run from source archives, without a new remote call."""
    for path in (trace_dir, runs_root):
        _require_private_path(path)
    with agent_run_lock(trace_dir):
        proposal = json.loads((trace_dir / "proposal.json").read_text(encoding="utf-8"))
        if (trace_dir / "evaluation_unverified.json").exists():
            raise ValueError("teaching feedback evaluation failed outside the recovery protocol")
        if not (trace_dir / "dispatch_uncertain.json").is_file():
            raise ValueError("teaching feedback has no uncertain second dispatch")
        spec = Spec(**proposal["spec"])
        second = Candidate(**proposal["second_candidate"])
        first_dir = _source(runs_root, proposal["first_run_relative"])
        expected_candidate, _, expected_proposal = _proposal(first_dir, runs_root, spec, proposal["seed"])
        expected_proposal["second_run_relative"] = proposal["second_run_relative"]
        if proposal != expected_proposal or second.to_dict() != expected_candidate.to_dict():
            raise ValueError("teaching feedback proposal differs from the original raw source")
        second_dir = _source(runs_root, proposal["second_run_relative"])
        _require_candidate_location(second_dir, runs_root, second)
        observation = observe_teaching_three_stage_candidate(second_dir, spec, second)
        expected_ack = _recovery_ack(trace_dir, proposal, second_dir, observation)
        ack_path = trace_dir / "recovery_ack.json"
        if ack_path.exists():
            if json.loads(ack_path.read_text(encoding="utf-8")) != expected_ack:
                raise ValueError("teaching feedback recovery acknowledgement changed")
        else:
            write_json(ack_path, expected_ack)
        summary_path = trace_dir / "feedback_summary.json"
        if summary_path.exists():
            return audit_teaching_three_stage_feedback(trace_dir, runs_root)
        summary = rebuild_teaching_three_stage_feedback(trace_dir, runs_root)
        write_json(summary_path, summary)
        return audit_teaching_three_stage_feedback(trace_dir, runs_root)


def run_teaching_three_stage_refinement(
    config_path: Path, runs_root: Path, trace_root: Path, first_dir: Path, spec: Spec, *, seed: int,
    runner: RemoteRunner | None = None,
) -> tuple[Path, dict]:
    for path in (runs_root, trace_root, first_dir):
        _require_private_path(path)
    candidate, _, proposal = _proposal(first_dir, runs_root, spec, seed)
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    trace_dir.mkdir(exist_ok=False)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    second_dir = runs_root / spec.id / f"seed{seed}" / candidate.candidate_id / run_id
    proposal["second_run_relative"] = second_dir.relative_to(runs_root).as_posix()
    write_json(trace_dir / "proposal.json", proposal)
    try:
        run_teaching_three_stage_candidate(
            config_path, runs_root, spec, candidate, run_id=run_id, runner=runner,
        )
    except RemoteEvaluationUncertain:
        write_json(trace_dir / "dispatch_uncertain.json", {
            "schema_version": 1, "status": "unverified_candidate_dispatch",
            "second_run_relative": proposal["second_run_relative"],
            "safe_to_retry": False,
            "not_lna_result": True, "spec_pass": None,
        })
        raise
    except (OSError, ValueError, RuntimeError):
        write_json(trace_dir / "evaluation_unverified.json", {
            "schema_version": 1, "status": "candidate_evaluation_unverified",
            "second_run_relative": proposal["second_run_relative"],
            "safe_to_retry": False, "not_lna_result": True, "spec_pass": None,
        })
        raise
    summary = rebuild_teaching_three_stage_feedback(trace_dir, runs_root)
    write_json(trace_dir / "feedback_summary.json", summary)
    audit_teaching_three_stage_feedback(trace_dir, runs_root)
    return trace_dir, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="One raw-audited output resonance feedback step on a public three-stage RF probe")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_feedback")
    parser.add_argument("--first-dir", type=Path)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--audit-trace", type=Path)
    action.add_argument("--finalize-trace", type=Path)
    args = parser.parse_args()
    if args.audit_trace is not None:
        report = audit_teaching_three_stage_feedback(args.audit_trace, args.runs_root)
        print(f"status={report['status']} not_lna_result=true")
        return 0
    if args.finalize_trace is not None:
        report = finalize_teaching_three_stage_feedback(args.finalize_trace, args.runs_root)
        print(f"status={report['status']} not_lna_result=true")
        return 0
    if args.first_dir is None:
        parser.error("--first-dir is required unless --audit-trace is provided")
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching feedback spec")
    try:
        trace_dir, report = run_teaching_three_stage_refinement(
            args.config, args.runs_root, args.trace_root, args.first_dir,
            specs[args.spec], seed=args.seed,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_dir={trace_dir.resolve()} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
