from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_spiral_pcell import audit_pdk_spiral_pcell_report
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path


_CELLS = {
    "default": ("spiral_pcell_default_20260927_01", "default_20260927_01"),
    "nr4": ("spiral_pcell_nr4_20260927_01", "nr4_20260927_01"),
}
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def private_library_context(source_summary: Path, variant: str) -> tuple[str, str, str]:
    archive = _CELLS[variant][1]
    creation = (source_summary.parent / archive / "create.ocn").read_text(encoding="utf-8")
    probe = (source_summary.parent / "read_20260927_01" / "probe.ocn").read_text(encoding="utf-8")
    library = re.findall(r'(?m)^libName="([^"]+)"$', creation)
    lib_path = re.findall(r'(?m)^libPath="([^"]+)"$', creation)
    tech = re.findall(r'dbOpenCellViewByType\("([^"]+)"\s+"[^"]+"\s+viewName', probe)
    if (
        len(library) != 1 or len(lib_path) != 1 or len(tech) != 1
        or _IDENTIFIER.fullmatch(library[0]) is None
        or _IDENTIFIER.fullmatch(tech[0]) is None
        or _REMOTE_PATH.fullmatch(lib_path[0]) is None
    ):
        raise ValueError("audited private OA scripts lack one safe library context")
    return library[0], lib_path[0], tech[0]


def run_pdk_spiral_stream(
    config_path: Path, output_dir: Path, *, source_summary: Path,
    variant: str, layer_map: str, runner: RemoteRunner | None = None,
) -> dict:
    for path in (output_dir, source_summary):
        _require_private_path(path)
    if variant not in _CELLS or _REMOTE_PATH.fullmatch(layer_map) is None:
        raise ValueError("spiral stream needs a known user cell and private absolute layer map")
    audit_pdk_spiral_pcell_report(source_summary)
    source = json.loads((source_summary / "metrics.json").read_text(encoding="utf-8"))
    cell, archive = _CELLS[variant]
    library_name, user_lib, tech_lib = private_library_context(source_summary, variant)
    if source["source_run_ids"][variant] != archive:
        raise ValueError("spiral stream source cell is not the audited layout")
    local_oa = source_summary.parent / archive / "layout.oa"
    oa = local_oa.read_bytes()
    if hashlib.sha256(oa).hexdigest() != source["source_artifact_sha256"][variant]["layout.oa"]:
        raise ValueError("spiral stream OA source changed")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before spiral stream")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    remote_oa_path = f"{user_lib}/{cell}/layout/layout.oa"
    output_dir.mkdir(parents=True, exist_ok=False)
    if not runner.download(remote_oa_path, output_dir / "source_before.oa").ok:
        raise RuntimeError("saved user OA source could not be read")
    if (output_dir / "source_before.oa").read_bytes() != oa:
        raise RuntimeError("saved user OA differs from its audited archive")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"spiral_stream_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "variant": variant, "source_cell": cell, "source_archive": archive,
        "source_summary_run_id": source_summary.name,
        "source_summary_manifest_sha256": hashlib.sha256(
            (source_summary / "evidence_manifest.json").read_bytes(),
        ).hexdigest(),
        "source_oa_sha256": hashlib.sha256(oa).hexdigest(),
        "layer_map_path_sha256": hashlib.sha256(layer_map.encode("utf-8")).hexdigest(),
        "host_available_gib_before": available,
        "explicit_tech_library": True, "pdk_write": False, "user_oa_write": False,
        "cdf_callback_validated": False, "drc_validated": False,
        "physical_qualification": False, "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    remote_context = str(PurePosixPath(runner.config.remote_root) / cell)
    remote_cds_lib = f"{remote_context}/cds.lib"
    if not runner.run_remote(["test", "-f", remote_cds_lib]).ok:
        return finish("source_library_mapping_missing")
    if not runner.download(remote_cds_lib, output_dir / "cds.lib").ok:
        return finish("source_library_mapping_download_failed")
    status["cds_lib_sha256"] = hashlib.sha256((output_dir / "cds.lib").read_bytes()).hexdigest()
    remote_gds = f"{remote_dir}/layout.gds"
    remote_log = f"{remote_dir}/strmout.log"
    remote_summary = f"{remote_dir}/summary.txt"
    result = runner.run_remote([
        "strmout", "-library", library_name, "-strmFile", remote_gds,
        "-topCell", cell, "-view", "layout", "-logFile", remote_log,
        "-summaryFile", remote_summary, "-techLib", tech_lib,
        "-layerMap", layer_map,
    ], cwd=remote_context, timeout_seconds=240)
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    downloads = {
        name: runner.download(remote, output_dir / name).ok
        for name, remote in (
            ("layout.gds", remote_gds), ("strmout.log", remote_log),
            ("summary.txt", remote_summary), ("source_after.oa", remote_oa_path),
            ("cds_after.lib", remote_cds_lib),
        )
    }
    status["downloads"] = downloads
    if not result.ok or not all(downloads.values()):
        return finish("stream_or_download_failed", result.returncode)
    if (output_dir / "source_after.oa").read_bytes() != oa:
        return finish("user_oa_changed", result.returncode)
    if (output_dir / "cds_after.lib").read_bytes() != (output_dir / "cds.lib").read_bytes():
        return finish("library_mapping_changed", result.returncode)
    log = (output_dir / "strmout.log").read_text(encoding="utf-8", errors="replace")
    summary = (output_dir / "summary.txt").read_text(encoding="utf-8", errors="replace")
    counts = [re.findall(r"(?m)^\s*" + name + r":\s*(\d+)\s*$", summary)
              for name in ("Polygons", "Paths", "Rectangles")]
    completion = re.search(
        r"Translation completed\. '([0-9]+)' error\(s\) and '([0-9]+)' warning\(s\) found\.", log,
    )
    warning_codes = re.findall(r"WARNING \((XSTRM-[0-9]+)\)", log)
    if (
        completion is None or int(completion[1]) != 0
        or int(completion[2]) != len(warning_codes)
        or any(len(values) != 1 for values in counts)
        or sum(int(values[0]) for values in counts) == 0
        or (output_dir / "layout.gds").stat().st_size < 1024
    ):
        return finish("stream_geometry_unverified", result.returncode)
    status["shape_counts"] = {name: int(values[0]) for name, values in
                              zip(("polygons", "paths", "rectangles"), counts, strict=True)}
    status["stream_warning_codes"] = sorted(set(warning_codes))
    status["stream_warning_count"] = len(warning_codes)
    status["drc_ready"] = not warning_codes
    if warning_codes:
        if warning_codes != ["XSTRM-399", "XSTRM-399"]:
            return finish("stream_warning_profile_unverified", result.returncode)
        return finish("stream_diagnostic_with_empty_struct_warnings", result.returncode)
    return finish("stream_geometry_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream an audited user spiral PCell layout to private GDS")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--source-summary", type=Path, required=True)
    parser.add_argument("--variant", choices=tuple(_CELLS), required=True)
    parser.add_argument("--layer-map", required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_spiral_stream")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    status = run_pdk_spiral_stream(
        args.config, output_dir, source_summary=args.source_summary,
        variant=args.variant, layer_map=args.layer_map,
    )
    print(f"status={status['status']} output={output_dir.resolve()}")
    return 0 if status["status"] in {
        "stream_geometry_recorded", "stream_diagnostic_with_empty_struct_warnings",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
