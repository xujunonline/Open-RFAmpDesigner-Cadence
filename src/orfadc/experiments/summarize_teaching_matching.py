from __future__ import annotations

import argparse
import csv
import hashlib
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


_LDD = re.compile(r"(?<= LDD=)[0-9.]+n(?=\r?$)", re.MULTILINE)
_CBLOCK = re.compile(r"(?<=^CBLOCK \(drain out\) capacitor c=)[0-9.]+[fp](?=\r?$)", re.MULTILINE)
_COLUMNS = (
    "run_id", "ldd_nh", "cblock_ff", "s11_8_db", "s11_10_db", "s11_12_db",
    "s21_8_db", "s21_10_db", "s21_12_db", "s22_8_db", "s22_10_db",
    "s22_12_db", "s11_worst_db", "s21_worst_db", "s22_worst_db",
    "gain_ripple_db", "nf_worst_db", "supply_current_ma", "minimum_k_sampled",
    "maximum_delta_abs_sampled",
)


def _db_at(frequencies: list[float], values: list[complex], ghz: int) -> float:
    matches = [index for index, frequency in enumerate(frequencies)
               if math.isclose(frequency, ghz * 1e9, rel_tol=0, abs_tol=1e-3)]
    if len(matches) != 1 or abs(values[matches[0]]) == 0:
        raise ValueError(f"teaching matching source lacks the exact {ghz} GHz point")
    return 20 * math.log10(abs(values[matches[0]]))


def summarize_teaching_matching(run_dirs: list[Path], output_dir: Path) -> dict:
    _require_private_path(output_dir)
    if not isinstance(run_dirs, list) or not 2 <= len(run_dirs) <= 12:
        raise ValueError("teaching matching summary requires 2..12 archived runs")
    reference_source = None
    reference_grid = None
    reference_bias = None
    seen_ids = set()
    seen_pairs = set()
    rows = []
    manifests = []
    for run_dir in run_dirs:
        if not isinstance(run_dir, Path) or run_dir.name in seen_ids:
            raise ValueError("teaching matching run IDs must be distinct")
        audit = audit_teaching_lna(run_dir)
        result = read_evidenced_metrics(run_dir)
        design = result.get("design_parameters")
        if not isinstance(design, dict):
            raise ValueError("teaching matching design parameters are missing")
        bias = design.get("vbias_v")
        ldd_nh = design.get("ldd_nh", 2.0)
        cblock_ff = design.get("cblock_ff", 5000.0)
        if any(type(x) not in {int, float} or not math.isfinite(x) for x in (bias, ldd_nh, cblock_ff)):
            raise ValueError("teaching matching parameters must be finite")
        pair = (ldd_nh, cblock_ff)
        if pair in seen_pairs or (reference_bias is not None and bias != reference_bias):
            raise ValueError("teaching matching requires one bias and distinct L/C pairs")
        reference_bias = bias
        source = (run_dir / "netlist.scs").read_text(encoding="ascii")
        source, l_count = _LDD.subn("<LDD>", source)
        source, c_count = _CBLOCK.subn("<CBLOCK>", source)
        if l_count != 1 or c_count != 1 or (reference_source is not None and source != reference_source):
            raise ValueError("teaching netlists differ beyond output L/C")
        reference_source = source
        traces = {name: parse_complex_trace(run_dir / "sp.sp", name)
                  for name in ("s11", "s21", "s22")}
        grid = traces["s21"][0]
        if reference_grid is not None and grid != reference_grid:
            raise ValueError("teaching matching frequency grids differ")
        if any(frequencies != grid for frequencies, _ in traces.values()):
            raise ValueError("teaching matching S-parameter grids differ within a run")
        reference_grid = grid
        measured = audit["metrics"]
        stability = audit["stability"]
        row = {"run_id": run_dir.name, "ldd_nh": float(ldd_nh), "cblock_ff": float(cblock_ff)}
        for name, (frequencies, values) in traces.items():
            for ghz in (8, 10, 12):
                row[f"{name}_{ghz}_db"] = _db_at(frequencies, values, ghz)
        row.update({
            "s11_worst_db": measured["s11_db"], "s21_worst_db": measured["s21_db"],
            "s22_worst_db": measured["s22_db"], "gain_ripple_db": measured["ripple_db"],
            "nf_worst_db": measured["nf_db"], "supply_current_ma": measured["supply_current_ma"],
            "minimum_k_sampled": stability["minimum_k"],
            "maximum_delta_abs_sampled": stability["maximum_delta_abs"],
        })
        rows.append({key: row[key] for key in _COLUMNS})
        manifests.append({
            "run_id": run_dir.name,
            "evidence_manifest_sha256": hashlib.sha256(
                (run_dir / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        })
        seen_ids.add(run_dir.name)
        seen_pairs.add(pair)
    rows.sort(key=lambda row: row["ldd_nh"])
    manifests.sort(key=lambda item: item["run_id"])
    summary = {
        "schema_version": 1, "status": "diagnostic_matching_summary",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": output_dir.name,
        "scope": "ideal single-frequency output match diagnostic; not a broadband or PDK LNA",
        "vbias_v": reference_bias, "frequency_points": len(reference_grid),
        "rows": rows, "source_manifests": manifests,
    }
    validate_metrics_payload(summary)
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "matching_comparison.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(output_dir / "metrics.json", summary)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json", "comparison": "matching_comparison.csv"})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and compare ideal MOS1 teaching output matching runs")
    parser.add_argument("run_dirs", type=Path, nargs="+")
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_match_summaries")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        result = summarize_teaching_matching(args.run_dirs, output_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"cannot summarize teaching matching archives: {type(exc).__name__}: {exc}")
    print(f"status={result['status']} runs={len(result['rows'])} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
