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


_ROOT = Path(__file__).resolve().parents[3]
_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_smoke.sh"
_REPORT_LINE = re.compile(rb'^reportPort=outfile\("[^"\r\n]+" "w"\)\r?\n', re.MULTILINE)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_LOGS = ("virtuoso.log", "virtuoso.stdout", "virtuoso.stderr", "xvfb.stdout", "xvfb.stderr")


_FORM_PROBE = b'''printf("ORFADC_FORM_WINDOW_ATTEMPT\\n")
formWindow=geOpen(?lib libName ?cell formCellName ?view "schematic" ?mode "r")
fprintf(reportPort "form_window=%L\\n" formWindow!=nil)
when(formWindow
  formCv=geGetWindowCellView()
  fprintf(reportPort "form_window_cv=%L\\n" formCv!=nil)
  when(formCv && formCv~>instances
    geSelectFig(car(formCv~>instances))
    printf("ORFADC_FORM_OPEN_ATTEMPT\\n")
    schHiObjectProperty()
    activeForm=hiGetCurrentForm()
    fprintf(reportPort "form_object=%L\\n" activeForm!=nil)
    fprintf(reportPort "form_global_bound=%L\\n" boundp('schObjPropForm))
    when(boundp('schObjPropForm)
      fprintf(reportPort "form_global_object=%L\\n" schObjPropForm!=nil)
      when(schObjPropForm
        fprintf(reportPort "form_field_count=%d\\n" length(schObjPropForm~>fieldList))
        fprintf(reportPort "form_w_field=%L\\n" schObjPropForm~>w!=nil)
        fprintf(reportPort "form_Wfg_field=%L\\n" schObjPropForm~>Wfg!=nil)
        fprintf(reportPort "form_l_field=%L\\n" schObjPropForm~>l!=nil)
      )
    )
  )
)
fprintf(reportPort "form_probe_end=t\\n")
'''


def _render_readonly_script(
    source: Path, expected_sha256: str, remote_report: str, *, form_probe: bool = False,
) -> bytes:
    _require_private_path(source)
    if not _HASH.fullmatch(expected_sha256) or not source.is_file() or source.is_symlink():
        raise ValueError("a fixed private CDF source and SHA-256 are required")
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected_sha256:
        raise ValueError("private CDF source changed")
    if not original.endswith(b"exit()\n"):
        raise ValueError("CDF source must have a bounded exit")
    if any(token in original for token in (b"dbSave(", b"dbCreate", b"vfoSetParam", b"cdfSet")):
        raise ValueError("CDF source must not request a design or CDF write")
    matches = _REPORT_LINE.findall(original)
    if len(matches) != 1 or matches[0] != original.splitlines(keepends=True)[0]:
        raise ValueError("CDF source lacks a unique first-line report output")
    report_line = f'reportPort=outfile("{remote_report}" "w")\n'.encode("ascii")
    rendered, count = _REPORT_LINE.subn(lambda _: report_line, original, count=1)
    assert count == 1
    if form_probe:
        tail = b"close(reportPort)\nexit()\n"
        if rendered.count(tail) != 1 or not rendered.endswith(tail):
            raise ValueError("CDF query lacks a unique bounded output/exit tail")
        cells = re.search(rb'foreach\(cellName list\("([^"\r\n]+)" "([^"\r\n]+)"\)', original)
        if cells is None or original.count(b"foreach(cellName list(") != 1:
            raise ValueError("CDF query lacks a unique existing diagnostic cell pair")
        form_cell = b'formCellName="' + cells[2] + b'"\n'
        rendered = rendered[:-len(tail)] + form_cell + _FORM_PROBE + tail
    return rendered


def run_virtuoso_cdf_readonly(
    config_path: Path, output_dir: Path, *, source: Path, expected_sha256: str,
    form_probe: bool = False,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    if not _LAUNCHER.is_file() or _LAUNCHER.is_symlink():
        raise ValueError("checked-in GUI launcher is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before CDF read-only probe")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("configured Xvfb is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-f", xvfb]).ok or not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"cdf_gui_read_{uuid4().hex[:12]}")
    report_name = "cdf_readonly_report.txt"
    script = _render_readonly_script(
        source, expected_sha256, f"{remote_dir}/{report_name}", form_probe=form_probe,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "source_readonly.ocn").write_bytes(source.read_bytes())
    (output_dir / "virtuoso_gui_smoke.il").write_bytes(script)
    shutil.copy2(_LAUNCHER, output_dir / _LAUNCHER.name)
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "host_available_gib_before": available,
        "source_sha256": expected_sha256,
        "form_probe_requested": form_probe,
        "rendered_sha256": hashlib.sha256(script).hexdigest(),
        "launcher_sha256": hashlib.sha256(_LAUNCHER.read_bytes()).hexdigest(),
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
    downloads = {
        name: runner.download(f"{remote_dir}/{name}", output_dir / name).ok
        for name in (*_LOGS, report_name)
    }
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("gui_cdf_readonly_failed", result.returncode)
    if not (output_dir / report_name).read_bytes():
        return finish("empty_cdf_report", result.returncode)
    log = (output_dir / "virtuoso.log").read_text(encoding="utf-8", errors="replace")
    if (
        "Virtuoso has launched" not in log
        or re.search(r"(?m)^\\i exit\(\)\s*$", log) is None
        or re.search(r"(?m)^\\e \*Error\*", log) is not None
    ):
        return finish("replay_incomplete", result.returncode)
    if form_probe:
        report = (output_dir / report_name).read_text(encoding="utf-8", errors="replace")
        if report.count("form_probe_end=t") != 1 or report.count("form_window=") != 1:
            return finish("form_probe_incomplete", result.returncode)
        status["form_window_opened"] = "form_window=t" in report
        status["form_object_observed"] = "form_object=t" in report
        if not status["form_window_opened"] or report.count("form_window_cv=") != 1:
            return finish("form_window_unavailable", result.returncode)
        if report.count("form_object=") != 1:
            return finish("form_not_observed", result.returncode)
        return finish("gui_form_readonly_completed", result.returncode)
    return finish("gui_cdf_readonly_completed", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fixed private CDF query in full Virtuoso/Xvfb")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_cdf_readonly")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--form-probe", action="store_true", help="open one read-only instance property form")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_cdf_readonly(
        args.config, output_dir, source=args.source, expected_sha256=args.source_sha256,
        form_probe=args.form_probe,
    )
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] in {"gui_cdf_readonly_completed", "gui_form_readonly_completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
