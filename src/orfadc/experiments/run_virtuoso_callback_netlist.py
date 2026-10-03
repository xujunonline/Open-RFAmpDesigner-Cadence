from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_virtuoso_form_netlist import _NETLIST_RESULT, _SCRIPT
from orfadc.experiments.run_virtuoso_form_readback import _context


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")


def _callback_context(callback_run: Path) -> tuple[str, str, str]:
    _require_private_path(callback_run)
    if not callback_run.is_dir() or callback_run.is_symlink():
        raise ValueError("callback diagnostic archive is unavailable")
    status_path = callback_run / "run_status.json"
    script_path = callback_run / "virtuoso_gui_smoke.il"
    if any(not path.is_file() or path.is_symlink() for path in (status_path, script_path)):
        raise ValueError("callback diagnostic source is missing or unsafe")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    script = script_path.read_bytes()
    if (
        status.get("status") != "callback_invoked_and_saved"
        or status.get("callback_invoked") is not True
        or status.get("cdf_callback_validated") is not False
        or status.get("pdk_write") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or hashlib.sha256(script).hexdigest() != status.get("rendered_sha256")
    ):
        raise ValueError("callback diagnostic status is not qualified for netlisting")
    values = {}
    for name in ("libName", "libPath", "sourceCellName", "cellName", "mosName"):
        match = re.search(rb'(?m)^' + name.encode() + rb'="([^"\r\n]+)"\r?$', script)
        if match is None or len(re.findall(rb'(?m)^' + name.encode() + rb'=', script)) != 1:
            raise ValueError("callback script source is ambiguous")
        values[name] = match[1].decode("ascii")
    if any(not _IDENTIFIER.fullmatch(values[name]) for name in ("libName", "sourceCellName", "cellName", "mosName")):
        raise ValueError("callback script identifier is unsafe")
    if not _REMOTE_PATH.fullmatch(values["libPath"]):
        raise ValueError("callback script library path is unsafe")
    if (status.get("source_cell") != values["sourceCellName"]
            or status.get("user_cell_name") != values["cellName"]):
        raise ValueError("callback script cell identity differs from status")
    form_run = _PRIVATE_ROOT / "virtuoso_cdf_form_variant" / status["source_form_run"]
    lib, lib_path, source_cell, mos = _context(form_run)
    if (lib, lib_path, source_cell, mos) != (
        values["libName"], values["libPath"], values["sourceCellName"], values["mosName"],
    ):
        raise ValueError("callback cell source differs from the audited form cell")
    oa = callback_run / "sch.oa"
    if not oa.is_file() or oa.is_symlink() or hashlib.sha256(oa.read_bytes()).hexdigest() != status.get("oa_sha256"):
        raise ValueError("callback cell OA changed after the probe")
    if any(
        (callback_run / name).read_bytes() != (form_run / "sch.oa").read_bytes()
        for name in ("source_before.oa", "source_after.oa")
    ):
        raise ValueError("callback probe changed the source OA")
    return lib, lib_path, values["cellName"]


def run_virtuoso_callback_netlist(
    config_path: Path, output_dir: Path, *, callback_run: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    lib_name, lib_path, cell = _callback_context(callback_run)
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink():
        raise ValueError("checked-in OCEAN netlist script is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before callback netlist")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_SCRIPT, output_dir / _SCRIPT.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"callback_netlist_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_callback_run": callback_run.name, "source_cell": cell,
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
        "source_oa_sha256": hashlib.sha256((callback_run / "sch.oa").read_bytes()).hexdigest(),
        "pdk_write": False, "user_oa_write": False,
        "cdf_callback_validated": False, "not_lna_result": True, "spec_pass": None,
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
    paths = {
        "ocean.log": f"{remote_dir}/ocean.log",
        "netlist_report.txt": f"{remote_dir}/netlist_report.txt",
        "sch.oa": f"{lib_path}/{cell}/schematic/sch.oa",
    }
    downloads = {name: runner.download(remote, output_dir / name).ok for name, remote in paths.items()}
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("netlist_generation_failed", result.returncode)
    oa = (output_dir / "sch.oa").read_bytes()
    if not oa or hashlib.sha256(oa).hexdigest() != status["source_oa_sha256"]:
        return finish("source_oa_changed", result.returncode)
    log = (output_dir / "ocean.log").read_text(encoding="utf-8", errors="replace")
    report = (output_dir / "netlist_report.txt").read_text(encoding="utf-8", errors="replace")
    match = _NETLIST_RESULT.search(report)
    if re.search(r"(?m)^\\e \*Error\*", log) or match is None:
        return finish("netlist_report_incomplete", result.returncode)
    source = match[1]
    input_path = source if source.endswith(".scs") else f"{source}/input.scs"
    downloads["input.scs"] = runner.download(input_path, output_dir / "input.scs").ok
    downloads["ade_e.scs"] = runner.download(
        str(PurePosixPath(input_path).parent / "ade_e.scs"), output_dir / "ade_e.scs",
    ).ok
    if not downloads["input.scs"] or not downloads["ade_e.scs"]:
        return finish("netlist_archive_incomplete", result.returncode)
    status["netlist_sha256"] = hashlib.sha256((output_dir / "input.scs").read_bytes()).hexdigest()
    return finish("netlist_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently netlist a saved callback-probe user cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_callback_netlist")
    parser.add_argument("--callback-run", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_callback_netlist(args.config, output_dir, callback_run=args.callback_run)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "netlist_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
