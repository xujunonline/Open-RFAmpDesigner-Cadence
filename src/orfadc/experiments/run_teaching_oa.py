from __future__ import annotations

import argparse
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_oa import _REQUIRED, audit_teaching_oa
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.extract_ocean_oa import extract_ocean_oa
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ROOT = Path(__file__).resolve().parents[3]
_PUBLIC_FILES = {
    "create_script": (_ROOT / "circuit/ocean/create_teaching_mos1_oa.ocn", "create_schematic.ocn"),
    "run_script": (_ROOT / "circuit/ocean/run_teaching_mos1_oa.ocn", "run_ocean.ocn"),
    "export_script": (_ROOT / "circuit/ocean/export_teaching_mos1_oa.ocn", "export_ocean.ocn"),
    "public_model": (_ROOT / "circuit/spectre/teaching_mos1_model.scs", "teaching_mos1_model.scs"),
}
_CREATE_SCRIPTS = {
    "flat": _PUBLIC_FILES["create_script"][0],
    "inductive": _ROOT / "circuit/ocean/create_teaching_inductive_mos1_oa.ocn",
    "damped": _ROOT / "circuit/ocean/create_teaching_inductive_mos1_oa.ocn",
    "cascode": _ROOT / "circuit/ocean/create_teaching_inductive_mos1_oa.ocn",
}
_REMOTE_SCRIPTS = (
    ("create_teaching_mos1_oa.ocn", "ocean_create.log", "ocean_create_stdout.log", "ocean_create_stderr.log"),
    ("run_teaching_mos1_oa.ocn", "ocean.log", "ocean_run_stdout.log", "ocean_run_stderr.log"),
    ("../export_teaching_mos1_oa.ocn", "ocean_export.log", "ocean_export_stdout.log", "ocean_export_stderr.log"),
)
_TRACE_NAMES = tuple(f"{signal}_{part}.txt" for signal in ("s11", "s21", "s12", "s22") for part in ("real", "imag")) + ("NF.txt", "NFmin.txt", "F.txt", "Fmin.txt")


def _remote_context(path: str) -> str:
    if not re.fullmatch(r"/[A-Za-z0-9._/+-]+", path) or ".." in PurePosixPath(path).parts:
        raise ValueError("schematic context must be a simple absolute remote path")
    return path


def run_teaching_oa(
    config_path: Path, output_dir: Path, *, schematic_context: str,
    topology: str = "flat", vcas_v: float = 0.95,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    context = _remote_context(schematic_context)
    if topology not in _CREATE_SCRIPTS:
        raise ValueError("unsupported teaching OA topology")
    if type(vcas_v) not in {int, float} or not math.isfinite(vcas_v) or not 0.8 <= vcas_v <= 1.1:
        raise ValueError("teaching OA VCAS must be finite and within 0.8..1.1 V")
    if topology != "cascode" and vcas_v != 0.95:
        raise ValueError("teaching OA VCAS only applies to cascode")
    sources = {**_PUBLIC_FILES, "create_script": (_CREATE_SCRIPTS[topology], "create_schematic.ocn")}
    for source, _ in sources.values():
        if not source.is_file() or source.is_symlink():
            raise ValueError("a checked-in teaching OA input is missing or symlinked")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before teaching OA simulation")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    token = uuid4().hex[:12]
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"teach_oa_{token}")
    cell = f"common_source_flat_tb_{token}"
    lib_dir = f"{remote_dir}/orfadc_teaching_mos1"
    copied = {}
    for key, (source, name) in sources.items():
        shutil.copy2(source, output_dir / name)
        copied[key] = name
    base = {
        "schema_version": 1, "status": "unknown", "simulation_status": "unknown",
        "circuit_class": "teaching_mos1_common_source", "not_lna_result": True,
        "spec_pass": None, "run_id": output_dir.name, "model_kind": "teaching_model",
        "analysis": ["dc", "sp", "noise"], "host_available_gib_before": available,
        "teaching_topology": topology,
    }
    if topology == "cascode":
        base["teaching_vcas_v"] = vcas_v

    def present() -> dict[str, str]:
        paths = {**_REQUIRED, **copied, "ocean_create_log": "ocean_create.log",
                 "ocean_export_log": "ocean_export.log"}
        if topology == "cascode" and (output_dir / "ocnprint/device_op.txt").is_file():
            paths["device_op"] = "ocnprint/device_op.txt"
        paths.update({name.rsplit(".", 1)[0]: name for _, _, stdout, stderr in _REMOTE_SCRIPTS for name in (stdout, stderr)})
        return {key: name for key, name in paths.items() if (output_dir / name).is_file()}

    def fail(status: str, *, simulation_status: str = "unknown", error: str | None = None) -> dict:
        payload = {**base, "status": status, "simulation_status": simulation_status}
        if error:
            payload["error"] = error
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        write_evidence_manifest(output_dir, present())
        return payload

    def fetch(remote: str, relative: str) -> bool:
        return runner.download(remote, output_dir / relative).ok

    if not runner.ensure_remote_dir(remote_dir).ok:
        return fail("mkdir_failed")
    for source, _ in sources.values():
        if not runner.upload(source, f"{remote_dir}/{source.name}").ok:
            return fail("upload_failed", error=source.name)

    env = ["env", f"ORFADC_TEACHING_LIB_DIR={lib_dir}", f"ORFADC_TEACHING_CELL={cell}"]
    if runner.config.xvfb_path:
        env.append(f"CDS_XVFB_PATH={runner.config.xvfb_path}")
    if runner.config.display:
        env.append(f"DISPLAY={runner.config.display}")
    if runner.config.xauthority:
        env.append(f"XAUTHORITY={runner.config.xauthority}")

    def ocean(script: str, log: str, stdout: str, stderr: str, *, cwd: str, extra_env: tuple[str, ...] = ()) -> bool:
        result = runner.run_remote(
            [*env, *extra_env, runner.config.ocean_bin, "-nograph", "-restore", script,
             "-log", f"{remote_dir}/{log}"], cwd=cwd, timeout_seconds=180,
        )
        (output_dir / stdout).write_text(result.stdout, encoding="utf-8")
        (output_dir / stderr).write_text(result.stderr, encoding="utf-8")
        downloaded = fetch(f"{remote_dir}/{log}", log)
        return result.ok and downloaded

    create_step = (_CREATE_SCRIPTS[topology].name, *_REMOTE_SCRIPTS[0][1:])
    damped_env = ("ORFADC_TEACHING_DAMPED=1",) if topology in {"damped", "cascode"} else ()
    topology_env = (*damped_env, *(
        ("ORFADC_TEACHING_CASCODE=1", f"ORFADC_TEACHING_VCAS={vcas_v:.17g}")
        if topology == "cascode" else ()
    ))
    if not ocean(*create_step, cwd=remote_dir,
                 extra_env=(f"ORFADC_SCHEMATIC_CONTEXT={context}", *topology_env)):
        return fail("schematic_creation_failed", simulation_status="failed")
    if not fetch(f"{remote_dir}/create_teaching_flat_tb_report.txt", "schematic_check.txt"):
        return fail("schematic_report_missing")
    check = (output_dir / "schematic_check.txt").read_text(encoding="utf-8")
    if "check_return=(0 0)" not in check or "save_return=t" not in check:
        return fail("schematic_check_failed", simulation_status="failed")
    if not fetch(f"{lib_dir}/{cell}/schematic/sch.oa", "oa_view/sch.oa"):
        return fail("oa_view_download_failed")

    if not ocean(*_REMOTE_SCRIPTS[1], cwd=remote_dir, extra_env=damped_env):
        fetch(f"{remote_dir}/results/psf/spectre.out", "spectre.out")
        return fail("ocean_simulation_failed", simulation_status="failed")
    if not fetch(f"{remote_dir}/teaching_flat_tb_run_report.txt", "ocean_run_report.txt"):
        return fail("ocean_run_report_missing")
    run_report = (output_dir / "ocean_run_report.txt").read_text(encoding="utf-8").strip()
    if run_report != f'run_result="{remote_dir}/results"':
        return fail("ocean_run_result_mismatch")
    if not fetch(f"{remote_dir}/results/psf/spectre.out", "spectre.out"):
        return fail("spectre_log_missing")
    spectre_log = (output_dir / "spectre.out").read_text(encoding="utf-8")
    netlist_match = re.search(r"^Reading file:\s+(\S+/input\.scs)$", spectre_log, re.MULTILINE)
    if netlist_match is None or not re.search(r"spectre completes with 0 errors,\s*0 warnings", spectre_log):
        return fail("spectre_log_unclean", simulation_status="failed")
    netlist_remote = netlist_match[1]
    netlist_dir = str(PurePosixPath(netlist_remote).parent)
    if not fetch(netlist_remote, "netlist.scs") or not fetch(f"{netlist_dir}/ade_e.scs", "ade_e.scs"):
        return fail("netlist_download_failed")
    for name in ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp"):
        if not fetch(f"{remote_dir}/results/psf/{name}", name):
            return fail("raw_download_failed", error=name)

    export_dir = f"{remote_dir}/ocnprint"
    if not runner.ensure_remote_dir(export_dir).ok:
        return fail("export_directory_failed")
    export_env = (f"ORFADC_TEACHING_RESULTS_PSF={remote_dir}/results/psf",)
    if topology == "cascode":
        export_env = (*export_env, "ORFADC_TEACHING_CASCODE=1")
    if not ocean(*_REMOTE_SCRIPTS[2], cwd=export_dir, extra_env=export_env):
        return fail("ocean_export_failed")
    export_report = f"{export_dir}/teaching_flat_tb_export_report.txt"
    for remote, relative in ((export_report, "ocean_export_report.txt"),
                             (export_report, "ocnprint/report.txt")):
        if not fetch(remote, relative):
            return fail("ocean_export_report_missing")
    for name in _TRACE_NAMES:
        if not fetch(f"{export_dir}/{name}", f"ocnprint/{name}"):
            return fail("trace_download_failed", error=name)
    if topology == "cascode" and not fetch(f"{export_dir}/device_op.txt", "ocnprint/device_op.txt"):
        return fail("device_op_download_failed")
    try:
        rows, payload = extract_ocean_oa(
            output_dir / "ocnprint", ocean_log=output_dir / "ocean.log",
            spectre_log=output_dir / "spectre.out", run_id=output_dir.name,
            supply_voltage_v=1.2, low_ghz=8.0, high_ghz=12.0, teaching_model=True,
            teaching_topology=topology,
            ocn_precision_digits=15,
        )
        payload["host_available_gib_before"] = available
        if topology == "cascode":
            payload["oa_device_op_exported"] = True
            payload["teaching_vcas_v"] = vcas_v
        write_active_oa_results(output_dir, rows, payload)
        write_evidence_manifest(output_dir, present())
        audit_teaching_oa(output_dir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        if (output_dir / "metrics.json").exists():
            raise RuntimeError("teaching OA audit failed; retained raw archive") from exc
        return fail("result_parse_failed", error=type(exc).__name__)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public MOS1 Virtuoso/OCEAN teaching cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_oa")
    parser.add_argument("--schematic-context", required=True, help="absolute remote schematic.cxt path")
    parser.add_argument("--topology", choices=tuple(_CREATE_SCRIPTS), default="flat")
    parser.add_argument("--vcas-v", type=float, default=0.95)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_oa(
            args.config, output_dir, schematic_context=args.schematic_context,
            topology=args.topology, vcas_v=args.vcas_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0 if payload["status"] == "ok_with_warnings" else 1


if __name__ == "__main__":
    raise SystemExit(main())
