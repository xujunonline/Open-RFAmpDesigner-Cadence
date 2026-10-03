from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.hb_metrics import extract_sp_s21_at_frequency
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_diagnostic_pair import _sha256
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


def build_cascode_comparison(common_dir: Path, cascode_dir: Path, run_id: str) -> dict:
    if any(not path.is_dir() or path.is_symlink() for path in (common_dir, cascode_dir)):
        raise ValueError("cascode comparison source directory is missing or symlinked")
    common_audit = audit_teaching_lna(common_dir)
    cascode_audit = audit_teaching_lna(cascode_dir)
    common = read_evidenced_metrics(common_dir)
    cascode = read_evidenced_metrics(cascode_dir)
    baseline_design = common.get("design_parameters")
    cascode_design = cascode.get("design_parameters")
    if (
        common.get("circuit_class") != "teaching_mos1_common_source"
        or cascode.get("circuit_class") != "teaching_mos1_cascode"
        or not isinstance(baseline_design, dict)
        or not isinstance(cascode_design, dict)
        or cascode_design != {**baseline_design, "topology": "cascode", "vcas_v": 0.95}
        or common_audit["points_verified"] != cascode_audit["points_verified"]
        or common_audit["points_verified"] != 161
        or not isinstance(cascode_audit.get("cascode_op"), dict)
    ):
        raise ValueError("cascode comparison requires matched 161-point teaching designs")
    maximum_s_deltas = {}
    for signal in ("s11", "s21", "s12", "s22"):
        common_f, common_values = parse_complex_trace(common_dir / "sp.sp", signal)
        cascode_f, cascode_values = parse_complex_trace(cascode_dir / "sp.sp", signal)
        if common_f != cascode_f or len(common_f) != 161:
            raise ValueError("cascode S-parameter frequency grids differ")
        maximum_s_deltas[signal] = max(abs(left - right) for left, right in zip(
            common_values, cascode_values, strict=True,
        ))
    maximum_noise_deltas = {}
    for signal in ("NF", "NFmin"):
        common_f, common_values = parse_scalar_trace(common_dir / "sp.noise.sp", signal)
        cascode_f, cascode_values = parse_scalar_trace(cascode_dir / "sp.noise.sp", signal)
        if common_f != cascode_f or len(common_f) != 161:
            raise ValueError("cascode noise frequency grids differ")
        maximum_noise_deltas[signal] = max(abs(left - right) for left, right in zip(
            common_values, cascode_values, strict=True,
        ))
    common_metrics = common_audit["metrics"]
    cascode_metrics = cascode_audit["metrics"]
    delta = {key: cascode_metrics[key] - value for key, value in common_metrics.items()
             if key in cascode_metrics and type(value) in {int, float}}
    m1 = cascode_audit["device_op"]
    m2 = cascode_audit["cascode_op"]
    report = {
        "schema_version": 1, "status": "verified_teaching_cascode_comparison",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_cascode", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "single-stage public MOS1 topology comparison; not a foundry LNA or paper result",
        "analysis": ["dc", "sp", "noise"],
        "common_run_id": common_dir.name, "cascode_run_id": cascode_dir.name,
        "common_manifest_sha256": _sha256(common_dir / "evidence_manifest.json"),
        "cascode_manifest_sha256": _sha256(cascode_dir / "evidence_manifest.json"),
        "points": 161, "common_metrics": common_metrics, "cascode_metrics": cascode_metrics,
        "metric_delta_cascode_minus_common": delta,
        "s21_10ghz_db": {
            "common": extract_sp_s21_at_frequency(common_dir / "sp.sp", 10e9),
            "cascode": extract_sp_s21_at_frequency(cascode_dir / "sp.sp", 10e9),
        },
        "maximum_complex_s_difference": maximum_s_deltas,
        "maximum_nf_difference_db": maximum_noise_deltas,
        "minimum_k": {
            "common": common_audit["stability"]["minimum_k"],
            "cascode": cascode_audit["stability"]["minimum_k"],
        },
        "cascode_device_op": {
            "m1_ids_ma": m1["ids"] * 1e3, "m2_ids_ma": m2["ids"] * 1e3,
            "m1_vds_minus_vdsat_v": m1["vds"] - m1["vdsat"],
            "m2_vds_minus_vdsat_v": m2["vds"] - m2["vdsat"],
        },
        "metrics": cascode_metrics,
    }
    if any(not math.isfinite(value) for value in (*maximum_s_deltas.values(), *maximum_noise_deltas.values())):
        raise ValueError("nonfinite cascode trace difference")
    validate_metrics_payload(report)
    return report


def audit_cascode_comparison_report(report_dir: Path, source_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("cascode comparison report directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    names = (saved.get("common_run_id"), saved.get("cascode_run_id"))
    if any(not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None for name in names):
        raise ValueError("invalid cascode comparison source identity")
    rebuilt = build_cascode_comparison(source_root / names[0], source_root / names[1], report_dir.name)
    if saved != rebuilt:
        raise ValueError("cascode comparison report differs from source archives")
    return {"status": "verified", "run_id": report_dir.name, "points": 161, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare archived public MOS1 common-source and cascode runs")
    parser.add_argument("common_dir", type=Path)
    parser.add_argument("cascode_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_cascode_comparisons")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_cascode_comparison(args.common_dir, args.cascode_dir, run_id)
        output_dir = args.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "metrics.json", report)
        write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
        audit_cascode_comparison_report(output_dir, args.common_dir.parent)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"cascode comparison failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points={report['points']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
