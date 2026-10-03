from __future__ import annotations

import argparse
import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.passive_quality import oneport_impedance
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_inductor_oneport import audit_pdk_inductor_oneport
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_TARGETS_HZ = (8e9, 10e9, 12e9)


def _at(frequency: list[float], values: list[complex], target: float) -> complex:
    matches = [value for sample, value in zip(frequency, values, strict=True)
               if math.isclose(sample, target, rel_tol=1e-12, abs_tol=1.0)]
    if len(matches) != 1:
        raise ValueError("RF source lacks one exact target frequency")
    return matches[0]


def _s11_db(impedance: complex, reference_ohm: float) -> float:
    gamma = (impedance - reference_ohm) / (impedance + reference_ohm)
    return 20 * math.log10(abs(gamma)) if gamma != 0 else float("-inf")


def build_pdk_rf_input_match(
    active_dir: Path, create_dir: Path, spiral_dir: Path, run_id: str,
) -> dict:
    for path in (active_dir, create_dir, spiral_dir):
        _require_private_path(path)
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("input-match report ID is unsafe")
    audit_pdk_rf_default_three_stage(active_dir, create_dir)
    audit_pdk_inductor_oneport(spiral_dir)
    active = read_evidenced_metrics(active_dir)
    spiral = read_evidenced_metrics(spiral_dir)
    if (
        active.get("model_kind") != "authorized_pdk_private"
        or active.get("not_lna_result") is not True
        or spiral.get("source_run_kind") != "oa_default_pdk_spiral_direct_spectre"
        or spiral.get("physical_qualification") is not False
    ):
        raise ValueError("input-match source provenance differs")
    input_frequency, input_s11 = parse_complex_trace(active_dir / "sp.sp", "s11")
    spiral_frequency, spiral_s11 = parse_complex_trace(spiral_dir / "sp.sp", "s11")
    spiral_z = oneport_impedance(_at(spiral_frequency, spiral_s11, 10e9), 50.0)
    effective_spiral_l_h = spiral_z.imag / (2 * math.pi * 10e9)
    if effective_spiral_l_h <= 0 or not math.isfinite(effective_spiral_l_h):
        raise ValueError("default spiral is not inductive at the target center")
    samples = []
    for sample in _TARGETS_HZ:
        z = oneport_impedance(_at(input_frequency, input_s11, sample), 50.0)
        required_l_h = -z.imag / (2 * math.pi * sample)
        if z.real <= 0 or required_l_h <= 0 or not math.isfinite(required_l_h):
            raise ValueError("input port cannot be compensated by a positive ideal series L")
        samples.append({
            "frequency_ghz": sample / 1e9,
            "input_resistance_ohm": z.real,
            "input_reactance_ohm": z.imag,
            "ideal_additional_series_l_nh": required_l_h * 1e9,
            "measured_s11_db": _s11_db(z, 50.0),
        })
    center_l_h = samples[1]["ideal_additional_series_l_nh"] * 1e-9
    for row in samples:
        frequency = row["frequency_ghz"] * 1e9
        z = complex(row["input_resistance_ohm"], row["input_reactance_ohm"])
        row["predicted_s11_with_center_series_l_db"] = _s11_db(
            z + 1j * 2 * math.pi * frequency * center_l_h, 50.0,
        )
    source_dirs = {"active": active_dir, "create": create_dir, "spiral": spiral_dir}
    source_record_sha256 = {
        name: hashlib.sha256((path / ("run_status.json" if name == "create" else "evidence_manifest.json")).read_bytes()).hexdigest()
        for name, path in source_dirs.items()
    }
    report = {
        "schema_version": 1, "status": "source_bound_input_match_estimate",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_default_input_match_diagnostic",
        "model_kind": "authorized_pdk_private", "not_lna_result": True,
        "spec_pass": None, "run_id": run_id,
        "scope": "Algebraic series-L estimate from audited PDK S11; no new candidate was simulated",
        "source_run_ids": {name: path.name for name, path in source_dirs.items()},
        "source_record_sha256": source_record_sha256,
        "samples": samples,
        "ideal_center_additional_l_nh": center_l_h * 1e9,
        "default_spiral_effective_l_nh_at_10ghz": effective_spiral_l_h * 1e9,
        "ideal_l_to_default_spiral_l_ratio": center_l_h / effective_spiral_l_h,
        "default_spiral_minimum_q_8_to_12ghz": spiral["metrics"]["minimum_q_in_band"],
        "reference_ohm": 50.0, "no_candidate_simulated": True,
        "physical_qualification": False, "cdf_callback_validated": False,
        "assumption": "Only an ideal additional series L is inserted before the measured active input; "
                      "the existing input network remains and the other port stays at its SP reference load.",
    }
    validate_metrics_payload(report)
    return report


def write_pdk_rf_input_match(
    active_dir: Path, create_dir: Path, spiral_dir: Path, output_dir: Path,
) -> dict:
    _require_private_path(output_dir)
    report = build_pdk_rf_input_match(active_dir, create_dir, spiral_dir, output_dir.name)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "metrics.json", report)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
    return report


def audit_pdk_rf_input_match(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("input-match report archive is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    ids = saved.get("source_run_ids")
    if (
        not isinstance(ids, dict) or set(ids) != {"active", "create", "spiral"}
        or any(not isinstance(value, str) or _RUN_ID.fullmatch(value) is None for value in ids.values())
    ):
        raise ValueError("input-match source identities are invalid")
    rebuilt = build_pdk_rf_input_match(
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / ids["active"],
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / ids["create"],
        _PRIVATE_ROOT / "passive_quality_reference" / ids["spiral"],
        report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("input-match estimate differs from reaudited Spectre sources")
    return {"status": "verified", "points": len(rebuilt["samples"]),
            "no_candidate_simulated": True, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze audited PDK RF input mismatch without claiming a new simulation")
    parser.add_argument("--active-dir", type=Path)
    parser.add_argument("--create-dir", type=Path)
    parser.add_argument("--spiral-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_input_match_estimates")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_pdk_rf_input_match(args.audit_dir)
        print(f"status={result['status']} points={result['points']} no_candidate_simulated=true")
        return 0
    if any(path is None for path in (args.active_dir, args.create_dir, args.spiral_dir)):
        parser.error("active, create, and spiral archives are required")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = args.output_root / run_id
    write_pdk_rf_input_match(args.active_dir, args.create_dir, args.spiral_dir, output_dir)
    result = audit_pdk_rf_input_match(output_dir)
    print(f"status={result['status']} points={result['points']} no_candidate_simulated=true "
          f"output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
