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
from orfadc.experiments.run_virtuoso_cdf_form_variant import _read_fixed_private
from orfadc.experiments.run_virtuoso_callback_netlist import _callback_context
from orfadc.experiments.run_virtuoso_form_readback import _context


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_NAME = "run_same_condition.ocn"
_REPORT_LINE = re.compile(rb'^reportPort=outfile\("[^"\r\n]+" "w"\)\r?\n', re.MULTILINE)
_DESIGN = re.compile(rb'(?m)^design\(libName "([^"\r\n]+)" "schematic"\)\r?$')
_RESULTS = re.compile(rb'(?m)^resultsDir\("[^"\r\n]+"\)\r?$')
_READING_FILE = re.compile(r"(?m)^Reading file:\s+(/[A-Za-z0-9._/+-]+/input\.scs)$")


def _render(source: bytes, *, cell: str, report_path: str, results_path: str) -> tuple[bytes, str]:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", cell):
        raise ValueError("Spectre diagnostic cell name is unsafe")
    for path in (report_path, results_path):
        if not re.fullmatch(r"/[A-Za-z0-9._/+-]+", path):
            raise ValueError("Spectre diagnostic result path is unsafe")
    match = _DESIGN.search(source)
    if match is None or len(_DESIGN.findall(source)) != 1 or len(_RESULTS.findall(source)) != 1:
        raise ValueError("fixed OCEAN source lacks a unique design/results assignment")
    baseline_cell = match[1].decode("ascii")
    if len(_REPORT_LINE.findall(source)) != 1 or _REPORT_LINE.findall(source)[0] != source.splitlines(keepends=True)[0]:
        raise ValueError("fixed OCEAN source lacks its report destination")
    rendered = _REPORT_LINE.sub(
        lambda _: f'reportPort=outfile("{report_path}" "w")\n'.encode("ascii"), source, count=1,
    )
    rendered = _DESIGN.sub(
        lambda _: f'design(libName "{cell}" "schematic")'.encode("ascii"), rendered, count=1,
    )
    rendered = _RESULTS.sub(
        lambda _: f'resultsDir("{results_path}")'.encode("ascii"), rendered, count=1,
    )
    if b"run()" not in rendered or b"analysis('sp" not in rendered or b"analysis('dc" not in rendered:
        raise ValueError("fixed OCEAN source lacks DC/SP-noise analysis")
    return rendered, baseline_cell


def run_virtuoso_form_spectre(
    config_path: Path, output_dir: Path, *, form_run: Path,
    source_path: Path, source_sha256: str, target: str,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    if target not in {"baseline", "form", "callback"}:
        raise ValueError("Spectre diagnostic target must be baseline, form or callback")
    source = _read_fixed_private(source_path, source_sha256)
    if target == "callback":
        lib_name, lib_path, form_cell = _callback_context(form_run)
    else:
        lib_name, lib_path, form_cell, _ = _context(form_run)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before Spectre diagnostic")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"form_spectre_{uuid4().hex[:12]}")
    initial, baseline_cell = _render(
        source, cell=form_cell if target != "baseline" else _DESIGN.search(source)[1].decode("ascii"),
        report_path=f"{remote_dir}/run_report.txt", results_path=f"{remote_dir}/results",
    )
    cell = form_cell if target != "baseline" else baseline_cell
    library = re.search(rb'(?m)^libPath="([^"\r\n]+)"\r?$', source)
    if library is None or library[1].decode("ascii") != lib_path:
        raise ValueError("fixed OCEAN source uses another user library")
    lib = re.search(rb'(?m)^libName="([^"\r\n]+)"\r?$', source)
    if lib is None or lib[1].decode("ascii") != lib_name:
        raise ValueError("fixed OCEAN source uses another library name")
    owned = runner.run_shell(
        f"test -d {shlex.quote(lib_path)} && test -w {shlex.quote(lib_path)} "
        f"&& test ! -L {shlex.quote(lib_path)} "
        f"&& test \"$(stat -c %U {shlex.quote(lib_path)})\" = \"$(id -un)\"",
        timeout_seconds=30,
    )
    if not owned.ok:
        raise ValueError("Spectre diagnostic library is not an owned user library")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "source_ocean.ocn").write_bytes(source)
    (output_dir / _SCRIPT_NAME).write_bytes(initial)
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "target": target,
        ("source_callback_run" if target == "callback" else "source_form_run"): form_run.name,
        "source_cell": cell,
        "host_available_gib_before": available,
        "source_sha256": source_sha256,
        "rendered_sha256": hashlib.sha256(initial).hexdigest(),
        "analysis": ["dc", "sp", "noise"],
        "pdk_write": False, "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    oa_remote = f"{lib_path}/{cell}/schematic/sch.oa"
    if not runner.download(oa_remote, output_dir / "oa_before.oa").ok:
        return finish("source_oa_missing")
    if not runner.upload(output_dir / _SCRIPT_NAME, f"{remote_dir}/{_SCRIPT_NAME}").ok:
        return finish("upload_failed")
    env = ["env"]
    if runner.config.xvfb_path:
        env.append(f"CDS_XVFB_PATH={runner.config.xvfb_path}")
    result = runner.run_remote(
        [*env, runner.config.ocean_bin, "-nograph", "-restore", _SCRIPT_NAME,
         "-log", f"{remote_dir}/ocean.log"], cwd=remote_dir, timeout_seconds=300,
    )
    (output_dir / "ocean.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "ocean.stderr").write_text(result.stderr, encoding="utf-8")
    paths = {
        "ocean.log": f"{remote_dir}/ocean.log",
        "run_report.txt": f"{remote_dir}/run_report.txt",
        "spectre.out": f"{remote_dir}/results/psf/spectre.out",
        "dcOp.dc": f"{remote_dir}/results/psf/dcOp.dc",
        "sp.sp": f"{remote_dir}/results/psf/sp.sp",
        "sp.noise.sp": f"{remote_dir}/results/psf/sp.noise.sp",
        "oa_after.oa": oa_remote,
    }
    downloads = {name: runner.download(remote, output_dir / name).ok for name, remote in paths.items()}
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("spectre_archive_incomplete", result.returncode)
    before = (output_dir / "oa_before.oa").read_bytes()
    after = (output_dir / "oa_after.oa").read_bytes()
    if not before or before != after:
        return finish("source_oa_changed", result.returncode)
    status["oa_sha256"] = hashlib.sha256(before).hexdigest()
    ocean_log = (output_dir / "ocean.log").read_text(encoding="utf-8", errors="replace")
    spectre_log = (output_dir / "spectre.out").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", ocean_log):
        return finish("ocean_error", result.returncode)
    if not re.search(r"spectre completes with 0 errors,", spectre_log):
        return finish("spectre_error", result.returncode)
    match = _READING_FILE.search(spectre_log)
    if match is None:
        return finish("spectre_source_unbound", result.returncode)
    input_path = match[1]
    downloads["input.scs"] = runner.download(input_path, output_dir / "input.scs").ok
    downloads["ade_e.scs"] = runner.download(
        str(PurePosixPath(input_path).parent / "ade_e.scs"), output_dir / "ade_e.scs",
    ).ok
    if not downloads["input.scs"] or not downloads["ade_e.scs"]:
        return finish("spectre_netlist_missing", result.returncode)
    status["netlist_sha256"] = hashlib.sha256((output_dir / "input.scs").read_bytes()).hexdigest()
    status["spectre_warning_count"] = len(re.findall(r"(?m)^Warning from spectre", spectre_log))
    return finish("spectre_raw_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Same-condition private v2/form Spectre DC/SP-noise diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--form-run", type=Path)
    source_group.add_argument("--callback-run", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--target", choices=("baseline", "form", "callback"), required=True)
    args = parser.parse_args()
    if (args.callback_run is None) != (args.target != "callback"):
        parser.error("callback target requires --callback-run; baseline/form require --form-run")
    output_root = args.output_root or _PRIVATE_ROOT / (
        "virtuoso_callback_spectre" if args.target == "callback" else "virtuoso_form_spectre"
    )
    output_dir = output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_form_spectre(
        args.config, output_dir, form_run=args.callback_run or args.form_run,
        source_path=args.source, source_sha256=args.source_sha256, target=args.target,
    )
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "spectre_raw_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
