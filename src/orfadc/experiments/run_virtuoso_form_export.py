from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.ocean_ascii import read_ocean_rf_data, read_ocean_vdd_current
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "circuit/ocean/export_form_sp_noise.ocn"
_TRACE_NAMES = tuple(f"{signal}_{part}.txt" for signal in ("s11", "s21", "s12", "s22")
                     for part in ("real", "imag")) + ("NF.txt", "NFmin.txt", "F.txt", "Fmin.txt")
_RESULTS_DIR = re.compile(rb'(?m)^resultsDir\("(/[A-Za-z0-9._/+-]+)"\)\r?$')


def _source_psf(spectre_run: Path) -> tuple[dict, str]:
    _require_private_path(spectre_run)
    if not spectre_run.is_dir() or spectre_run.is_symlink():
        raise ValueError("Spectre diagnostic archive is unavailable")
    import json
    status = json.loads((spectre_run / "run_status.json").read_text(encoding="utf-8"))
    source = (spectre_run / "run_same_condition.ocn").read_bytes()
    match = _RESULTS_DIR.search(source)
    if (
        status.get("status") != "spectre_raw_recorded"
        or status.get("target") not in {"baseline", "form", "callback"}
        or status.get("analysis") != ["dc", "sp", "noise"]
        or hashlib.sha256(source).hexdigest() != status.get("rendered_sha256")
        or match is None
    ):
        raise ValueError("Spectre source does not bind an archived PSF result")
    for name in ("spectre.out", "dcOp.dc", "sp.sp", "sp.noise.sp", "input.scs", "ade_e.scs"):
        if not (spectre_run / name).is_file() or (spectre_run / name).is_symlink():
            raise ValueError("Spectre raw source archive is incomplete")
    return status, match[1].decode("ascii") + "/psf"


def run_virtuoso_form_export(
    config_path: Path, output_dir: Path, *, spectre_run: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    source_status, psf_root = _source_psf(spectre_run)
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink():
        raise ValueError("checked-in OCEAN export script is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before PSF export")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_SCRIPT, output_dir / _SCRIPT.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"form_export_{uuid4().hex[:12]}")
    source_hashes = {
        name: hashlib.sha256((spectre_run / name).read_bytes()).hexdigest()
        for name in ("spectre.out", "dcOp.dc", "sp.sp", "sp.noise.sp", "input.scs", "ade_e.scs")
    }
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_spectre_run": spectre_run.name, "target": source_status["target"],
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
        "source_sha256": source_hashes,
        "ocn_precision_digits": 15,
        "pdk_write": False, "user_oa_write": False,
        "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    if not runner.upload(_SCRIPT, f"{remote_dir}/{_SCRIPT.name}").ok:
        return finish("upload_failed")
    env = ["env", f"ORFADC_FORM_RESULTS_PSF={psf_root}"]
    if runner.config.xvfb_path:
        env.append(f"CDS_XVFB_PATH={runner.config.xvfb_path}")
    result = runner.run_remote(
        [*env, runner.config.ocean_bin, "-nograph", "-restore", _SCRIPT.name,
         "-log", f"{remote_dir}/ocean.log"], cwd=remote_dir, timeout_seconds=120,
    )
    (output_dir / "ocean.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "ocean.stderr").write_text(result.stderr, encoding="utf-8")
    names = ("ocean.log", "form_sp_export_report.txt", *_TRACE_NAMES)
    downloads = {name: runner.download(f"{remote_dir}/{name}", output_dir / name).ok for name in names}
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("export_incomplete", result.returncode)
    log = (output_dir / "ocean.log").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log):
        return finish("export_skill_error", result.returncode)
    try:
        rows, stability = read_ocean_rf_data(output_dir)
        current_ma = read_ocean_vdd_current(output_dir / "form_sp_export_report.txt")
    except (OSError, ValueError, TypeError):
        return finish("export_parse_failed", result.returncode)
    write_json(output_dir / "diagnostic_summary.json", {
        "status": "diagnostic_only", "source_spectre_run": spectre_run.name,
        "target": source_status["target"], "sample_count": len(rows),
        "start_ghz": rows[0]["freq_ghz"], "stop_ghz": rows[-1]["freq_ghz"],
        "worst_s11_db": max(row["s11_db"] for row in rows),
        "worst_s21_db": min(row["s21_db"] for row in rows),
        "worst_nf_db": max(row["nf_db"] for row in rows),
        "current_ma": current_ma,
        "sampled_min_k": stability["minimum_k"] if stability else None,
        "not_lna_result": True, "spec_pass": None,
    })
    status["sample_count"] = len(rows)
    return finish("export_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export 15-digit OCEAN SP/noise traces from a form diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--spectre-run", type=Path, required=True)
    args = parser.parse_args()
    source_status, _ = _source_psf(args.spectre_run)
    output_root = args.output_root or _PRIVATE_ROOT / (
        "virtuoso_callback_exports" if source_status["target"] == "callback" else "virtuoso_form_exports"
    )
    output_dir = output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_form_export(args.config, output_dir, spectre_run=args.spectre_run)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "export_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
