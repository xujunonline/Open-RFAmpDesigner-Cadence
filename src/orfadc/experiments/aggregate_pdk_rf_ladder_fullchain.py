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
from orfadc.experiments.audit_pdk_rf_input_ladder import (
    audit_pdk_rf_input_ladder, extract_pdk_rf_input_ladder,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_pdk_rf_ladder_hb import audit_pdk_rf_ladder_hb_sweep
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Spec
from orfadc.tools.cost_functions import fullchain_violations


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FILES = {"config": "source_runs.json", "metrics": "metrics.json"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pdk_rf_ladder_fullchain(
    ladder_dir: Path, sweep_dir: Path, spec: Spec, run_id: str,
) -> dict:
    for path in (ladder_dir, sweep_dir):
        _require_private_path(path)
    if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
        raise ValueError("RF ladder fullchain report ID is unsafe")
    if spec.id != "S1" or spec.band_edges_ghz != (9.0, 11.0):
        raise ValueError("RF ladder HB archive only supports the S1 diagnostic band")
    audit_pdk_rf_input_ladder(ladder_dir)
    audit_pdk_rf_ladder_hb_sweep(sweep_dir)
    ladder = read_evidenced_metrics(ladder_dir)
    sweep = read_evidenced_metrics(sweep_dir)
    if (
        sweep["ladder_run_id"] != ladder_dir.name
        or sweep["ladder_manifest_sha256"] != _sha256(ladder_dir / "evidence_manifest.json")
        or sweep["compression"]["status"] != "ok"
        or sweep["points_completed"] < 6
        or ladder["source_run_kind"] != "pdk_rf_default_oa_derived_ideal_input_ladder"
        or ladder["physical_qualification"] is not False
        or sweep["physical_qualification"] is not False
        or ladder["cdf_callback_validated"] is not False
        or sweep["cdf_callback_validated"] is not False
        or ladder["spectre_warning_count"] != 5
        or sweep["model_warning_resolved"] is not False
        or ladder["port_reference_ohm"] != sweep["port_reference_ohm"]
        or ladder["not_lna_result"] is not True
        or sweep["not_lna_result"] is not True
        or ladder["spec_pass"] is not None
        or sweep["spec_pass"] is not None
    ):
        raise ValueError("RF ladder SP/noise and HB sources are not one diagnostic candidate")
    rows, rebuilt_ladder = extract_pdk_rf_input_ladder(ladder_dir)
    if ladder != rebuilt_ladder:
        raise ValueError("RF ladder small-signal source changed after raw audit")
    low, high = spec.band_edges_ghz
    band_rows = [row for row in rows if low <= row["freq_ghz"] <= high]
    if (
        len(rows) != 161 or len(band_rows) != 81
        or band_rows[0]["freq_ghz"] != low or band_rows[-1]["freq_ghz"] != high
    ):
        raise ValueError("S1 diagnostic band is not fully covered by the RF ladder archive")
    metrics = {
        **summarize_sparams(rows, low, high),
        **summarize_noise(rows, low, high),
        "ip1db_dbm": sweep["metrics"]["diagnostic_ip1db_dbm"],
        "op1db_dbm": sweep["metrics"]["diagnostic_op1db_dbm"],
        "power_ma": ladder["metrics"]["supply_current_ma"],
    }
    s11_limit_db = -20.0  # Local Stage 2 target, not a Table III field.
    violations = fullchain_violations(
        {**metrics, "source": "cadence_spectre_archives", "simulation_status": "ok",
         "circuit_class": "pdk_rf_ideal_input_ladder_probe", "not_lna_result": True},
        {**asdict(spec), "s11_max_db": s11_limit_db},
    )
    if violations["status"] != "unverified_score" or violations["pass"] is not False:
        raise ValueError("RF ladder diagnostic cannot become a verified LNA score")
    payload = {
        "schema_version": 1, "status": "diagnostic_fullchain_unqualified",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_ideal_input_ladder_probe",
        "model_kind": "authorized_pdk_private", "not_lna_result": True,
        "spec_pass": None, "run_id": run_id,
        "scope": "archived same-candidate ideal-input-ladder DC/SP/noise/HB diagnostic; not a qualified LNA",
        "analysis": ["dc", "sp", "noise", "hb"],
        "diagnostic_spec": asdict(spec), "diagnostic_s11_limit_db": s11_limit_db,
        "frequency_band_ghz": {"low": low, "high": high},
        "points_in_band": len(band_rows),
        "reference_planes": {
            "input": "PORT1 single-ended before ideal input ladder",
            "output": "PORT2 differential",
            "input_z0_ohm": ladder["port_reference_ohm"]["input"],
            "output_z0_ohm": ladder["port_reference_ohm"]["output"],
        },
        "metrics": metrics, "violations": violations,
        "source_run_ids": {"ladder_run_id": ladder_dir.name, "sweep_run_id": sweep_dir.name},
        "source_manifest_sha256": {
            "ladder": _sha256(ladder_dir / "evidence_manifest.json"),
            "sweep": _sha256(sweep_dir / "evidence_manifest.json"),
        },
        "ideal_parameters": ladder["ideal_parameters"],
        "physical_qualification": False, "cdf_callback_validated": False,
        "model_warning_resolved": False, "compression_single_frequency_ghz": 10.0,
    }
    validate_metrics_payload(payload)
    return payload


def audit_pdk_rf_ladder_fullchain(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("RF ladder fullchain report is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    entries = json.loads((report_dir / "evidence_manifest.json").read_text(
        encoding="utf-8"
    )).get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _FILES.items()):
        raise ValueError("RF ladder fullchain evidence lacks required artifacts")
    config_path = report_dir / "source_runs.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("RF ladder fullchain source config is missing or unsafe")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "spec_id", "ladder_run_id", "sweep_run_id"}
        or config["schema_version"] != 1 or config["spec_id"] != "S1"
        or any(not isinstance(config[key], str) or not _ID.fullmatch(config[key])
               for key in ("ladder_run_id", "sweep_run_id"))
    ):
        raise ValueError("RF ladder fullchain source config is invalid")
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    rebuilt = build_pdk_rf_ladder_fullchain(
        _PRIVATE_ROOT / "pdk_rf_input_ladder" / config["ladder_run_id"],
        _PRIVATE_ROOT / "pdk_rf_ladder_hb_sweeps" / config["sweep_run_id"],
        spec, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("RF ladder fullchain differs from its raw Spectre sources")
    return {"status": "verified_diagnostic_only", "run_id": report_dir.name,
            "points_in_band": rebuilt["points_in_band"],
            "not_lna_result": True, "spec_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or audit RF ideal-input-ladder fullchain diagnostic")
    parser.add_argument("--ladder-dir", type=Path)
    parser.add_argument("--sweep-dir", type=Path)
    parser.add_argument("--output-root", type=Path,
                        default=_PRIVATE_ROOT / "pdk_rf_ladder_fullchain")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_pdk_rf_ladder_fullchain(args.audit_dir)
        print(f"status={result['status']} points={result['points_in_band']}")
        return 0
    if args.ladder_dir is None or args.sweep_dir is None:
        parser.error("--ladder-dir and --sweep-dir are required")
    _require_private_path(args.output_root)
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    payload = build_pdk_rf_ladder_fullchain(args.ladder_dir, args.sweep_dir, spec, run_id)
    report_dir = args.output_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "source_runs.json", {
        "schema_version": 1, "spec_id": "S1", **payload["source_run_ids"],
    })
    write_json(report_dir / "metrics.json", payload)
    write_evidence_manifest(report_dir, _FILES)
    result = audit_pdk_rf_ladder_fullchain(report_dir)
    print(f"status={result['status']} points={result['points_in_band']} output={report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
