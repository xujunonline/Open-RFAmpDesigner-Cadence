from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.experiments.audit_teaching_lna import audit_teaching_lna
from orfadc.experiments.export_teaching_device_lookup import _BIAS, _COLUMNS, _MODEL, _WIDTH


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_NUMERIC = (
    "temperature_c", "w_um", "l_um", "vgs_v", "vds_v", "vdsat_v",
    "current_ma", "gm_s", "gds_s", "cgs_f", "cgd_f", "gm_over_id_v_inv",
)


def _equal(actual: object, expected: float, label: str) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-10, abs_tol=1e-24
    ):
        raise ValueError(f"lookup {label} disagrees with audited source")


def audit_teaching_device_lookup(output_dir: Path, source_root: Path) -> dict:
    """Recompute a teaching lookup from independently audited source archives."""
    if any(not path.is_dir() or path.is_symlink() for path in (output_dir, source_root)):
        raise ValueError("lookup and source roots must be ordinary directories")
    saved = read_evidenced_metrics(output_dir)
    rows = saved.get("rows")
    bindings = saved.get("source_manifests")
    if (
        saved.get("run_id") != output_dir.name
        or saved.get("source") != "cadence_spectre_archives"
        or saved.get("model_kind") != "teaching_model"
        or saved.get("not_lna_result") is not True
        or saved.get("spec_pass") is not None
        or not isinstance(rows, list) or not 2 <= len(rows) <= 12
        or not isinstance(bindings, list) or len(bindings) != len(rows)
    ):
        raise ValueError("not an archived teaching device lookup")
    if rows != sorted(rows, key=lambda row: (row["w_um"], row["vgs_v"])):
        raise ValueError("lookup rows are not sorted by width and bias")
    widths = sorted({row["w_um"] for row in rows})
    legacy_fixed_width = "widths_um" not in saved and widths == [300.0]
    if (not legacy_fixed_width and saved.get("widths_um") != widths) or saved.get("status") != (
        "multi_width_characterization" if len(widths) > 1 else "single_device_characterization"
    ):
        raise ValueError("lookup width summary disagrees with rows")
    bindings_by_id = {}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"run_id", "evidence_manifest_sha256"}:
            raise ValueError("lookup source binding is malformed")
        run_id = binding["run_id"]
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or run_id in bindings_by_id:
            raise ValueError("lookup source run ID is unsafe or duplicated")
        bindings_by_id[run_id] = binding["evidence_manifest_sha256"]
    if set(bindings_by_id) != {row.get("source_run_id") for row in rows}:
        raise ValueError("lookup rows and source bindings disagree")
    template = None
    legacy_template = None
    frequency_grid = None
    seen_points = set()
    for row in rows:
        run_id = row["source_run_id"]
        run_dir = source_root / run_id
        if run_dir.is_symlink() or not run_dir.is_dir() or not run_dir.resolve().is_relative_to(source_root.resolve()):
            raise ValueError("lookup source archive is missing or unsafe")
        manifest_hash = hashlib.sha256((run_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if manifest_hash != bindings_by_id[run_id]:
            raise ValueError("lookup source evidence manifest changed")
        audited = audit_teaching_lna(run_dir)
        source_metrics = read_evidenced_metrics(run_dir)
        design = source_metrics.get("design_parameters", {})
        op = audited.get("device_op")
        if not isinstance(op, dict) or op.get("ids", 0) <= 0 or op.get("gm", 0) <= 0:
            raise ValueError("lookup source lacks valid operating point")
        text = (run_dir / "netlist.scs").read_text(encoding="ascii")
        bias_text, bias_count = _BIAS.subn(r"\g<1><BIAS>", text)
        width_match = _WIDTH.search(text)
        model_match = _MODEL.search(text)
        if bias_count != 1 or width_match is None or model_match is None:
            raise ValueError("lookup source has unexpected netlist structure")
        neutralized, width_count = _WIDTH.subn("<WIDTH>", bias_text)
        if width_count != 1 or (template is not None and neutralized != template):
            raise ValueError("lookup source netlists differ beyond bias/width")
        template = neutralized
        legacy_template = bias_text
        width = float(width_match[0])
        bias = design.get("vbias_v")
        if type(bias) not in {int, float} or (width, bias) in seen_points:
            raise ValueError("lookup source bias is missing or duplicated")
        seen_points.add((width, bias))
        revision = "sha256_" + hashlib.sha256(model_match[0].encode("ascii")).hexdigest()[:16]
        if saved.get("model_revision") != revision or row.get("model_revision") != revision:
            raise ValueError("lookup model revision disagrees with source")
        frequencies, _ = parse_complex_trace(run_dir / "sp.sp", "s21")
        if frequency_grid is not None and frequencies != frequency_grid:
            raise ValueError("lookup source frequency grids differ")
        frequency_grid = frequencies
        expected = {
            "temperature_c": 27.0, "w_um": width, "l_um": 0.1,
            "vgs_v": op["vgs"], "vds_v": op["vds"], "vdsat_v": op["vdsat"],
            "current_ma": op["ids"] * 1e3, "gm_s": op["gm"], "gds_s": op["gds"],
            "cgs_f": op["cgs"], "cgd_f": op["cgd"],
            "gm_over_id_v_inv": op["gm"] / op["ids"],
        }
        for key, value in expected.items():
            _equal(row.get(key), value, f"{run_id} {key}")
        if (
            row.get("model_kind") != "teaching_model"
            or row.get("technology_id") != "spectre_mos1_public_teaching"
            or row.get("corner") != "nominal"
        ):
            raise ValueError("lookup source provenance fields disagree")
    expected_template = legacy_template if legacy_fixed_width else template
    if (
        saved.get("template_sha256") != hashlib.sha256(expected_template.encode("ascii")).hexdigest()
        or saved.get("frequency_points") != len(frequency_grid)
    ):
        raise ValueError("lookup template or frequency summary disagrees")
    csv_path = output_dir / "device_lookup.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked lookup CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("lookup CSV columns disagree")
        csv_rows = list(reader)
    if len(csv_rows) != len(rows):
        raise ValueError("lookup CSV row count disagrees")
    for index, (csv_row, row) in enumerate(zip(csv_rows, rows, strict=True)):
        for key in _COLUMNS:
            if key in _NUMERIC:
                try:
                    value = float(csv_row[key])
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"lookup CSV numeric {key} is invalid") from exc
                _equal(value, row[key], f"CSV row {index} {key}")
            elif csv_row[key] != row[key]:
                raise ValueError(f"lookup CSV row {index} {key} disagrees")
    return {"status": "verified", "run_id": output_dir.name, "rows_verified": len(rows),
            "source_runs_verified": len(bindings), "widths_um": widths, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a MOS1 teaching device lookup")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    result = audit_teaching_device_lookup(args.output_dir, args.source_root)
    print(f"status={result['status']} rows={result['rows_verified']} widths={result['widths_um']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
