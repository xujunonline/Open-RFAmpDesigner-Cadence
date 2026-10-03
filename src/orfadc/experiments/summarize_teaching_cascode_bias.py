from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_diagnostic_pair import _sha256
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_COLUMNS = (
    "run_id", "vcas_v", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db",
    "ripple_db", "supply_current_ma", "minimum_k", "m1_vds_margin_v", "m2_vds_margin_v",
)


def _csv_text(rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def build_cascode_bias_summary(run_dirs: list[Path], run_id: str) -> dict:
    if len(run_dirs) < 2 or len({path.resolve() for path in run_dirs}) != len(run_dirs):
        raise ValueError("cascode bias summary requires distinct source runs")
    if any(not path.is_dir() or path.is_symlink() for path in run_dirs):
        raise ValueError("cascode bias source directory is missing or symlinked")
    if len({path.parent.resolve() for path in run_dirs}) != 1:
        raise ValueError("cascode bias sources must share a run root")
    rows = []
    base_design = None
    base_grid = None
    for path in run_dirs:
        audited = audit_teaching_lna(path)
        saved = read_evidenced_metrics(path)
        design = saved.get("design_parameters")
        if (saved.get("circuit_class") != "teaching_mos1_cascode"
                or not isinstance(design, dict) or design.get("topology") != "cascode"
                or audited["points_verified"] != 161
                or "device_op" not in audited or "cascode_op" not in audited):
            raise ValueError("cascode bias source is not a complete 161-point teaching run")
        fixed = {key: value for key, value in design.items() if key != "vcas_v"}
        if base_design is None:
            base_design = fixed
        elif fixed != base_design:
            raise ValueError("cascode bias sources differ beyond VCAS")
        frequency, _ = parse_complex_trace(path / "sp.sp", "s11")
        noise_frequency, _ = parse_scalar_trace(path / "sp.noise.sp", "NF")
        if frequency != noise_frequency or (base_grid is not None and frequency != base_grid):
            raise ValueError("cascode bias source frequency grids differ")
        base_grid = frequency
        metrics = audited["metrics"]
        m1 = audited["device_op"]
        m2 = audited["cascode_op"]
        rows.append({
            "run_id": path.name, "vcas_v": design["vcas_v"],
            **{key: metrics[key] for key in _COLUMNS if key in metrics},
            "minimum_k": audited["stability"]["minimum_k"],
            "m1_vds_margin_v": m1["vds"] - m1["vdsat"],
            "m2_vds_margin_v": m2["vds"] - m2["vdsat"],
            "manifest_sha256": _sha256(path / "evidence_manifest.json"),
        })
    rows.sort(key=lambda row: row["vcas_v"])
    if len({row["vcas_v"] for row in rows}) != len(rows):
        raise ValueError("cascode bias sweep contains a duplicate VCAS value")
    report = {
        "schema_version": 1, "status": "verified_teaching_cascode_bias_sweep",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_cascode", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "public MOS1 single-stage bias sensitivity; not an LNA optimization or paper result",
        "analysis": ["dc", "sp", "noise"], "points_per_run": 161,
        "fixed_design_parameters": base_design, "rows": rows,
    }
    validate_metrics_payload(report)
    return report


def audit_cascode_bias_report(report_dir: Path, source_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("cascode bias report directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    rows = saved.get("rows")
    if not isinstance(rows, list) or len(rows) < 2 or any(
        not isinstance(row, dict) or not isinstance(row.get("run_id"), str)
        or re.fullmatch(r"[A-Za-z0-9_-]+", row["run_id"]) is None for row in rows
    ):
        raise ValueError("invalid cascode bias source identities")
    rebuilt = build_cascode_bias_summary([source_root / row["run_id"] for row in rows], report_dir.name)
    if saved != rebuilt:
        raise ValueError("cascode bias report differs from source archives")
    expected_csv = _csv_text([{key: row[key] for key in _COLUMNS} for row in rebuilt["rows"]])
    if (report_dir / "bias_sweep.csv").read_text(encoding="utf-8") != expected_csv:
        raise ValueError("cascode bias CSV differs from source archives")
    return {"status": "verified", "run_id": report_dir.name, "source_runs": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize audited public MOS1 cascode VCAS runs")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_cascode_bias_summaries")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_cascode_bias_summary(args.run_dirs, run_id)
        output_dir = args.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "metrics.json", report)
        (output_dir / "bias_sweep.csv").write_text(
            _csv_text([{key: row[key] for key in _COLUMNS} for row in report["rows"]]), encoding="utf-8",
        )
        write_evidence_manifest(output_dir, {"metrics": "metrics.json", "bias_sweep": "bias_sweep.csv"})
        audit_cascode_bias_report(output_dir, args.run_dirs[0].parent)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"cascode bias summary failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} runs={len(report['rows'])} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
