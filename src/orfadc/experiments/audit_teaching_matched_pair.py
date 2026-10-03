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
from orfadc.config_loader import write_json
from orfadc.experiments.audit_diagnostic_pair import _netlist_lines, _sha256, expected_hb_netlist
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_teaching_matched_hb import audit_matched_hb_summary
from orfadc.metric_contract import validate_metrics_payload


_SHARED_DESIGN_KEYS = (
    "vbias_v", "ldd_nh", "cblock_ff", "rdamp_ohm",
    "sp_intervals", "sp_start_ghz", "sp_stop_ghz",
)


def _safe_run_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("invalid paired source run identity")
    return value


def build_teaching_matched_pair(
    small_signal_dir: Path, summary_dir: Path, hb_root: Path, run_id: str,
) -> dict:
    """Bind archived DC/SP/noise and every HB stimulus to one public MOS1 netlist."""
    if any(not path.is_dir() or path.is_symlink() for path in (small_signal_dir, summary_dir, hb_root)):
        raise ValueError("paired source directory is missing or symlinked")
    small_audit = audit_teaching_lna(small_signal_dir)
    summary_audit = audit_matched_hb_summary(summary_dir, hb_root)
    small = read_evidenced_metrics(small_signal_dir)
    summary = read_evidenced_metrics(summary_dir)
    small_design = small.get("design_parameters")
    hb_design = summary.get("design_parameters")
    if not isinstance(small_design, dict) or not isinstance(hb_design, dict) or any(
        small_design.get(key) != hb_design.get(key) for key in _SHARED_DESIGN_KEYS
    ):
        raise ValueError("small-signal and HB design parameters differ")
    if hb_design.get("frequency_ghz") != 10.0 or hb_design.get("harmonics") != 7:
        raise ValueError("paired HB frequency or harmonics differ from the experiment")
    small_netlist = (small_signal_dir / "netlist.scs").read_text(encoding="ascii")
    small_s21 = extract_sp_s21_at_frequency(small_signal_dir / "sp.sp", 10e9)
    source_ids = [_safe_run_id(row["run_id"]) for row in summary["rows"]]
    source_ids.append(_safe_run_id(summary["rejected_run_id"]))
    point_hashes = []
    point_s21_deltas = []
    for index, point_id in enumerate(source_ids):
        point_dir = hb_root / point_id
        if not point_dir.is_dir() or point_dir.is_symlink():
            raise ValueError("paired HB point directory is missing or symlinked")
        point = read_evidenced_metrics(point_dir)
        params = point.get("parameters")
        if not isinstance(params, dict) or any(params.get(key) != value for key, value in hb_design.items()):
            raise ValueError("paired HB point parameters differ from the small-signal circuit")
        if index < len(summary["rows"]):
            power = summary["rows"][index]["pin_dbm"]
        else:
            power = summary["rejected_input_dbm"]
            manifest = json.loads((point_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
            if manifest.get("artifacts", {}).get("sp_raw", {}).get("path") != "sp.sp":
                raise ValueError("rejected HB small-signal raw file is not in its evidence manifest")
            log = (point_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
            warning = re.search(r"spectre completes with 0 errors,\s*(\d+) warnings", log)
            logged_codes = sorted(set(re.findall(r"\b(?:CMI|SPECTRE)-\d+\b", log)))
            if (
                not warning or int(warning[1]) < 1 or "CMI-2377" not in logged_codes
                or point.get("quality_flags") != ["spectre_warnings", *logged_codes]
            ):
                raise ValueError("rejected HB point lacks its recorded model-validity warning")
        if params.get("input_dbm") != power:
            raise ValueError("paired HB power differs from the summary")
        expected = expected_hb_netlist(
            small_netlist, input_dbm=power, frequency_ghz=10.0, harmonics=7,
        )
        actual = _netlist_lines((point_dir / "netlist.scs").read_text(encoding="ascii"))
        if actual != expected:
            raise ValueError("HB point changes the small-signal circuit beyond stimulus and HB")
        point_s21 = extract_sp_s21_at_frequency(point_dir / "sp.sp", 10e9)
        if not math.isclose(point_s21, small_s21, rel_tol=0, abs_tol=0.001):
            raise ValueError("paired HB small-signal S21 differs from the source")
        point_s21_deltas.append(point_s21 - small_s21)
        point_hashes.append(_sha256(point_dir / "netlist.scs"))
    report = {
        "schema_version": 1, "status": "verified_teaching_matched_pair",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "same-circuit public MOS1 DC/SP/noise/HB diagnostic; no valid P1dB or qualified LNA",
        "analysis": ["dc", "sp", "noise", "hb"],
        "small_signal_run_id": small_signal_dir.name,
        "hb_summary_run_id": summary_dir.name,
        "small_signal_manifest_sha256": _sha256(small_signal_dir / "evidence_manifest.json"),
        "hb_summary_manifest_sha256": _sha256(summary_dir / "evidence_manifest.json"),
        "hb_point_run_ids": source_ids,
        "hb_netlist_sha256_list": point_hashes,
        "same_netlist_except_stimulus_and_hb": True,
        "small_signal_s21_10ghz_db": small_s21,
        "maximum_point_s21_delta_db": max(abs(value) for value in point_s21_deltas),
        "points_small_signal": small_audit["points_verified"],
        "points_hb_valid": summary_audit["points_verified"],
        "points_hb_warning_excluded": 1,
        "compression_status": summary["compression"]["status"],
        "metrics": {**small_audit["metrics"], "ip1db_dbm": None, "op1db_dbm": None},
    }
    if report["compression_status"] != "unbracketed":
        raise ValueError("paired teaching HB compression is not unbracketed")
    validate_metrics_payload(report)
    return report


def audit_teaching_matched_pair_report(
    report_dir: Path, small_signal_root: Path, summary_root: Path, hb_root: Path,
) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("paired report directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    small_id = _safe_run_id(saved.get("small_signal_run_id"))
    summary_id = _safe_run_id(saved.get("hb_summary_run_id"))
    rebuilt = build_teaching_matched_pair(
        small_signal_root / small_id, summary_root / summary_id, hb_root, report_dir.name,
    )
    if saved != rebuilt:
        raise ValueError("paired report differs from source archives")
    return {"status": "verified", "run_id": report_dir.name,
            "points_hb_valid": rebuilt["points_hb_valid"], "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-audit a public MOS1 SP/noise run and matched HB points")
    parser.add_argument("small_signal_dir", type=Path)
    parser.add_argument("summary_dir", type=Path)
    parser.add_argument("--hb-root", type=Path, default=_PRIVATE_ROOT / "teaching_hb")
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_matched_pairs")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_teaching_matched_pair(args.small_signal_dir, args.summary_dir, args.hb_root, run_id)
        output_dir = args.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "metrics.json", report)
        write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
        audit_teaching_matched_pair_report(
            output_dir, args.small_signal_dir.parent, args.summary_dir.parent, args.hb_root,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"matched teaching pair audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} valid_hb={report['points_hb_valid']} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
