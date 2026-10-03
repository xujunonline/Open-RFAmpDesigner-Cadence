from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path

from ..cadence.evidence import read_evidenced_metrics
from ..metric_contract import validate_metrics_payload
from ..schemas import Candidate, Spec
from ..tools.cost_functions import fullchain_violations


def validated_fullchain_violations(candidate: Candidate, result: dict, spec: Spec) -> dict:
    if not isinstance(result, dict):
        raise ValueError("observation must be an object")
    validate_metrics_payload(result)
    recorded_candidate = result.get("candidate")
    recorded_spec = result.get("spec")
    if not isinstance(recorded_candidate, dict) or not isinstance(recorded_spec, dict):
        raise ValueError("candidate and spec context are required")
    if (
        recorded_candidate.get("candidate_id") != candidate.candidate_id
        or recorded_candidate.get("spec_id") != candidate.spec_id
        or recorded_candidate.get("seed") != candidate.seed
        or candidate.spec_id != spec.id
    ):
        raise ValueError("observation does not match the candidate")
    if any(recorded_spec.get(key) != value for key, value in asdict(spec).items()):
        raise ValueError("observation does not match the spec")
    band = result.get("frequency_band_ghz")
    low, high = spec.band_edges_ghz
    if not isinstance(band, dict) or not all(
        math.isclose(band.get(key, float("nan")), expected, rel_tol=1e-9)
        for key, expected in (("low", low), ("high", high))
    ):
        raise ValueError("observation does not cover the spec band")
    if (
        result.get("status") not in {"ok", "ok_with_warnings"}
        or result.get("source") != "cadence_spectre"
        or result.get("simulation_status") != "ok"
        or result.get("circuit_class") != "active_lna"
        or result.get("not_lna_result") is not False
        or result.get("spec_pass") is None
        or not isinstance(result.get("analysis"), list)
        or not {"dc", "sp", "noise", "compression"}.issubset(result["analysis"])
        or not isinstance(result.get("reference_planes"), dict)
    ):
        raise ValueError("complete Cadence LNA evaluation is required")
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("metrics are required")
    violations = fullchain_violations(
        {
            **metrics,
            "source": result["source"],
            "simulation_status": result["simulation_status"],
            "circuit_class": result["circuit_class"],
            "not_lna_result": result["not_lna_result"],
        },
        recorded_spec,
    )
    if violations["status"] != "evaluated":
        raise ValueError("fullchain metrics are incomplete")
    return violations


class Refiner:
    def refine_from_run(self, candidate: Candidate, run_dir: Path, spec: Spec) -> Candidate:
        try:
            result = read_evidenced_metrics(run_dir)
        except (OSError, TypeError, ValueError):
            candidate.notes.append("Run evidence is missing, incomplete, or has changed.")
            candidate.status = "needs_evaluation"
            return candidate
        if result.get("spec_pass") is True:
            candidate.notes.append("Raw fullchain metrics must be re-extracted before acceptance.")
            candidate.status = "needs_evaluation"
            return candidate
        return self.refine(candidate, result, spec)

    def refine(self, candidate: Candidate, result: dict, spec: Spec) -> Candidate:
        try:
            violations = validated_fullchain_violations(candidate, result, spec)
        except (TypeError, ValueError, KeyError):
            candidate.notes.append("A matching, complete backend evaluation is required before refinement.")
            candidate.status = "needs_evaluation"
            return candidate
        if violations.get("nf_violation", 0.0) > 0:
            candidate.notes.append("Increase NF headroom and rerun Stage 2.")
            candidate.status = "retry_stage2"
        elif violations.get("gain_violation", 0.0) > 0:
            candidate.notes.append("Rerun Stage 3 band planning with tighter gain distribution.")
            candidate.status = "retry_stage3"
        elif violations.get("ip1db_violation", 0.0) > 0:
            candidate.notes.append("Reallocate gain/current to improve linearity.")
            candidate.status = "retry_stage1_or_stage3"
        elif violations.get("s11_violation", 0.0) > 0:
            candidate.notes.append("Rerun Stage 2 input matching.")
            candidate.status = "retry_stage2"
        elif violations.get("power_violation", 0.0) > 0:
            candidate.notes.append("Reallocate stage current within the power budget.")
            candidate.status = "retry_stage1"
        else:
            candidate.notes.append("Raw fullchain metrics must be re-extracted before acceptance.")
            candidate.status = "needs_evaluation"
        return candidate
