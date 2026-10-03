from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import summarize_noise
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_pdk_rf_default_hb_sweep import audit_pdk_rf_default_hb_sweep
from orfadc.experiments.audit_pdk_rf_default_three_stage import (
    audit_pdk_rf_default_three_stage, extract_pdk_rf_default_three_stage,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Spec
from orfadc.tools.cost_functions import fullchain_violations


_BASE = _PRIVATE_ROOT / "pdk_three_stage_fixed"
_SWEEPS = _PRIVATE_ROOT / "pdk_rf_hb_sweeps"
_SOURCE_KEYS = ("create_run_id", "baseline_run_id", "sweep_run_id")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_diagnostic_fullchain(
    create_dir: Path, baseline_dir: Path, sweep_dir: Path, spec: Spec, run_id: str,
) -> dict:
    for path in (create_dir, baseline_dir, sweep_dir):
        _require_private_path(path)
    if spec.id != "S1" or spec.band_edges_ghz != (9.0, 11.0):
        raise ValueError("this archived 10 GHz compression probe only supports the S1 diagnostic band")
    audit_pdk_rf_default_three_stage(baseline_dir, create_dir)
    audit_pdk_rf_default_hb_sweep(sweep_dir, _BASE, create_dir, baseline_dir)
    baseline = read_evidenced_metrics(baseline_dir)
    sweep = read_evidenced_metrics(sweep_dir)
    if (
        sweep["oa_create_run_id"] != create_dir.name
        or sweep["baseline_run_id"] != baseline_dir.name
        or sweep["default_geometry_signature_sha256"]
        != baseline["default_geometry_signature_sha256"]
        or sweep["compression"]["status"] != "ok"
        or baseline["physical_qualification"] is not False
        or baseline["cdf_callback_validated"] is not False
        or baseline["spectre_warning_count"] != 5
    ):
        raise ValueError("small-signal and HB sources are not one qualified diagnostic circuit")
    rows, rebuilt_baseline = extract_pdk_rf_default_three_stage(baseline_dir, create_dir)
    if baseline != rebuilt_baseline:
        raise ValueError("small-signal source changed after its raw archive audit")
    low, high = spec.band_edges_ghz
    band_rows = [row for row in rows if low <= row["freq_ghz"] <= high]
    if len(rows) != 161 or len(band_rows) != 81 or band_rows[0]["freq_ghz"] != low or band_rows[-1]["freq_ghz"] != high:
        raise ValueError("S1 diagnostic band is not fully sampled by the archived SP/noise sweep")
    small = {**summarize_sparams(rows, low, high), **summarize_noise(rows, low, high)}
    metrics = {
        **small,
        "ip1db_dbm": sweep["metrics"]["diagnostic_ip1db_dbm"],
        "op1db_dbm": sweep["metrics"]["diagnostic_op1db_dbm"],
        "power_ma": baseline["metrics"]["supply_current_ma"],
    }
    s11_limit_db = -20.0  # Stage 2 diagnostic matching target, not a Table III column.
    violations = fullchain_violations(
        {**metrics, "source": "cadence_spectre_archives",
         "simulation_status": "ok", "circuit_class": "pdk_rf_default_three_stage_probe",
         "not_lna_result": True},
        {**asdict(spec), "s11_max_db": s11_limit_db},
    )
    if violations["status"] != "unverified_score" or violations["pass"] is not False:
        raise ValueError("diagnostic observations must not become a verified LNA score")
    payload = {
        "schema_version": 1, "status": "diagnostic_fullchain_unqualified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_default_three_stage_probe",
        "model_kind": "authorized_pdk_private", "not_lna_result": True,
        "spec_pass": None, "run_id": run_id,
        "scope": "archived same-circuit DC/SP/noise/HB diagnostic; not a qualified LNA or paper result",
        "analysis": ["dc", "sp", "noise", "hb"],
        "diagnostic_spec": asdict(spec), "diagnostic_s11_limit_db": s11_limit_db,
        "frequency_band_ghz": {"low": low, "high": high},
        "points_in_band": len(band_rows),
        "reference_planes": {
            "input": "PORT1 single-ended", "output": "PORT2 differential",
            "input_z0_ohm": baseline["port_reference_ohm"]["input"],
            "output_z0_ohm": baseline["port_reference_ohm"]["output"],
        },
        "metrics": metrics, "violations": violations,
        "source_run_ids": {
            "create_run_id": create_dir.name,
            "baseline_run_id": baseline_dir.name,
            "sweep_run_id": sweep_dir.name,
        },
        "source_manifest_sha256": {
            "baseline": _digest(baseline_dir / "evidence_manifest.json"),
            "sweep": _digest(sweep_dir / "evidence_manifest.json"),
        },
        "physical_qualification": False, "cdf_callback_validated": False,
        "model_warning_resolved": False, "compression_single_frequency_ghz": 10.0,
    }
    return payload


def audit_diagnostic_fullchain(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("diagnostic fullchain archive is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    config_path = report_dir / "source_runs.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("diagnostic fullchain source config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if set(config) != {"schema_version", "spec_id", *_SOURCE_KEYS} or config["schema_version"] != 1:
        raise ValueError("diagnostic fullchain source config differs")
    if config["spec_id"] != "S1" or any(
        not isinstance(config[key], str) or not _ID.fullmatch(config[key])
        for key in _SOURCE_KEYS
    ):
        raise ValueError("diagnostic fullchain source ID is invalid")
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    rebuilt = build_diagnostic_fullchain(
        _BASE / config["create_run_id"], _BASE / config["baseline_run_id"],
        _SWEEPS / config["sweep_run_id"], spec, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("diagnostic fullchain differs from raw Spectre archives")
    return {"status": "verified_diagnostic_only", "run_id": report_dir.name,
            "points_in_band": rebuilt["points_in_band"], "not_lna_result": True,
            "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or audit an archived RF fullchain diagnostic")
    parser.add_argument("--create-dir", type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--sweep-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_diagnostic_fullchain")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_diagnostic_fullchain(args.audit_dir)
        print(f"status={result['status']} points={result['points_in_band']}")
        return 0
    if any(path is None for path in (args.create_dir, args.baseline_dir, args.sweep_dir)):
        parser.error("all three source directories are required")
    _require_private_path(args.output_root)
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    payload = build_diagnostic_fullchain(
        args.create_dir, args.baseline_dir, args.sweep_dir, spec, run_id,
    )
    report_dir = args.output_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "source_runs.json", {
        "schema_version": 1, "spec_id": "S1", **payload["source_run_ids"],
    })
    write_json(report_dir / "metrics.json", payload)
    write_evidence_manifest(report_dir, {
        "config": "source_runs.json", "metrics": "metrics.json",
    })
    result = audit_diagnostic_fullchain(report_dir)
    print(f"status={result['status']} points={result['points_in_band']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
