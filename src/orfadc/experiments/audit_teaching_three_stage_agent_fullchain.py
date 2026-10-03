from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.audit_teaching_three_stage_hb_sweep import audit_three_stage_hb_sweep
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_three_stage_refinement import _source
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate, Spec


def _sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("same-candidate source file is missing or linked")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_teaching_three_stage_agent_fullchain(
    agent_trace: Path, runs_root: Path, hb_sweep: Path, hb_root: Path,
    spec: Spec, report_id: str,
) -> dict:
    """Bind a teaching agent's second small-signal candidate to its own HB sweep."""
    for path in (agent_trace, runs_root, hb_sweep, hb_root):
        _require_private_path(path)
    feedback = audit_teaching_three_stage_agent_feedback(agent_trace, runs_root, spec)
    audit_three_stage_hb_sweep(hb_sweep, hb_root)
    candidate_dir = _source(runs_root, feedback["second_run_relative"])
    evidence = read_evidenced_metrics(candidate_dir)
    candidate = Candidate(**evidence["candidate"])
    observation = observe_teaching_three_stage_candidate(candidate_dir, spec, candidate)
    sweep = read_evidenced_metrics(hb_sweep)
    ids = sweep["point_run_ids"]
    first_hb = hb_root / ids[0]
    settings = sweep.get("parameters")
    if (
        candidate.candidate_id != f"{spec.id}_seed{feedback['seed']}_teach3_resonance"
        or candidate.passive_params.get("output_tune_ff") != 0.0
        or candidate.active_params or candidate.power_ratio_list
        or settings != {
            "output_secondary_nh": candidate.passive_params["output_secondary_nh"],
            "frequency_ghz": 10.0, "harmonics": 7,
        }
        or (candidate_dir / "netlist.scs").read_bytes() != render_teaching_three_stage(
            output_secondary_nh=candidate.passive_params["output_secondary_nh"],
        )
        or _sha256(candidate_dir / "teaching_mos1_model.scs") != _sha256(PUBLIC_MODEL)
        or _sha256(first_hb / "teaching_mos1_model.scs") != _sha256(PUBLIC_MODEL)
        or sweep["compression"]["status"] != "ok"
        or sweep["compression"]["ip1db_dbm"] is None
        or sweep["compression"]["op1db_dbm"] is None
    ):
        raise ValueError("HB sweep does not belong to the planned second teaching candidate")
    maximum_s_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        first_grid, first_values = parse_complex_trace(candidate_dir / "sp.sp", signal)
        hb_grid, hb_values = parse_complex_trace(first_hb / "sp.sp", signal)
        if first_grid != hb_grid or len(first_values) != 161:
            raise ValueError("same-candidate SP grids differ")
        maximum_s_delta = max(
            maximum_s_delta,
            *(abs(left - right) for left, right in zip(first_values, hb_values, strict=True)),
        )
    if maximum_s_delta > 1e-8:
        raise ValueError("agent candidate and HB sweep small-signal S differ")
    candidate_noise = noise_rows_from_psfascii(
        candidate_dir / "sp.noise.sp", nf_signal="NF", nf_unit="db", nfmin_signal="NFmin",
    )
    hb_noise = noise_rows_from_psfascii(
        first_hb / "sp.noise.sp", nf_signal="NF", nf_unit="db", nfmin_signal="NFmin",
    )
    if len(candidate_noise) != 161 or len(hb_noise) != len(candidate_noise):
        raise ValueError("same-candidate noise grids differ")
    maximum_noise_delta = 0.0
    for left, right in zip(candidate_noise, hb_noise, strict=True):
        if left["freq_hz"] != right["freq_hz"]:
            raise ValueError("same-candidate noise frequency grids differ")
        maximum_noise_delta = max(
            maximum_noise_delta, abs(left["nf_db"] - right["nf_db"]),
            abs(left["nfmin_db"] - right["nfmin_db"]),
        )
    if not math.isfinite(maximum_noise_delta) or maximum_noise_delta > 1e-8:
        raise ValueError("agent candidate and HB sweep noise differ")
    report = {
        "schema_version": 1, "status": "verified_same_teaching_candidate_diagnostic_fullchain",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "run_id": report_id, "spec_id": spec.id, "seed": feedback["seed"],
        "candidate_id": candidate.candidate_id,
        "scope": "same public MOS1 candidate SP/noise and 10 GHz HB; no physical LNA qualification",
        "analysis": ["dc", "sp", "noise", "hb"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "agent_trace_id": agent_trace.name,
        "candidate_run_relative": feedback["second_run_relative"],
        "hb_sweep_run_id": hb_sweep.name,
        "agent_summary_sha256": _sha256(agent_trace / "feedback_summary.json"),
        "candidate_manifest_sha256": _sha256(candidate_dir / "evidence_manifest.json"),
        "hb_sweep_manifest_sha256": _sha256(hb_sweep / "evidence_manifest.json"),
        "hb_points": sweep["points_completed"],
        "same_circuit_except_hb_stimulus": True,
        "maximum_complex_s_delta": maximum_s_delta,
        "maximum_noise_db_delta": maximum_noise_delta,
        "compression_status": "diagnostic_p1db_bracketed",
        "metrics": {
            "s11_db": observation["s11_worst_db"],
            "s21_db": observation["s21_worst_db"],
            "s22_db": observation["s22_worst_db"],
            "nf_db": observation["nf_worst_db"],
            "ripple_db": observation["s21_ripple_db"],
            "supply_current_ma": observation["supply_current_ma"],
            "diagnostic_ip1db_dbm": sweep["compression"]["ip1db_dbm"],
            "diagnostic_op1db_dbm": sweep["compression"]["op1db_dbm"],
        },
        "physical_qualification": False,
        "not_lna_result": True, "spec_pass": None,
    }
    validate_metrics_payload(report)
    return report


def audit_teaching_three_stage_agent_fullchain(
    report_dir: Path, agent_trace: Path, runs_root: Path, hb_sweep: Path,
    hb_root: Path, spec: Spec,
) -> dict:
    _require_private_path(report_dir)
    saved = read_evidenced_metrics(report_dir)
    rebuilt = build_teaching_three_stage_agent_fullchain(
        agent_trace, runs_root, hb_sweep, hb_root, spec, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("teaching same-candidate report differs from its raw sources")
    return {"status": "verified", "run_id": report_dir.name,
            "not_lna_result": True, "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind a teaching planned agent candidate to an independent HB sweep")
    parser.add_argument("agent_trace", type=Path)
    parser.add_argument("hb_sweep", type=Path)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_hb")
    parser.add_argument("--report-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_agent_fullchain")
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown teaching spec")
    try:
        if args.audit_dir is not None:
            result = audit_teaching_three_stage_agent_fullchain(
                args.audit_dir, args.agent_trace, args.runs_root,
                args.hb_sweep, args.hb_root, specs[args.spec],
            )
            print(f"status={result['status']} report_dir={args.audit_dir.resolve()} not_lna_result=true")
            return 0
        _require_private_path(args.report_root)
        report_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_teaching_three_stage_agent_fullchain(
            args.agent_trace, args.runs_root, args.hb_sweep, args.hb_root,
            specs[args.spec], report_id,
        )
        report_dir = args.report_root / report_id
        report_dir.mkdir(parents=True, exist_ok=False)
        write_json(report_dir / "metrics.json", report)
        write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
        audit_teaching_three_stage_agent_fullchain(
            report_dir, args.agent_trace, args.runs_root, args.hb_sweep,
            args.hb_root, specs[args.spec],
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        parser.error(type(exc).__name__)
    print(f"status=verified report_dir={report_dir.resolve()} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
