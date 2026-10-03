from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_spiral_pcell import audit_pdk_spiral_pcell_report
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_spiral_stream import _CELLS, private_library_context
from orfadc.metric_contract import validate_metrics_payload


_LAYOUT_ROOT = _PRIVATE_ROOT / "pdk_spiral_layout"
_STREAM_ROOT = _PRIVATE_ROOT / "pdk_spiral_stream"
_RUNS = {"default": "20260927T061000Z_c7862888", "nr4": "20260927T061020Z_42145c2a"}
_VIA_RUN = "via_hierarchy_20260927_01"
_VIA_SCRIPT_SHA256 = "01919c649ce0e1461fd809d7456db875a4c5c1c8c901f8d1822f23e35e01a15f"
_STREAM_FILES = ("run_status.json", "source_before.oa", "source_after.oa", "cds.lib",
                 "cds_after.lib", "layout.gds", "strmout.log", "summary.txt", "stdout.log", "stderr.log")
_VIA_FILES = ("probe.ocn", "remote_probe.ocn", "report.txt", "ocean.log",
              "after_default.oa", "after_nr4.oa")


def _read(path: Path) -> bytes:
    _require_private_path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("spiral stream source artifact is missing or unsafe")
    return path.read_bytes()


def _shape_count(text: str, name: str) -> int:
    values = re.findall(r"(?m)^\s*" + name + r":\s*(\d+)\s*$", text)
    if len(values) != 1:
        raise ValueError("spiral stream shape count is missing or ambiguous")
    return int(values[0])


def build_pdk_spiral_stream_report(run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("spiral stream summary run ID is invalid")
    layout_summary = _LAYOUT_ROOT / "summary_20260927_01"
    audit_pdk_spiral_pcell_report(layout_summary)
    layout = read_evidenced_metrics(layout_summary)
    via_dir = _LAYOUT_ROOT / _VIA_RUN
    via_script = _read(via_dir / "probe.ocn")
    if (
        hashlib.sha256(via_script).hexdigest() != _VIA_SCRIPT_SHA256
        or via_script != _read(via_dir / "remote_probe.ocn")
        or "-restore probe.ocn" not in _read(via_dir / "ocean.log").decode("utf-8", errors="replace")
    ):
        raise ValueError("spiral via hierarchy probe source differs")
    via_report = _read(via_dir / "report.txt").decode("utf-8")
    if (
        via_report.count("via_master_count=91") != 2
        or via_report.count(" opened=t\n") != 2
        or len(re.findall(r"(?m)^via_master depth=3 ", via_report)) != 104
        or len(re.findall(r"(?m)^via_master depth=4 ", via_report)) != 78
        or len(re.findall(r"bbox=\(\(0\.0 0\.0\) \(0\.0 0\.0\)\) shapes=0 children=0", via_report)) != 52
    ):
        raise ValueError("spiral via hierarchy report differs")
    hashes = {"via": {name: hashlib.sha256(_read(via_dir / name)).hexdigest()
                      for name in _VIA_FILES}}
    for variant in _CELLS:
        oa = _read(_LAYOUT_ROOT / layout["source_run_ids"][variant] / "layout.oa")
        if oa != _read(via_dir / f"after_{variant}.oa"):
            raise ValueError("spiral OA changed during via hierarchy probe")
    shapes = {}
    for variant, run_name in _RUNS.items():
        cell, source_archive = _CELLS[variant]
        library_name, _, tech_lib = private_library_context(layout_summary, variant)
        run_dir = _STREAM_ROOT / run_name
        hashes[variant] = {name: hashlib.sha256(_read(run_dir / name)).hexdigest()
                           for name in _STREAM_FILES}
        status = json.loads(_read(run_dir / "run_status.json").decode("utf-8"))
        oa = _read(_LAYOUT_ROOT / source_archive / "layout.oa")
        if (
            status.get("status") != "stream_diagnostic_with_empty_struct_warnings"
            or status.get("run_id") != run_name or status.get("variant") != variant
            or status.get("source_cell") != cell or status.get("source_archive") != source_archive
            or status.get("source_summary_run_id") != layout_summary.name
            or status.get("source_summary_manifest_sha256") != hashlib.sha256(
                _read(layout_summary / "evidence_manifest.json"),
            ).hexdigest()
            or status.get("source_oa_sha256") != hashlib.sha256(oa).hexdigest()
            or status.get("host_available_gib_before", 0) < 2.66
            or status.get("returncode") != 0
            or status.get("downloads") != dict.fromkeys((
                "layout.gds", "strmout.log", "summary.txt", "source_after.oa", "cds_after.lib",
            ), True)
            or status.get("stream_warning_codes") != ["XSTRM-399"]
            or status.get("stream_warning_count") != 2
            or status.get("drc_ready") is not False
            or status.get("explicit_tech_library") is not True
            or any(status.get(key) is not False for key in (
                "pdk_write", "user_oa_write", "cdf_callback_validated",
                "drc_validated", "physical_qualification",
            ))
            or status.get("not_lna_result") is not True or status.get("spec_pass") is not None
            or oa != _read(run_dir / "source_before.oa")
            or oa != _read(run_dir / "source_after.oa")
            or _read(run_dir / "cds.lib") != _read(run_dir / "cds_after.lib")
            or status.get("cds_lib_sha256") != hashlib.sha256(_read(run_dir / "cds.lib")).hexdigest()
            or len(_read(run_dir / "layout.gds")) < 1024
        ):
            raise ValueError("spiral stream status or source OA differs")
        log = _read(run_dir / "strmout.log").decode("utf-8", errors="replace")
        summary = _read(run_dir / "summary.txt").decode("utf-8", errors="replace")
        layer_map = re.findall(r"(?m)^layerMap\s+(/[^\s]+)$", log)
        if (
            len(layer_map) != 1
            or hashlib.sha256(layer_map[0].encode("utf-8")).hexdigest() != status["layer_map_path_sha256"]
            or len(re.findall(r"(?m)^library\s+" + re.escape(library_name) + r"$", log)) != 1
            or len(re.findall(r"(?m)^topCell\s+" + cell + r"$", log)) != 1
            or len(re.findall(r"(?m)^techLib\s+" + re.escape(tech_lib) + r"$", log)) != 1
            or "Translation completed. '0' error(s) and '2' warning(s) found." not in log
            or len(re.findall(r"WARNING \(XSTRM-399\)", log)) != 2
        ):
            raise ValueError("spiral stream translation provenance or warnings differ")
        counts = {key: _shape_count(summary, label) for key, label in (
            ("polygons", "Polygons"), ("paths", "Paths"), ("rectangles", "Rectangles"),
        )}
        if counts != status.get("shape_counts") or sum(counts.values()) == 0:
            raise ValueError("spiral stream shapes differ from XStream summary")
        shapes[variant] = counts
    if hashes["default"]["layout.gds"] == hashes["nr4"]["layout.gds"]:
        raise ValueError("spiral default and nr4 GDS are indistinguishable")
    payload = {
        "schema_version": 1, "run_id": run_id,
        "status": "pdk_spiral_gds_diagnostic_with_empty_struct_warnings",
        "simulation_status": "unknown", "source": "cadence_xstream_oa_archives",
        "circuit_class": "passive_oneport_layout_probe", "model_kind": "authorized_pdk_private",
        "scope": "Two nonempty GDS exports from saved user PCells; two XSTRM-399 empty-structure warnings each; not DRC-ready or physically qualified",
        "source_layout_summary_run_id": layout_summary.name,
        "source_layout_manifest_sha256": hashlib.sha256(
            _read(layout_summary / "evidence_manifest.json"),
        ).hexdigest(),
        "source_run_ids": {**_RUNS, "via": _VIA_RUN},
        "source_artifact_sha256": hashes,
        "shape_counts_from_xstream": shapes,
        "via_hierarchy_readonly_count_each": 91,
        "oa_empty_via_master_occurrences_total": 52,
        "stream_warning_count_each": 2,
        "gds_files_distinct": True, "gds_geometry_present": True,
        "drc_ready": False, "drc_validated": False,
        "cdf_callback_validated": False, "physical_qualification": False,
        "pdk_write": False, "not_lna_result": True, "spec_pass": None,
    }
    validate_metrics_payload(payload)
    return payload


def write_pdk_spiral_stream_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    report = build_pdk_spiral_stream_report(output_dir.name)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "metrics.json", report)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
    audit_pdk_spiral_stream_report(output_dir)
    return report


def audit_pdk_spiral_stream_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    saved = read_evidenced_metrics(output_dir)
    rebuilt = build_pdk_spiral_stream_report(output_dir.name)
    if saved != rebuilt:
        raise ValueError("spiral GDS report differs from raw OA and XStream archives")
    return {"status": "verified", "drc_ready": False, "physical_qualification": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or audit private spiral PCell GDS diagnostics")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = write_pdk_spiral_stream_report(args.output_dir) if args.finalize else audit_pdk_spiral_stream_report(args.output_dir)
    print(f"status={result['status']} output={args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
