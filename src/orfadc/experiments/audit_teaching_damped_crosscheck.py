from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.ocean_ascii import read_ocnprint_trace, read_ocean_vdd_current
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace, parse_struct_values
from orfadc.config_loader import write_json
from orfadc.experiments.audit_diagnostic_pair import _sha256
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.audit_teaching_oa import audit_teaching_oa
from orfadc.experiments.audit_teaching_oa_crosscheck import compare_samples
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_DESIGN = {
    "vbias_v": 0.65, "wmos_um": 300.0, "lgs_nh": 1.0, "lss_ph": 240.0,
    "ldd_nh": 1.68809309279457, "cblock_ff": 225.079079039277,
    "rdamp_ohm": 150.0, "sp_intervals": 160,
    "sp_start_ghz": 8.0, "sp_stop_ghz": 12.0,
}
_DESIGNS = {
    "damped": _DESIGN,
    "cascode": {**_DESIGN, "topology": "cascode", "vcas_v": 0.95},
}
_REPORT_IDENTITIES = {
    "damped": ("verified_teaching_damped_crosscheck", "teaching_mos1_damped_common_source"),
    "cascode": ("verified_teaching_cascode_crosscheck", "teaching_mos1_cascode"),
}


def build_teaching_damped_crosscheck(oa_dir: Path, direct_dir: Path, run_id: str) -> dict:
    """Compare independent OA/OCEAN and direct Spectre runs of one public circuit."""
    if any(not path.is_dir() or path.is_symlink() for path in (oa_dir, direct_dir)):
        raise ValueError("damped crosscheck source directory is missing or symlinked")
    oa_audit = audit_teaching_oa(oa_dir)
    direct_audit = audit_teaching_lna(direct_dir)
    oa = read_evidenced_metrics(oa_dir)
    direct = read_evidenced_metrics(direct_dir)
    topology = oa.get("teaching_topology")
    expected_design = _DESIGNS.get(topology)
    if topology == "cascode":
        expected_design = {**_DESIGN, "topology": "cascode", "vcas_v": oa.get("teaching_vcas_v", 0.95)}
    if (
        topology not in _DESIGNS
        or oa.get("ocn_precision_digits") != 15
        or direct.get("design_parameters") != expected_design
        or oa_audit["points_verified"] != 161
        or direct_audit["points_verified"] != 161
    ):
        raise ValueError("crosscheck sources are not the same 161-point teaching candidate")
    frequency_delta = 0.0
    complex_deltas = {}
    for signal in ("s11", "s21", "s12", "s22"):
        direct_f, direct_values = parse_complex_trace(direct_dir / "sp.sp", signal)
        real_f, real = read_ocnprint_trace(
            oa_dir / "ocnprint" / f"{signal}_real.txt",
            header_fragment=f'real(getData("{signal}"',
        )
        imag_f, imag = read_ocnprint_trace(
            oa_dir / "ocnprint" / f"{signal}_imag.txt",
            header_fragment=f'imag(getData("{signal}"',
        )
        if len(real_f) != len(imag_f) or any(
            not math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-3)
            for left, right in zip(real_f, imag_f, strict=True)
        ):
            raise ValueError(f"{signal} OCEAN real/imag frequency grids differ")
        grid_delta, value_delta = compare_samples(
            direct_f, direct_values, real_f,
            [complex(left, right) for left, right in zip(real, imag, strict=True)],
            name=signal, value_tolerance=1e-8,
        )
        frequency_delta = max(frequency_delta, grid_delta)
        complex_deltas[signal] = value_delta
    noise_deltas = {}
    for signal in ("NF", "NFmin", "F", "Fmin"):
        direct_f, direct_values = parse_scalar_trace(direct_dir / "sp.noise.sp", signal)
        export_f, export_values = read_ocnprint_trace(
            oa_dir / "ocnprint" / f"{signal}.txt",
            header_fragment=f'getData("{signal}"',
        )
        grid_delta, value_delta = compare_samples(
            direct_f, direct_values, export_f, export_values,
            name=signal, value_tolerance=1e-8,
        )
        frequency_delta = max(frequency_delta, grid_delta)
        noise_deltas[signal] = value_delta
    current_delta = read_ocean_vdd_current(oa_dir / "ocnprint/report.txt") - direct_audit["metrics"]["supply_current_ma"]
    if not math.isclose(current_delta, 0, rel_tol=0, abs_tol=1e-6):
        raise ValueError("OA and direct Spectre supply current differ")
    for key, expected in direct_audit["metrics"].items():
        actual = oa_audit["metrics"].get(key)
        if type(actual) not in {int, float} or not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-6):
            raise ValueError(f"OA and direct Spectre band metric {key} differ")
    if oa_audit["stability_quality"] != "sampled_grid_only":
        raise ValueError("OA stability export lacks valid 15-digit sampled-grid quality")
    report_status, circuit_class = _REPORT_IDENTITIES[topology]
    report = {
        "schema_version": 1, "status": report_status,
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": circuit_class, "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "public MOS1 OA/OCEAN vs standalone Spectre data; ideal passives, not a qualified LNA",
        "analysis": ["dc", "sp", "noise"],
        "oa_run_id": oa_dir.name, "direct_run_id": direct_dir.name,
        "oa_manifest_sha256": _sha256(oa_dir / "evidence_manifest.json"),
        "direct_manifest_sha256": _sha256(direct_dir / "evidence_manifest.json"),
        "points": 161, "maximum_frequency_delta_hz": frequency_delta,
        "maximum_complex_s_delta": complex_deltas,
        "maximum_noise_delta": noise_deltas,
        "supply_current_delta_ma": current_delta,
        "metrics": direct_audit["metrics"],
        "stability_quality": oa_audit["stability_quality"],
    }
    if topology == "cascode" and "device_op" in oa_audit:
        device_deltas = {}
        for instance, fields in oa_audit["device_op"].items():
            direct_fields = parse_struct_values(direct_dir / "dcOpInfo.info", instance=instance, struct_type="mos1")
            differences = {field: abs(value - direct_fields[field]) for field, value in fields.items()}
            if any(not math.isclose(value, direct_fields[field], rel_tol=1e-8, abs_tol=1e-20)
                   for field, value in fields.items()):
                raise ValueError("cascode OA and direct Spectre device operating points differ")
            device_deltas[instance] = differences
        report["maximum_device_op_delta"] = device_deltas
    validate_metrics_payload(report)
    return report


def audit_teaching_damped_crosscheck_report(report_dir: Path, oa_root: Path, direct_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("damped crosscheck report directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    oa_id = saved.get("oa_run_id")
    direct_id = saved.get("direct_run_id")
    if any(not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
           for value in (oa_id, direct_id)):
        raise ValueError("invalid damped crosscheck source identity")
    rebuilt = build_teaching_damped_crosscheck(oa_root / oa_id, direct_root / direct_id, report_dir.name)
    if saved != rebuilt:
        raise ValueError("damped crosscheck report differs from source archives")
    return {"status": "verified", "run_id": report_dir.name, "points": 161, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-audit OA/OCEAN and direct Spectre damped or cascode MOS1 archives")
    parser.add_argument("oa_dir", type=Path)
    parser.add_argument("direct_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_damped_crosschecks")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_teaching_damped_crosscheck(args.oa_dir, args.direct_dir, run_id)
        output_dir = args.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "metrics.json", report)
        write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
        audit_teaching_damped_crosscheck_report(output_dir, args.oa_dir.parent, args.direct_dir.parent)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"damped crosscheck failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points={report['points']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
