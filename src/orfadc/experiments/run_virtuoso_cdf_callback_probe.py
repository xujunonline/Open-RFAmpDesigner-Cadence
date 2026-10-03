from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_virtuoso_cdf_readonly import _LAUNCHER, _LOGS
from orfadc.experiments.run_virtuoso_form_readback import _context


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")


def _render_callback_probe(
    *, lib_name: str, lib_path: str, source_cell: str, cell_name: str,
    mos_name: str, report_path: str,
) -> bytes:
    if any(not _IDENTIFIER.fullmatch(value) for value in (lib_name, source_cell, cell_name, mos_name)):
        raise ValueError("callback probe has an unsafe identifier")
    if any(not _REMOTE_PATH.fullmatch(value) for value in (lib_path, report_path)):
        raise ValueError("callback probe has an unsafe path")
    if source_cell == cell_name:
        raise ValueError("callback probe must not edit the source cell")
    return f'''reportPort=outfile("{report_path}" "w")
libName="{lib_name}"
libPath="{lib_path}"
sourceCellName="{source_cell}"
cellName="{cell_name}"
mosName="{mos_name}"
libObj=ddGetObj(libName)
unless(libObj libObj=ddCreateLib(libName libPath))
unless(libObj error("user library registration failed"))
oldCv=dbOpenCellViewByType(libName cellName "schematic" "schematic" "r")
when(oldCv
  dbClose(oldCv)
  error("callback probe cell already exists")
)
sourceCv=dbOpenCellViewByType(libName sourceCellName "schematic" "schematic" "r")
unless(sourceCv error("saved form source cell is unavailable"))
copyCv=dbCopyCellView(sourceCv libName cellName "schematic")
unless(copyCv error("callback probe copy failed"))
dbClose(sourceCv)
fprintf(reportPort "copy_save=%L\\n" dbSave(copyCv))
dbClose(copyCv)
formWindow=geOpen(?lib libName ?cell cellName ?view "schematic" ?mode "a")
unless(formWindow error("callback probe window did not open"))
formCv=geGetWindowCellView()
unless(formCv error("callback probe cellview is unavailable"))
mos=dbFindAnyInstByName(formCv mosName)
unless(mos error("callback probe MOS instance is unavailable"))
cdfgData=cdfGetInstCDF(mos)
unless(cdfgData error("instance CDF is unavailable"))
callbackParam=cdfFindParamByName(cdfgData "Wfg")
unless(callbackParam && callbackParam~>callback && callbackParam~>callback!=""
  error("Wfg callback is unavailable"))
fprintf(reportPort "callback_present=t\\n")
foreach(param cdfgData~>parameters
  when(member(param~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "before_cdf name=%s value=%L\\n" param~>name param~>value)
  )
)
foreach(prop mos~>prop
  when(member(prop~>name list("Wfg" "w" "l" "nf" "fingers" "ad" "as" "pd" "ps" "nrd" "nrs" "sd" "sa" "sb"))
    fprintf(reportPort "before_instance name=%s value=%L\\n" prop~>name prop~>value)
  )
)
printf("ORFADC_CALLBACK_ATTEMPT\\n")
callbackResult=errset(evalstring(callbackParam~>callback) t)
unless(callbackResult error("Wfg callback failed"))
printf("ORFADC_CALLBACK_RETURNED\\n")
fprintf(reportPort "callback_returned=t\\n")
mos=dbFindAnyInstByName(formCv mosName)
cdfAfter=cdfGetInstCDF(mos)
foreach(param cdfAfter~>parameters
  when(member(param~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "after_cdf name=%s value=%L\\n" param~>name param~>value)
  )
)
foreach(prop mos~>prop
  when(member(prop~>name list("Wfg" "w" "l" "nf" "fingers" "ad" "as" "pd" "ps" "nrd" "nrs" "sd" "sa" "sb"))
    fprintf(reportPort "after_instance name=%s value=%L\\n" prop~>name prop~>value)
  )
)
fprintf(reportPort "check_return=%L\\n" schCheck(formCv))
fprintf(reportPort "save_return=%L\\n" dbSave(formCv))
fprintf(reportPort "callback_probe_end=t\\n")
close(reportPort)
exit()
'''.encode("ascii")


def run_virtuoso_cdf_callback_probe(
    config_path: Path, output_dir: Path, *, form_run: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    lib_name, lib_path, source_cell, mos_name = _context(form_run)
    source_oa = form_run / "sch.oa"
    if not source_oa.is_file() or source_oa.is_symlink() or not _LAUNCHER.is_file():
        raise ValueError("callback probe source or GUI launcher is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before callback probe")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("configured Xvfb is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-f", xvfb]).ok or not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    owned = runner.run_shell(
        f"test -d {shlex.quote(lib_path)} && test -w {shlex.quote(lib_path)} "
        f"&& test ! -L {shlex.quote(lib_path)} "
        f"&& test \"$(stat -c %U {shlex.quote(lib_path)})\" = \"$(id -un)\"",
        timeout_seconds=30,
    )
    if not owned.ok:
        raise ValueError("callback probe library is not an owned user library")
    token = uuid4().hex[:12]
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"cdf_callback_{token}")
    cell_name = f"cdf_callback_{token}"
    script = _render_callback_probe(
        lib_name=lib_name, lib_path=lib_path, source_cell=source_cell,
        cell_name=cell_name, mos_name=mos_name,
        report_path=f"{remote_dir}/callback_report.txt",
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "virtuoso_gui_smoke.il").write_bytes(script)
    shutil.copy2(_LAUNCHER, output_dir / _LAUNCHER.name)
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_form_run": form_run.name, "source_cell": source_cell,
        "user_cell_name": cell_name, "host_available_gib_before": available,
        "rendered_sha256": hashlib.sha256(script).hexdigest(),
        "launcher_sha256": hashlib.sha256(_LAUNCHER.read_bytes()).hexdigest(),
        "source_oa_sha256": hashlib.sha256(source_oa.read_bytes()).hexdigest(),
        "pdk_write": False, "user_oa_write": True,
        "cdf_callback_validated": False, "physical_qualification": False,
        "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    if not runner.download(
        f"{lib_path}/{source_cell}/schematic/sch.oa", output_dir / "source_before.oa",
    ).ok:
        return finish("source_oa_missing")
    if hashlib.sha256((output_dir / "source_before.oa").read_bytes()).hexdigest() != status["source_oa_sha256"]:
        return finish("source_oa_changed")
    for name in ("virtuoso_gui_smoke.il", _LAUNCHER.name):
        if not runner.upload(output_dir / name, f"{remote_dir}/{name}").ok:
            return finish("upload_failed")
    display_number = 1000 + int(uuid4().hex[:4], 16) % 50000
    result = runner.run_remote(
        ["env", f"ORFADC_XVFB={xvfb}", f"ORFADC_DISPLAY_NUMBER={display_number}",
         "bash", _LAUNCHER.name], cwd=remote_dir, timeout_seconds=150,
    )
    (output_dir / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    paths = {
        **{name: f"{remote_dir}/{name}" for name in (*_LOGS, "callback_report.txt")},
        "source_after.oa": f"{lib_path}/{source_cell}/schematic/sch.oa",
        "sch.oa": f"{lib_path}/{cell_name}/schematic/sch.oa",
    }
    downloads = {name: runner.download(remote, output_dir / name).ok for name, remote in paths.items()}
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("callback_archive_incomplete", result.returncode)
    before = (output_dir / "source_before.oa").read_bytes()
    after = (output_dir / "source_after.oa").read_bytes()
    if before != after:
        return finish("source_oa_changed", result.returncode)
    log = (output_dir / "virtuoso.log").read_text(encoding="utf-8", errors="replace")
    report = (output_dir / "callback_report.txt").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or "\\o ORFADC_CALLBACK_RETURNED" not in log:
        return finish("callback_failed", result.returncode)
    if any(fragment not in report for fragment in (
        "callback_present=t", "callback_returned=t", "copy_save=t",
        "check_return=(0 0)", "save_return=t", "callback_probe_end=t",
    )):
        return finish("callback_save_unconfirmed", result.returncode)
    status["callback_invoked"] = True
    status["oa_sha256"] = hashlib.sha256((output_dir / "sch.oa").read_bytes()).hexdigest()
    return finish("callback_invoked_and_saved", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated PDK Wfg callback probe on a copied user cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_cdf_callback_probe")
    parser.add_argument("--form-run", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_cdf_callback_probe(args.config, output_dir, form_run=args.form_run)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "callback_invoked_and_saved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
