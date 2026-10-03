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


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "circuit/ocean/readback_user_mos_form.ocn"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")


def _context(form_run: Path) -> tuple[str, str, str, str]:
    _require_private_path(form_run)
    if not form_run.is_dir() or form_run.is_symlink():
        raise ValueError("form diagnostic archive is unavailable")
    status = json.loads((form_run / "run_status.json").read_text(encoding="utf-8"))
    source = (form_run / "source_copy.ocn").read_bytes()
    if (
        status.get("status") != "form_action_recorded"
        or status.get("baseline_copy") is not True
        or status.get("user_cell_name") is None
        or hashlib.sha256(source).hexdigest() != status.get("source_sha256")
        or not (form_run / "sch.oa").is_file()
    ):
        raise ValueError("form diagnostic lacks a saved copied-cell source")
    fields = {}
    for key in (b"libName", b"libPath"):
        match = re.search(rb'(?m)^' + key + rb'="([^"\r\n]+)"\r?$', source)
        if match is None:
            raise ValueError("form diagnostic source lacks user-library registration")
        fields[key.decode("ascii")] = match[1].decode("ascii")
    mos = re.search(rb'when\(inst~>name=="([^"\r\n]+)" mos=inst\)', source)
    if mos is None:
        raise ValueError("form diagnostic source lacks its MOS instance binding")
    cell = status["user_cell_name"]
    mos_name = mos[1].decode("ascii")
    if any(not _IDENTIFIER.fullmatch(value) for value in (fields["libName"], cell, mos_name)):
        raise ValueError("form diagnostic identifier is unsafe")
    if not _REMOTE_PATH.fullmatch(fields["libPath"]):
        raise ValueError("form diagnostic library path is unsafe")
    return fields["libName"], fields["libPath"], cell, mos_name


def run_virtuoso_form_readback(
    config_path: Path, output_dir: Path, *, form_run: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    lib_name, lib_path, cell, mos = _context(form_run)
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink():
        raise ValueError("checked-in readback script is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before CDF readback")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_SCRIPT, output_dir / _SCRIPT.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"form_readback_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_form_run": form_run.name, "source_cell": cell,
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
        "pdk_write": False, "user_oa_write": False, "cdf_callback_invoked": False,
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
    env = ["env", f"ORFADC_REPORT={remote_dir}/readback_report.txt",
           f"ORFADC_USER_LIB={lib_name}", f"ORFADC_USER_LIB_PATH={lib_path}",
           f"ORFADC_USER_CELL={cell}", f"ORFADC_USER_MOS={mos}"]
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
        for name in ("ocean.log", "readback_report.txt")
    }
    downloads["sch.oa"] = runner.download(
        f"{lib_path}/{cell}/schematic/sch.oa", output_dir / "sch.oa",
    ).ok
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("readback_failed", result.returncode)
    log = (output_dir / "ocean.log").read_text(encoding="utf-8", errors="replace")
    report = (output_dir / "readback_report.txt").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or "readback_complete=t" not in report:
        return finish("readback_incomplete", result.returncode)
    status["oa_sha256"] = hashlib.sha256((output_dir / "sch.oa").read_bytes()).hexdigest()
    return finish("readback_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently reopen a saved PDK form diagnostic cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_form_readback")
    parser.add_argument("--form-run", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_form_readback(args.config, output_dir, form_run=args.form_run)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "readback_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
