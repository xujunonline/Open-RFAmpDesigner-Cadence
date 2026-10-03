from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_BIAS_LINE = re.compile(r"^(parameters VDD=1\.2 VBIAS=)[0-9.]+(?= WMOS=300u)", re.MULTILINE)
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COLUMNS = (
    "vbias_v", "run_id", "s11_db", "s21_db", "s22_db", "ripple_db",
    "nf_db", "nfmin_db", "supply_current_ma", "supply_power_mw", "points_in_band",
)


def _build_teaching_bias(run_dirs: list[Path], run_id: str) -> tuple[list[dict], dict]:
    if not isinstance(run_dirs, list) or not 2 <= len(run_dirs) <= 12:
        raise ValueError("teaching bias summary requires 2..12 archived runs")
    rows = []
    source_digests = []
    reference_grid = None
    reference_netlist = None
    seen_ids = set()
    seen_biases = set()
    for run_dir in run_dirs:
        if not isinstance(run_dir, Path) or run_dir.name in seen_ids:
            raise ValueError("teaching bias run IDs must be distinct paths")
        verified = audit_teaching_lna(run_dir)
        payload = read_evidenced_metrics(run_dir)
        bias = payload.get("design_parameters", {}).get("vbias_v", 0.65)
        if type(bias) not in {int, float} or not math.isfinite(bias) or bias in seen_biases:
            raise ValueError("teaching bias values must be finite and distinct")
        netlist = (run_dir / "netlist.scs").read_text(encoding="ascii")
        normalized, count = _BIAS_LINE.subn(r"\g<1><BIAS>", netlist)
        if count != 1 or (reference_netlist is not None and normalized != reference_netlist):
            raise ValueError("teaching run netlists differ beyond VBIAS")
        reference_netlist = normalized
        grid, _ = parse_complex_trace(run_dir / "sp.sp", "s21")
        if reference_grid is not None and grid != reference_grid:
            raise ValueError("teaching SP frequency grids differ")
        reference_grid = grid
        row = {"vbias_v": float(bias), "run_id": run_dir.name}
        row.update(verified["metrics"])
        rows.append({key: row[key] for key in _COLUMNS})
        source_digests.append({
            "run_id": run_dir.name,
            "evidence_manifest_sha256": hashlib.sha256(
                (run_dir / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        })
        seen_ids.add(run_dir.name)
        seen_biases.add(bias)
    rows.sort(key=lambda row: row["vbias_v"])
    source_digests.sort(key=lambda item: item["run_id"])
    summary = {
        "schema_version": 1,
        "status": "diagnostic_summary",
        "simulation_status": "unknown",
        "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model",
        "not_lna_result": True,
        "spec_pass": None,
        "source": "cadence_spectre_archives",
        "scope": "same-template MOS1 bias comparison; not a foundry or paper result",
        "run_id": run_id,
        "frequency_points": len(reference_grid),
        "run_ids": [row["run_id"] for row in rows],
        "source_manifests": source_digests,
        "rows": rows,
    }
    validate_metrics_payload(summary)
    return rows, summary


def _csv_bytes(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def summarize_teaching_bias(run_dirs: list[Path], output_dir: Path) -> dict:
    _require_private_path(output_dir)
    rows, summary = _build_teaching_bias(run_dirs, output_dir.name)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "bias_sweep.csv").write_bytes(_csv_bytes(rows))
    write_json(output_dir / "metrics.json", summary)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json", "csv": "bias_sweep.csv"})
    return summary


def audit_teaching_bias_summary(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("teaching bias summary archive is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    ids = saved.get("run_ids")
    if (
        not isinstance(ids, list) or not 2 <= len(ids) <= 12
        or any(not isinstance(value, str) or _RUN_ID.fullmatch(value) is None for value in ids)
        or len(set(ids)) != len(ids)
        or saved.get("not_lna_result") is not True
        or saved.get("spec_pass") is not None
        or saved.get("model_kind") != "teaching_model"
    ):
        raise ValueError("teaching bias summary source IDs or boundary are invalid")
    sources = [_PRIVATE_ROOT / "teaching_lna" / value for value in ids]
    rows, rebuilt = _build_teaching_bias(sources, report_dir.name)
    csv_path = report_dir / "bias_sweep.csv"
    if (
        saved != rebuilt or not csv_path.is_file() or csv_path.is_symlink()
        or csv_path.read_bytes() != _csv_bytes(rows)
    ):
        raise ValueError("teaching bias summary differs from reaudited Spectre archives")
    return {"status": "verified", "runs": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and summarize same-grid MOS1 teaching bias runs")
    parser.add_argument("run_dirs", type=Path, nargs="*")
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_bias_summaries")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_bias_summary(args.audit_dir)
        print(f"status={result['status']} runs={result['runs']}")
        return 0
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        result = summarize_teaching_bias(args.run_dirs, output_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"cannot summarize teaching bias archives: {type(exc).__name__}: {exc}")
    print(f"status={result['status']} runs={len(result['rows'])} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
