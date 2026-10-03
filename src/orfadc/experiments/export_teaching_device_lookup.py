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


_BIAS = re.compile(
    r"^(parameters VDD=1\.2 VBIAS=)[0-9.]+(?= WMOS=[0-9.]+u LMOS=100n LGS=1n LSS=240p LDD=2n$)",
    re.MULTILINE,
)
_WIDTH = re.compile(r"(?<= WMOS=)[0-9.]+(?=u LMOS=100n)")
_MODEL = re.compile(r"^model n_teach mos1 .*\n    .*\n", re.MULTILINE)
_COLUMNS = (
    "source_run_id", "model_kind", "technology_id", "model_revision", "corner",
    "temperature_c", "w_um", "l_um", "vgs_v", "vds_v", "vdsat_v",
    "current_ma", "gm_s", "gds_s", "cgs_f", "cgd_f", "gm_over_id_v_inv",
)


def export_teaching_device_lookup(run_dirs: list[Path], output_dir: Path) -> dict:
    _require_private_path(output_dir)
    if not isinstance(run_dirs, list) or not 2 <= len(run_dirs) <= 12:
        raise ValueError("teaching device lookup requires 2..12 archived runs")
    rows = []
    source_manifests = []
    template = None
    grid = None
    model_revision = None
    seen_ids = set()
    seen_points = set()
    for run_dir in run_dirs:
        if not isinstance(run_dir, Path) or run_dir.name in seen_ids:
            raise ValueError("teaching device run IDs must be distinct")
        audit = audit_teaching_lna(run_dir)
        op = audit.get("device_op")
        if not isinstance(op, dict):
            raise ValueError("teaching device lookup needs audited MOS1 operating-point data")
        metrics = read_evidenced_metrics(run_dir)
        design = metrics.get("design_parameters", {})
        bias = design.get("vbias_v")
        if type(bias) not in {int, float} or not math.isfinite(bias):
            raise ValueError("teaching device bias must be finite")
        source = (run_dir / "netlist.scs").read_text(encoding="ascii")
        if "M1 (drain gate source 0) n_teach w=WMOS l=LMOS" not in source:
            raise ValueError("teaching MOS1 instance geometry is not the characterized W/L")
        if not re.search(r"^parameters VDD=1\.2 VBIAS=[0-9.]+ WMOS=[0-9.]+u LMOS=100n\b", source, re.MULTILINE):
            raise ValueError("teaching device netlists differ beyond VBIAS/WMOS")
        neutralized, count = _BIAS.subn(r"\g<1><BIAS>", source)
        width_match = _WIDTH.search(source)
        if count != 1 or width_match is None:
            raise ValueError("teaching device netlist lacks a valid bias or width")
        width = float(width_match[0])
        recorded_width = design.get("wmos_um", 300.0)
        if (
            not 100 <= width <= 500
            or type(recorded_width) not in {int, float}
            or not math.isclose(recorded_width, width, rel_tol=0, abs_tol=1e-10)
        ):
            raise ValueError("teaching device width disagrees with run metadata")
        point = (width, float(bias))
        if point in seen_points:
            raise ValueError("teaching device width/bias point is duplicated")
        neutralized, width_count = _WIDTH.subn("<WIDTH>", neutralized)
        if width_count != 1 or (template is not None and neutralized != template):
            raise ValueError("teaching device netlists differ beyond VBIAS/WMOS")
        template = neutralized
        match = _MODEL.search(source)
        if match is None:
            raise ValueError("teaching MOS1 model statement is missing")
        model_revision = "sha256_" + hashlib.sha256(match[0].encode("ascii")).hexdigest()[:16]
        frequencies, _ = parse_complex_trace(run_dir / "sp.sp", "s21")
        if grid is not None and frequencies != grid:
            raise ValueError("teaching device SP grids differ")
        grid = frequencies
        if not op["ids"] > 0 or not op["gm"] > 0:
            raise ValueError("teaching device has no positive current or gm")
        row = {
            "source_run_id": run_dir.name,
            "model_kind": "teaching_model", "technology_id": "spectre_mos1_public_teaching",
            "model_revision": model_revision, "corner": "nominal", "temperature_c": 27.0,
            "w_um": width, "l_um": 0.1,
            "vgs_v": op["vgs"], "vds_v": op["vds"], "vdsat_v": op["vdsat"],
            "current_ma": op["ids"] * 1e3, "gm_s": op["gm"], "gds_s": op["gds"],
            "cgs_f": op["cgs"], "cgd_f": op["cgd"],
            "gm_over_id_v_inv": op["gm"] / op["ids"],
        }
        rows.append(row)
        source_manifests.append({
            "run_id": run_dir.name,
            "evidence_manifest_sha256": hashlib.sha256(
                (run_dir / "evidence_manifest.json").read_bytes()
            ).hexdigest(),
        })
        seen_ids.add(run_dir.name)
        seen_points.add(point)
    rows.sort(key=lambda row: (row["w_um"], row["vgs_v"]))
    source_manifests.sort(key=lambda item: item["run_id"])
    widths = sorted({row["w_um"] for row in rows})
    multi_width = len(widths) > 1
    summary = {
        "schema_version": 1,
        "status": "multi_width_characterization" if multi_width else "single_device_characterization",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "teaching_mos1_common_source", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": output_dir.name,
        "scope": "MOS1 fixed-L teaching width/bias grid; no stage mapping, PDK, or RF LNA sizing claim",
        "widths_um": widths,
        "model_revision": model_revision, "template_sha256": hashlib.sha256(template.encode("ascii")).hexdigest(),
        "frequency_points": len(grid), "rows": rows, "source_manifests": source_manifests,
    }
    validate_metrics_payload(summary)
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "device_lookup.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(output_dir / "metrics.json", summary)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json", "lookup": "device_lookup.csv"})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Export audited Spectre MOS1 single-device teaching table")
    parser.add_argument("run_dirs", type=Path, nargs="+")
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_device_lookups")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        result = export_teaching_device_lookup(args.run_dirs, output_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"cannot export teaching device lookup: {type(exc).__name__}: {exc}")
    print(f"status={result['status']} rows={len(result['rows'])} output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
