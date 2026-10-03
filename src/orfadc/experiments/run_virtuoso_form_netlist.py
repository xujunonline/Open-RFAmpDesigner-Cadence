from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_virtuoso_form_readback import _context


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "circuit/ocean/netlist_user_mos_form.ocn"
_NETLIST_RESULT = re.compile(r'(?m)^netlist_result="(/[A-Za-z0-9._/+-]+)"$')


def run_virtuoso_form_netlist(
    config_path: Path, output_dir: Path, *, form_run: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    lib_name, lib_path, cell, _ = _context(form_run)
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink():
        raise ValueError("checked-in netlist script is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before form netlist")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_SCRIPT, output_dir / _SCRIPT.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"form_netlist_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_form_run": form_run.name, "source_cell": cell,
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
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
    env = ["env", f"ORFADC_REPORT={remote_dir}/netlist_report.txt",
           f"ORFADC_USER_LIB={lib_name}", f"ORFADC_USER_LIB_PATH={lib_path}",
           f"ORFADC_USER_CELL={cell}"]
    if runner.config.xvfb_path:
        env.append(f"CDS_XVFB_PATH={runner.config.xvfb_path}")
    result = runner.run_remote(
        [*env, runner.config.ocean_bin, "-nograph", "-restore", _SCRIPT.name,
         "-log", f"{remote_dir}/ocean.log"], cwd=remote_dir, timeout_seconds=120,
    )
    (output_dir / "ocean.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "ocean.stderr").write_text(result.stderr, encoding="utf-8")
    downloads = {
        name: runner.download(f"{remote_dir}/{name}", output_dir / name).ok
        for name in ("ocean.log", "netlist_report.txt")
    }
    downloads["sch.oa"] = runner.download(
        f"{lib_path}/{cell}/schematic/sch.oa", output_dir / "sch.oa",
    ).ok
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("netlist_generation_failed", result.returncode)
    log = (output_dir / "ocean.log").read_text(encoding="utf-8", errors="replace")
    report = (output_dir / "netlist_report.txt").read_text(encoding="utf-8", errors="replace")
    match = _NETLIST_RESULT.search(report)
    if re.search(r"(?m)^\\e \*Error\*", log) or match is None:
        return finish("netlist_report_incomplete", result.returncode)
    source = match[1]
    candidates = (source,) if source.endswith(".scs") else (f"{source}/input.scs",)
    input_path = candidates[0]
    downloads["input.scs"] = runner.download(input_path, output_dir / "input.scs").ok
    if not downloads["input.scs"]:
        return finish("netlist_missing", result.returncode)
    companion = str(PurePosixPath(input_path).parent / "ade_e.scs")
    downloads["ade_e.scs"] = runner.download(companion, output_dir / "ade_e.scs").ok
    if not downloads["ade_e.scs"]:
        return finish("netlist_companion_missing", result.returncode)
    status["netlist_sha256"] = hashlib.sha256((output_dir / "input.scs").read_bytes()).hexdigest()
    status["oa_sha256"] = hashlib.sha256((output_dir / "sch.oa").read_bytes()).hexdigest()
    return finish("netlist_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export one saved form diagnostic OA schematic to Spectre")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_form_netlist")
    parser.add_argument("--form-run", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_form_netlist(args.config, output_dir, form_run=args.form_run)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "netlist_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
