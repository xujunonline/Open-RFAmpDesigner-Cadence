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
from orfadc.config_loader import write_json
from orfadc.experiments.audit_diagnostic_pair import _sha256
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_COLUMNS = (
    "run_id", "output_secondary_nh", "output_tune_ff", "s11_db", "s21_db", "s22_db",
    "nf_db", "ripple_db", "supply_current_ma", "minimum_k",
)


def _csv_text(rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows([{key: row[key] for key in _COLUMNS} for row in rows])
    return stream.getvalue()


def build_three_stage_summary(run_dirs: list[Path], run_id: str) -> dict:
    if len(run_dirs) < 2 or len({path.resolve() for path in run_dirs}) != len(run_dirs):
        raise ValueError("three-stage summary requires distinct source runs")
    if any(not path.is_dir() or path.is_symlink() for path in run_dirs):
        raise ValueError("three-stage source directory is missing or symlinked")
    if len({path.parent.resolve() for path in run_dirs}) != 1:
        raise ValueError("three-stage sources must share a root")
    rows = []
    for path in run_dirs:
        audit_teaching_three_stage(path)
        payload = read_evidenced_metrics(path)
        if (payload.get("source_run_kind") != "teaching_mos1_three_stage_direct_spectre"
                or payload.get("port_reference_ohm") != {"input": 50.0, "output": 1787.0}
                or payload.get("points") != 161):
            raise ValueError("three-stage source has incompatible analysis or port references")
        design = payload.get("design_parameters") or {}
        metrics = payload["metrics"]
        rows.append({
            "run_id": path.name,
            "output_secondary_nh": design.get("output_secondary_nh", 1.0),
            "output_tune_ff": design.get("output_tune_ff", 0.0),
            **{key: metrics[key] for key in ("s11_db", "s21_db", "s22_db", "nf_db", "ripple_db", "supply_current_ma")},
            "minimum_k": payload["stability"]["minimum_k"],
            "manifest_sha256": _sha256(path / "evidence_manifest.json"),
        })
    rows.sort(key=lambda row: (row["output_secondary_nh"], row["output_tune_ff"]))
    if len({(row["output_secondary_nh"], row["output_tune_ff"]) for row in rows}) != len(rows):
        raise ValueError("three-stage summary contains duplicate passive candidates")
    report = {
        "schema_version": 1, "status": "verified_teaching_three_stage_summary",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_id,
        "scope": "public MOS1 direct Spectre three-stage passive probe; not a qualified LNA or paper result",
        "analysis": ["dc", "sp", "noise"], "points_per_run": 161,
        "port_reference_ohm": {"input": 50.0, "output": 1787.0}, "rows": rows,
    }
    validate_metrics_payload(report)
    return report


def audit_three_stage_summary(report_dir: Path, source_root: Path) -> dict:
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("three-stage summary directory is missing or symlinked")
    saved = read_evidenced_metrics(report_dir)
    rows = saved.get("rows")
    if not isinstance(rows, list) or len(rows) < 2 or any(
        not isinstance(row, dict) or not isinstance(row.get("run_id"), str)
        or re.fullmatch(r"[A-Za-z0-9_-]+", row["run_id"]) is None for row in rows
    ):
        raise ValueError("three-stage summary has invalid source identities")
    rebuilt = build_three_stage_summary([source_root / row["run_id"] for row in rows], report_dir.name)
    if saved != rebuilt:
        raise ValueError("three-stage summary differs from source archives")
    if (report_dir / "passive_probe.csv").read_text(encoding="utf-8") != _csv_text(rebuilt["rows"]):
        raise ValueError("three-stage summary CSV differs from source archives")
    return {"status": "verified", "run_id": report_dir.name, "source_runs": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize audited public MOS1 three-stage passive probes")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_summaries")
    args = parser.parse_args()
    try:
        _require_private_path(args.output_root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        report = build_three_stage_summary(args.run_dirs, run_id)
        output_dir = args.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "metrics.json", report)
        (output_dir / "passive_probe.csv").write_text(_csv_text(report["rows"]), encoding="utf-8")
        write_evidence_manifest(output_dir, {"metrics": "metrics.json", "passive_probe": "passive_probe.csv"})
        audit_three_stage_summary(output_dir, args.run_dirs[0].parent)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"three-stage summary failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} runs={len(report['rows'])} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
