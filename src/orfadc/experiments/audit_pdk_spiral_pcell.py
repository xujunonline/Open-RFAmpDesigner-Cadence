from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ROOT = _PRIVATE_ROOT / "pdk_spiral_layout"
_SOURCES = {
    "read": ("read_20260927_01", "probe.ocn", "87dbb35e5be354bc3cd5e024a93f2b42535c6fc7d2365685aa96499056cfad86"),
    "default": ("default_20260927_01", "create.ocn", "7386606f459149b0c5b3b0fdb29cd0dd2d8dc843b2a07ee8f97ec845696b2ff8"),
    "nr4": ("nr4_20260927_01", "create.ocn", "17a465c34b555e4b333c5f4c7305ccd19d2a51ccea3778b9ed573e1a3f39fd3f"),
    "failed_read": ("read_saved_20260927_01", "probe.ocn", "f84a17c6c71139cb3e88ef31eb0080bb459a4cbb4e03299e0619d8b8d4def51a"),
    "saved_read": ("read_saved_20260927_02", "probe.ocn", "6514b244c616412ddee42a2b9ea5dbad8494d4c183ad85a3284e8050af8b2241"),
}
_FILES = {
    "read": ("probe.ocn", "remote_probe.ocn", "ocean.log", "report.txt"),
    "default": ("create.ocn", "remote_create.ocn", "ocean.log", "report.txt", "layout.oa"),
    "nr4": ("create.ocn", "remote_create.ocn", "ocean.log", "report.txt", "layout.oa"),
    "failed_read": ("probe.ocn", "remote_probe.ocn", "ocean.log", "report.txt", "after_default.oa", "after_nr4.oa"),
    "saved_read": ("probe.ocn", "remote_probe.ocn", "ocean.log", "report.txt", "after_default.oa", "after_nr4.oa"),
}
_CELL_NAMES = ("spiral_pcell_default_20260927_01", "spiral_pcell_nr4_20260927_01")


def _read(path: Path) -> bytes:
    _require_private_path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("spiral PCell source artifact is missing or unsafe")
    return path.read_bytes()


def _bbox(line: str) -> tuple[float, float, float, float]:
    values = re.findall(r"-?\d+(?:\.\d+)?", line)
    if len(values) != 4:
        raise ValueError("spiral PCell bounding box is malformed")
    box = tuple(float(value) for value in values)
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("spiral PCell bounding box has no area")
    return box


def _line(text: str, prefix: str) -> str:
    found = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(found) != 1:
        raise ValueError(f"spiral PCell report lacks one {prefix} line")
    return found[0]


def _parameters(text: str) -> dict[str, str]:
    found = re.findall(r'^parameter name="([a-z]+)" type="string" value="([^"]+)"$', text, re.MULTILINE)
    values = dict(found)
    if len(found) != 6 or set(values) != {"w", "nr", "rad", "spacing", "gdis", "lay"}:
        raise ValueError("spiral PCell parameter readback differs")
    return values


def _saved_block(text: str, cell: str) -> str:
    start = f"cell={cell} opened=t\n"
    if text.count(start) != 1:
        raise ValueError("saved spiral PCell cell did not reopen")
    return text.split(start, 1)[1].split("cell=", 1)[0]


def build_pdk_spiral_pcell_report(run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("spiral PCell summary run ID is invalid")
    archives = {key: _ROOT / info[0] for key, info in _SOURCES.items()}
    hashes = {}
    for key, directory in archives.items():
        script_name, expected_hash = _SOURCES[key][1:]
        script = _read(directory / script_name)
        if hashlib.sha256(script).hexdigest() != expected_hash:
            raise ValueError("spiral PCell probe script differs from its fixed source")
        remote_script = _read(directory / f"remote_{script_name}")
        if script != remote_script:
            raise ValueError("spiral PCell remote script differs")
        hashes[key] = {name: hashlib.sha256(_read(directory / name)).hexdigest()
                       for name in _FILES[key]}
        log = _read(directory / "ocean.log").decode("utf-8", errors="replace")
        if re.search(r"(?m)^\\e \*Error\*", log) or "-restore " + script_name not in log:
            raise ValueError("spiral PCell OCEAN log has an error or different source")
    read_text = _read(archives["read"] / "report.txt").decode("utf-8")
    if "view=layout opened=t" not in read_text or "view=ivpcell opened=t" not in read_text:
        raise ValueError("spiral PCell master views were not read")
    if 'view_param name="nr" type="string" value="3"' not in read_text:
        raise ValueError("spiral PCell default master parameter differs")
    reports = {key: _read(archives[key] / "report.txt").decode("utf-8")
               for key in ("default", "nr4")}
    params = {key: _parameters(report) for key, report in reports.items()}
    if (
        params["default"].get("nr") != "3" or params["nr4"].get("nr") != "4"
        or any(params["default"][key] != params["nr4"][key]
               for key in ("w", "rad", "spacing", "gdis", "lay"))
        or any(_line(report, "save=") != "save=t" for report in reports.values())
        or any("master_shapes=24 master_children=42 master_terminals=3" not in report
               for report in reports.values())
    ):
        raise ValueError("spiral PCell placement or one-parameter change differs")
    placed = {key: _bbox(_line(report, "instance_bbox=").split(" master_bbox=", 1)[0])
              for key, report in reports.items()}
    if placed["default"] == placed["nr4"]:
        raise ValueError("spiral PCell instance geometry did not respond to nr")
    failed = _read(archives["failed_read"] / "report.txt").decode("utf-8")
    if failed.splitlines() != [f"cell={cell} opened=nil" for cell in _CELL_NAMES]:
        raise ValueError("failed first read must remain an unqualified failed archive")
    saved = _read(archives["saved_read"] / "report.txt").decode("utf-8")
    core = {}
    for key, cell in zip(("default", "nr4"), _CELL_NAMES, strict=True):
        block = _saved_block(saved, cell)
        if (
            _line(block, "top_instances=").split()[0] != "top_instances=1"
            or _line(block, "instance=").split()[0] != 'instance="L1"'
            or _parameters(block) != params[key]
            or _bbox(_line(block, "instance=").split(" bbox=", 1)[1]) != placed[key]
            or "master_shapes=24 master_children=42 master_terminals=3" not in block
        ):
            raise ValueError("saved spiral PCell does not match placement report")
        cores = [line for line in block.splitlines() if line.startswith('core_child="ind_M9"')]
        if len(cores) != 1:
            raise ValueError("saved spiral PCell core geometry is missing")
        core[key] = _bbox(cores[0].split(" bbox=", 1)[1])
        original = _read(archives[key] / "layout.oa")
        if len(original) < 1024 or original != _read(archives["saved_read"] / f"after_{key}.oa"):
            raise ValueError("spiral PCell OA changed during successful readback")
        if original != _read(archives["failed_read"] / f"after_{key}.oa"):
            raise ValueError("spiral PCell OA changed during failed readback")
    if core["default"] == core["nr4"] or hashes["default"]["layout.oa"] == hashes["nr4"]["layout.oa"]:
        raise ValueError("spiral PCell core and saved OA did not differ")
    if not all("techSaveDrmForm" in _read(archives[key] / "ocean.log").decode("utf-8", errors="replace")
               for key in ("default", "nr4")):
        raise ValueError("spiral PCell initialization warning profile differs")
    payload = {
        "schema_version": 1, "run_id": run_id,
        "status": "pdk_spiral_low_level_pcell_geometry_response",
        "simulation_status": "unknown", "source": "cadence_ocean_oa_archives",
        "circuit_class": "passive_oneport_layout_probe", "model_kind": "authorized_pdk_private",
        "scope": "Two newly saved user-layout cells with a one-parameter nr change; no schematic, CDF, DRC, EM or PEX qualification",
        "source_run_ids": {key: info[0] for key, info in _SOURCES.items()},
        "source_artifact_sha256": hashes,
        "read_only_master_observed": True, "failed_read_excluded": True,
        "two_new_user_layout_cells_saved": True, "one_parameter_nr_change": True,
        "instance_bbox_changed": True, "core_bbox_changed": True,
        "oa_unchanged_after_readback": True, "initialization_warning_present": True,
        "pdk_write": False, "user_oa_write": True,
        "cdf_callback_validated": False, "drc_validated": False,
        "physical_qualification": False, "not_lna_result": True, "spec_pass": None,
    }
    validate_metrics_payload(payload)
    return payload


def write_pdk_spiral_pcell_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    report = build_pdk_spiral_pcell_report(output_dir.name)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "metrics.json", report)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
    audit_pdk_spiral_pcell_report(output_dir)
    return report


def audit_pdk_spiral_pcell_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    saved = read_evidenced_metrics(output_dir)
    rebuilt = build_pdk_spiral_pcell_report(output_dir.name)
    if saved != rebuilt:
        raise ValueError("spiral PCell summary differs from the private OA archives")
    return {"status": "verified", "physical_qualification": False,
            "cdf_callback_validated": False, "drc_validated": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or reaudited private spiral PCell geometry evidence")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = write_pdk_spiral_pcell_report(args.output_dir) if args.finalize else audit_pdk_spiral_pcell_report(args.output_dir)
    print(f"status={result['status']} output={args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
