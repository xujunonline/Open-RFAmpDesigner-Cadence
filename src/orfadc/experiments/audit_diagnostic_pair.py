from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.hb_metrics import extract_sp_s21_at_frequency
from orfadc.config_loader import write_json
from orfadc.experiments.audit_hb_sweep import audit_hb_sweep
from orfadc.experiments.extract_active_oa import extract_active_oa
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _SUPPLY_LINE, _require_private_path
from orfadc.experiments.run_hb_diagnostic import _INPUT_PORT, _OUTPUT_PORT
from orfadc.metric_contract import validate_metrics_payload


def _netlist_lines(source: str) -> str:
    return "\n".join(line.rstrip() for line in source.splitlines() if line.strip())


def expected_hb_netlist(active_source: str, *, input_dbm: float,
                        frequency_ghz: float, harmonics: int) -> str:
    """Reconstruct the only allowed HB derivation of an active diagnostic netlist."""
    source = _netlist_lines(active_source)
    if "\nhb hb " in source or source.startswith("hb hb "):
        raise ValueError("active source already contains HB")
    source, input_count = _INPUT_PORT.subn(
        lambda match: f"{match[1]} type=sine dbm={input_dbm:.17g} freq={frequency_ghz * 1e9:.17g}",
        source,
    )
    source, output_count = _OUTPUT_PORT.subn(lambda match: f"{match[1]} type=dc", source)
    if input_count != 1 or output_count != 1:
        raise ValueError("active source ports are not the expected 50-ohm pair")
    return source + f"\nhb hb fundfreqs=[{frequency_ghz * 1e9:.17g}] maxharms=[{harmonics}] annotate=status"


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("symlinked diagnostic metadata is not accepted")

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")

    result = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError("diagnostic metadata must be an object")
    return result


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("diagnostic source file is missing or symlinked")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metrics_agree(saved: dict, extracted: dict) -> None:
    if set(saved) != set(extracted):
        raise ValueError("diagnostic active metric names changed")
    for key, expected in extracted.items():
        actual = saved[key]
        if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
            actual, expected, rel_tol=1e-9, abs_tol=1e-9,
        ):
            raise ValueError(f"diagnostic active metric {key} differs from raw data")


def audit_diagnostic_pair(candidate_dir: Path, sweep_dir: Path) -> dict:
    """Read-only proof that archived DC/SP/noise and HB share one diagnostic circuit."""
    if any(not path.is_dir() or path.is_symlink() for path in (candidate_dir, sweep_dir)):
        raise ValueError("diagnostic source directories must exist and not be symlinks")
    active = read_evidenced_metrics(candidate_dir)
    sweep = audit_hb_sweep(sweep_dir)
    config = _read_json(sweep_dir / "sweep_config.json")
    candidate = active.get("candidate")
    if (
        active.get("status") != "ok_with_warnings"
        or active.get("simulation_status") != "ok"
        or active.get("source") != "cadence_spectre"
        or active.get("source_run_kind") != "oa_netlist_derivative_bias_load_direct_spectre"
        or active.get("circuit_class") != "active_common_source_smoke"
        or active.get("not_lna_result") is not True
        or active.get("spec_pass") is not None
        or active.get("run_id") != candidate_dir.name
        or not isinstance(candidate, dict)
        or not isinstance(candidate.get("active_params"), dict)
        or candidate["active_params"].get("rd_ohm") != config.get("rd_ohm")
        or candidate["active_params"].get("vbias_v") != config.get("vbias_v")
        or active.get("reference_planes", {}).get("z0_ohm") != 50.0
    ):
        raise ValueError("active candidate and HB sweep contexts are not compatible")
    manifest = _read_json(candidate_dir / "evidence_manifest.json")
    paths = {key: entry.get("path") for key, entry in manifest.get("artifacts", {}).items()
             if isinstance(entry, dict)}
    if any(paths.get(key) != value for key, value in {
        "netlist": "netlist.scs", "ade_companion": "ade_e.scs",
        "dc_raw": "psf/dcOp.dc", "sp_raw": "psf/sp.sp",
        "noise_raw": "psf/sp.noise.sp", "spectre_log": "spectre.log",
    }.items()):
        raise ValueError("active candidate raw evidence is incomplete")
    active_source = (candidate_dir / "netlist.scs").read_text(encoding="utf-8")
    supply = _SUPPLY_LINE.search(active_source)
    if supply is None:
        raise ValueError("active candidate supply voltage is missing")
    voltage = float(supply.group(1))
    band = active.get("frequency_band_ghz")
    if not isinstance(band, dict) or not 0 < band.get("low", 0) < band.get("high", 0):
        raise ValueError("active candidate has no valid RF band")
    rows, extracted = extract_active_oa(
        candidate_dir / "psf", run_id=candidate_dir.name, supply_voltage_v=voltage,
        low_ghz=band["low"], high_ghz=band["high"],
        source_run_kind="oa_netlist_derivative_bias_load_direct_spectre",
    )
    _metrics_agree(active.get("metrics", {}), extracted["metrics"])
    if active.get("points") != len(rows) or active.get("stability") != extracted["stability"]:
        raise ValueError("active candidate sampled data differ from raw evidence")
    active_s21_ghz = extract_sp_s21_at_frequency(
        candidate_dir / "psf" / "sp.sp", config["frequency_ghz"] * 1e9,
    )
    expected_netlists = []
    source_manifests = []
    for index, power in enumerate(config["input_powers_dbm"]):
        point_dir = sweep_dir / f"point_{index:02d}"
        point = read_evidenced_metrics(point_dir)
        expected = expected_hb_netlist(
            active_source, input_dbm=power, frequency_ghz=config["frequency_ghz"],
            harmonics=config["harmonics"],
        )
        actual = _netlist_lines((point_dir / "netlist.scs").read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError(f"HB point {index} changes the active circuit beyond allowed stimulus/HB")
        if (point_dir / "ade_e.scs").read_bytes() != (candidate_dir / "ade_e.scs").read_bytes():
            raise ValueError(f"HB point {index} uses a different model companion")
        point_s21 = extract_sp_s21_at_frequency(point_dir / "sp.sp", config["frequency_ghz"] * 1e9)
        if not math.isclose(point_s21, active_s21_ghz, rel_tol=0, abs_tol=0.001):
            raise ValueError(f"HB point {index} small-signal S21 differs from the candidate")
        if point.get("parameters") != {
            "rd_ohm": config["rd_ohm"], "vbias_v": config["vbias_v"],
            "input_dbm": power, "frequency_ghz": config["frequency_ghz"],
            "harmonics": config["harmonics"],
        }:
            raise ValueError(f"HB point {index} parameters disagree with the sweep")
        expected_netlists.append(_sha256(point_dir / "netlist.scs"))
        source_manifests.append(_sha256(point_dir / "evidence_manifest.json"))
    compression = sweep["compression"]
    if compression.get("status") != "ok" or compression.get("ip1db_dbm") is None:
        raise ValueError("diagnostic pair requires a bracketed compression point")
    report = {
        "schema_version": 1, "status": "verified_diagnostic_pair",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "active_common_source_smoke", "not_lna_result": True,
        "spec_pass": None, "run_id": f"{candidate_dir.name}__{sweep_dir.name}",
        "scope": "archived same-circuit DC/SP/noise/HB diagnostic; not a qualified LNA fullchain",
        "analysis": ["dc", "sp", "noise", "hb"],
        "candidate_id": candidate["candidate_id"], "origin_spec_id": candidate["spec_id"],
        "candidate_run_id": candidate_dir.name, "sweep_run_id": sweep_dir.name,
        "active_manifest_sha256": _sha256(candidate_dir / "evidence_manifest.json"),
        "hb_manifest_sha256_list": source_manifests,
        "hb_netlist_sha256_list": expected_netlists,
        "hb_sweep_config_sha256": _sha256(sweep_dir / "sweep_config.json"),
        "hb_sweep_summary_sha256": _sha256(sweep_dir / "summary.json"),
        "same_model_companion": True, "same_active_netlist_except_stimulus_and_hb": True,
        "template_hashes_match": active.get("source_template_sha256") == config.get("template_sha256"),
        "small_signal_s21_at_hb_frequency_db": active_s21_ghz,
        "points_small_signal": len(rows), "points_hb": len(source_manifests),
        "metrics": {**active["metrics"],
                    "ip1db_dbm": compression["ip1db_dbm"],
                    "op1db_dbm": compression["op1db_dbm"]},
    }
    validate_metrics_payload(report)
    return report


def audit_diagnostic_pair_report(report_dir: Path, candidate_dir: Path, sweep_dir: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("diagnostic pair report directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    rebuilt = audit_diagnostic_pair(candidate_dir, sweep_dir)
    rebuilt["run_id"] = report_dir.name
    if saved != rebuilt:
        raise ValueError("diagnostic pair report differs from the source archives")
    return {"status": "verified", "run_id": report_dir.name,
            "candidate_run_id": candidate_dir.name, "sweep_run_id": sweep_dir.name,
            "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-audit an OA diagnostic candidate and its HB sweep")
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("sweep_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "diagnostic_pairs")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        report = audit_diagnostic_pair(args.candidate_dir, args.sweep_dir)
        output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
        output_dir.mkdir(parents=True, exist_ok=False)
        report["run_id"] = output_dir.name
        write_json(output_dir / "metrics.json", report)
        write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
        audit_diagnostic_pair_report(output_dir, args.candidate_dir, args.sweep_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"diagnostic pair audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points_hb={report['points_hb']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
