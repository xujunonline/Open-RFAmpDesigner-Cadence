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
from orfadc.experiments.run_virtuoso_cdf_readonly import _LAUNCHER, _LOGS, _REPORT_LINE


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")
_CELL = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_VALUE = re.compile(r"[A-Za-z0-9.+-]{1,40}\Z")
_SETTINGS_MARKER = b"foreach(setting list("


def _read_fixed_private(path: Path, sha256: str) -> bytes:
    _require_private_path(path)
    if not _HASH.fullmatch(sha256) or not path.is_file() or path.is_symlink():
        raise ValueError("a fixed private source and SHA-256 are required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("private source changed")
    return raw


def _target_width(reference: bytes) -> str:
    text = reference.decode("utf-8")
    default = re.search(r'(?m)^cdf name=Wfg default="([^"]+)" callback_present=t$', text)
    cells = re.split(r"(?m)^cell=", text)[1:]
    if default is None or len(cells) != 2:
        raise ValueError("CDF reference lacks the expected default and two diagnostic cells")
    values = []
    for cell in cells:
        match = re.search(r'(?m)^  instance name=Wfg value="([^"]+)"$', cell)
        if match is None:
            raise ValueError("CDF reference lacks a prior per-finger width")
        values.append(match[1])
    target = next((value for value in reversed(values) if value != default[1]), None)
    if target is None or not _VALUE.fullmatch(target):
        raise ValueError("prior diagnostic widths offer no safe single-field change")
    return target


def _copied_cell_target(reference: bytes) -> str:
    text = reference.decode("utf-8")
    cells = re.split(r"(?m)^cell=", text)[1:]
    if len(cells) != 2:
        raise ValueError("CDF reference needs exactly two prior diagnostic cells")
    values = []
    for cell in cells:
        match = re.search(r'(?m)^  instance name=Wfg value="([^"]+)"$', cell)
        if match is None:
            raise ValueError("CDF reference lacks the prior instance width")
        values.append(match[1])
    if values[0] == values[1] or not all(_VALUE.fullmatch(value) for value in values):
        raise ValueError("prior cells do not establish a safe width-only contrast")
    return values[0]


def _render_copied_form_variant(
    source: bytes, *, report_path: str, cell_name: str, target_wfg: str,
) -> tuple[bytes, str]:
    if not _REMOTE_PATH.fullmatch(report_path) or not _CELL.fullmatch(cell_name):
        raise ValueError("private form probe output path or cell name is unsafe")
    if not _VALUE.fullmatch(target_wfg) or b"vfoSetParam" in source or b"dbSave(" in source:
        raise ValueError("CDF copy source or target is unsafe")
    fields = {}
    for key in (b"libName", b"libPath"):
        match = re.search(rb'(?m)^' + key + rb'="([^"\r\n]+)"\r?$', source)
        if match is None or source.count(key + b"=") != 1:
            raise ValueError("CDF source lacks one user-library registration")
        fields[key.decode("ascii")] = match[1].decode("ascii")
    library_path = fields["libPath"]
    if not _REMOTE_PATH.fullmatch(library_path):
        raise ValueError("CDF user library path is unsafe")
    pair = re.search(rb'foreach\(cellName list\("([^"\r\n]+)" "([^"\r\n]+)"\)', source)
    instance = re.search(rb'when\(inst~>name=="([^"\r\n]+)" mos=inst\)', source)
    if pair is None or instance is None or source.count(b"foreach(cellName list(") != 1:
        raise ValueError("CDF query does not bind the prior cell and its MOS instance")
    source_cell = pair[2].decode("ascii")
    mos_name = instance[1].decode("ascii")
    if not _CELL.fullmatch(source_cell) or not _CELL.fullmatch(mos_name):
        raise ValueError("prior schematic identifier is unsafe")
    script = f'''reportPort=outfile("{report_path}" "w")
libName="{fields["libName"]}"
libPath="{library_path}"
sourceCellName="{source_cell}"
cellName="{cell_name}"
mosName="{mos_name}"
libObj=ddGetObj(libName)
unless(libObj libObj=ddCreateLib(libName libPath))
unless(libObj error("user library registration failed"))
oldCv=dbOpenCellViewByType(libName cellName "schematic" "schematic" "r")
when(oldCv
  dbClose(oldCv)
  error("new form variant cell already exists")
)
sourceCv=dbOpenCellViewByType(libName sourceCellName "schematic" "schematic" "r")
unless(sourceCv error("known-good source schematic is unavailable"))
copyCv=dbCopyCellView(sourceCv libName cellName "schematic")
unless(copyCv error("schematic copy failed"))
dbClose(sourceCv)
fprintf(reportPort "copy_mode=%L\\n" copyCv~>mode)
fprintf(reportPort "copy_save=%L\\n" dbSave(copyCv))
dbClose(copyCv)
formWindow=geOpen(?lib libName ?cell cellName ?view "schematic" ?mode "a")
unless(formWindow error("new form diagnostic window did not open"))
formCv=geGetWindowCellView()
unless(formCv error("new form cellview is unavailable"))
mos=dbFindAnyInstByName(formCv mosName)
unless(mos error("copied MOS instance is unavailable"))
geSelectFig(mos)
schHiObjectProperty()
unless(boundp('schObjPropForm) && schObjPropForm && schObjPropForm~>Wfg
  error("per-finger width field is unavailable"))
fprintf(reportPort "form_field_before=%L\\n" schObjPropForm~>Wfg~>value)
targetValue="{target_wfg}"
schObjPropForm~>Wfg~>value=targetValue
fprintf(reportPort "form_field_assigned=%L\\n" schObjPropForm~>Wfg~>value)
printf("ORFADC_FORM_APPLY_ATTEMPT\\n")
fprintf(reportPort "form_done_return=%L\\n" hiFormDone(schObjPropForm))
printf("ORFADC_FORM_APPLY_RETURNED\\n")
mos=dbFindAnyInstByName(formCv mosName)
cdfAfter=cdfGetInstCDF(mos)
foreach(param cdfAfter~>parameters
  when(member(param~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "after_cdf name=%s value=%L\\n" param~>name param~>value)
  )
)
foreach(prop mos~>prop
  when(member(prop~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "after_instance name=%s value=%L\\n" prop~>name prop~>value)
  )
)
fprintf(reportPort "check_return=%L\\n" schCheck(formCv))
fprintf(reportPort "save_return=%L\\n" dbSave(formCv))
fprintf(reportPort "form_probe_end=t\\n")
close(reportPort)
exit()
'''.encode("ascii")
    return script, library_path


def _render_form_variant(
    source: bytes, *, report_path: str, cell_name: str, target_wfg: str,
) -> tuple[bytes, str]:
    if not _REMOTE_PATH.fullmatch(report_path) or not _CELL.fullmatch(cell_name):
        raise ValueError("private form probe output path or cell name is unsafe")
    if not _VALUE.fullmatch(target_wfg):
        raise ValueError("form probe target has unsupported characters")
    if source.count(_SETTINGS_MARKER) != 1:
        raise ValueError("CDF creation source lacks a unique settings block")
    head = source.split(_SETTINGS_MARKER, 1)[0]
    if b"vfoSetParam" in head or b"dbSave(" in head:
        raise ValueError("CDF creation prelude contains an unexpected write path")
    matches = _REPORT_LINE.findall(head)
    if len(matches) != 1 or matches[0] != head.splitlines(keepends=True)[0]:
        raise ValueError("CDF creation source lacks a unique report output")
    head, count = _REPORT_LINE.subn(
        lambda _: f'reportPort=outfile("{report_path}" "w")\n'.encode("ascii"), head, count=1,
    )
    assert count == 1
    head, count = re.subn(
        rb'(?m)^cellName="[^"\r\n]+"\r?$',
        lambda _: f'cellName="{cell_name}"'.encode("ascii"), head, count=1,
    )
    if count != 1 or head.count(b"cellName=") != 1:
        raise ValueError("CDF creation source lacks a unique cell assignment")
    library = re.search(rb'(?m)^libPath="([^"\r\n]+)"\r?$', head)
    if library is None:
        raise ValueError("CDF creation source lacks its user library path")
    library_path = library[1].decode("ascii")
    if not _REMOTE_PATH.fullmatch(library_path):
        raise ValueError("CDF user library path is unsafe")
    tail = f'''
fprintf(reportPort "initial_save=%L\\n" dbSave(cv))
dbClose(cv)
formWindow=geOpen(?lib libName ?cell cellName ?view "schematic" ?mode "a")
unless(formWindow error("new form diagnostic window did not open"))
formCv=geGetWindowCellView()
unless(formCv && length(formCv~>instances)==1 error("new cell does not contain one instance"))
mos=car(formCv~>instances)
geSelectFig(mos)
schHiObjectProperty()
unless(boundp('schObjPropForm) && schObjPropForm && schObjPropForm~>Wfg
  error("per-finger width field is unavailable"))
fprintf(reportPort "form_field_before=%L\\n" schObjPropForm~>Wfg~>value)
targetValue="{target_wfg}"
schObjPropForm~>Wfg~>value=targetValue
fprintf(reportPort "form_field_assigned=%L\\n" schObjPropForm~>Wfg~>value)
printf("ORFADC_FORM_APPLY_ATTEMPT\\n")
fprintf(reportPort "form_done_return=%L\\n" hiFormDone(schObjPropForm))
printf("ORFADC_FORM_APPLY_RETURNED\\n")
mos=car(formCv~>instances)
cdfAfter=cdfGetInstCDF(mos)
foreach(param cdfAfter~>parameters
  when(member(param~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "after_cdf name=%s value=%L\\n" param~>name param~>value)
  )
)
foreach(prop mos~>prop
  when(member(prop~>name list("Wfg" "w" "l" "nf" "fingers"))
    fprintf(reportPort "after_instance name=%s value=%L\\n" prop~>name prop~>value)
  )
)
fprintf(reportPort "check_return=%L\\n" schCheck(formCv))
fprintf(reportPort "save_return=%L\\n" geSave(formCv))
fprintf(reportPort "form_probe_end=t\\n")
close(reportPort)
exit()
'''.encode("ascii")
    return head + tail, library_path


def run_virtuoso_cdf_form_variant(
    config_path: Path, output_dir: Path, *, source_path: Path, source_sha256: str,
    reference_path: Path, reference_sha256: str, runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    source = _read_fixed_private(source_path, source_sha256)
    reference = _read_fixed_private(reference_path, reference_sha256)
    target = _copied_cell_target(reference)
    if not _LAUNCHER.is_file() or _LAUNCHER.is_symlink():
        raise ValueError("checked-in GUI launcher is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before CDF form edit")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("configured Xvfb is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-f", xvfb]).ok or not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    token = uuid4().hex[:12]
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"cdf_form_{token}")
    cell_name = f"cdf_form_{token}"
    script, library_path = _render_copied_form_variant(
        source, report_path=f"{remote_dir}/form_report.txt", cell_name=cell_name, target_wfg=target,
    )
    ownership = runner.run_shell(
        f"test -d {shlex.quote(library_path)} && test -w {shlex.quote(library_path)} "
        f"&& test ! -L {shlex.quote(library_path)} "
        f"&& test \"$(stat -c %U {shlex.quote(library_path)})\" = \"$(id -un)\"",
        timeout_seconds=30,
    )
    if not ownership.ok:
        raise ValueError("CDF source library is not an owned writable user library")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "source_copy.ocn").write_bytes(source)
    (output_dir / "reference_cdf.txt").write_bytes(reference)
    (output_dir / "virtuoso_gui_smoke.il").write_bytes(script)
    shutil.copy2(_LAUNCHER, output_dir / _LAUNCHER.name)
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "host_available_gib_before": available,
        "source_sha256": source_sha256,
        "reference_sha256": reference_sha256,
        "rendered_sha256": hashlib.sha256(script).hexdigest(),
        "launcher_sha256": hashlib.sha256(_LAUNCHER.read_bytes()).hexdigest(),
        "target_sha256": hashlib.sha256(target.encode("ascii")).hexdigest(),
        "user_cell_name": cell_name,
        "baseline_copy": True,
        "pdk_write": False, "user_oa_write": True, "not_lna_result": True,
        "cdf_callback_validated": False, "physical_qualification": False, "spec_pass": None,
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
        for name in (*_LOGS, "form_report.txt")
    }
    downloads["sch.oa"] = runner.download(
        f"{library_path}/{cell_name}/schematic/sch.oa", output_dir / "sch.oa",
    ).ok
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("form_variant_failed", result.returncode)
    log = (output_dir / "virtuoso.log").read_text(encoding="utf-8", errors="replace")
    report = (output_dir / "form_report.txt").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or "\\o ORFADC_FORM_APPLY_RETURNED" not in log:
        return finish("form_action_incomplete", result.returncode)
    if (
        "form_probe_end=t" not in report or "save_return=t" not in report
        or "copy_save=t" not in report or "check_return=(0 0)" not in report
    ):
        return finish("form_save_unconfirmed", result.returncode)
    return finish("form_action_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded single-field PDK form diagnostic in a new user cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_cdf_form_variant")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-sha256", required=True)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_cdf_form_variant(
        args.config, output_dir, source_path=args.source, source_sha256=args.source_sha256,
        reference_path=args.reference, reference_sha256=args.reference_sha256,
    )
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "form_action_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
