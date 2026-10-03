from __future__ import annotations

import argparse
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage
from orfadc.experiments.audit_teaching_three_stage_oa import (
    _ARTIFACTS, _SCRIPTS, audit_teaching_three_stage_oa, extract_teaching_three_stage_oa,
)
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)
from orfadc.experiments.run_teaching_oa import _remote_context
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL
from orfadc.metric_contract import validate_metrics_payload


_DEFAULT_DIRECT = _PRIVATE_ROOT / "teaching_three_stage/probe_7eecbf34a74a"
_EXPORT_NAMES = (
    "teaching_three_stage_export_report.txt", "device_op.txt",
    *(f"{signal}_{part}.txt" for signal in ("s11", "s21", "s12", "s22") for part in ("real", "imag")),
    *(f"{signal}.txt" for signal in ("NF", "NFmin", "F", "Fmin")),
)


def run_teaching_three_stage_oa(
    config_path: Path, output_dir: Path, *, schematic_context: str,
    direct_dir: Path = _DEFAULT_DIRECT, runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    context = _remote_context(schematic_context)
    for source in (*_SCRIPTS.values(), PUBLIC_MODEL):
        if not source.is_file() or source.is_symlink():
            raise ValueError("three-stage public OA input is missing or symlinked")
    audit_teaching_three_stage(direct_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before three-stage OA simulation")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    probe = runner.probe(tools=("ocean", "spectre"))
    guest = runner.run_remote(["pgrep", "-x", "vmtoolsd"], timeout_seconds=20)
    if probe["status"] != "ok" or any(not probe["tools"][name]["found"] for name in ("ocean", "spectre")) or not guest.ok:
        raise RuntimeError("SSH, Cadence, or guest Tools preflight failed")

    output_dir.mkdir(parents=True, exist_ok=False)
    token = uuid4().hex[:12]
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"teach3_oa_{token}")
    cell = f"three_stage_tb_{token}"
    sources = (*_SCRIPTS.values(), PUBLIC_MODEL)
    for source in sources:
        shutil.copy2(source, output_dir / source.name)
    base = {
        "schema_version": 1, "status": "unknown", "simulation_status": "unknown",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": output_dir.name,
        "analysis": ["dc", "sp", "noise"], "host_available_gib_before": available,
    }

    def fail(status: str) -> dict:
        payload = {**base, "status": status}
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        present = {"metrics": "metrics.json"}
        present.update({source.stem.replace(".", "_"): source.name for source in sources})
        for key, relative in _ARTIFACTS.items():
            if key != "metrics" and (output_dir / relative).is_file() and relative not in present.values():
                present[key] = relative
        write_evidence_manifest(output_dir, present)
        return payload

    def fetch(remote: str, relative: str) -> bool:
        return runner.download(remote, output_dir / relative).ok

    if not runner.ensure_remote_dir(remote_dir).ok:
        return fail("remote_directory_failed")
    for source in sources:
        if not runner.upload(source, f"{remote_dir}/{source.name}").ok:
            return fail("upload_failed")
    environment = ["env", f"ORFADC_TEACHING_LIB_DIR={remote_dir}/orfadc_teaching_mos1",
                   f"ORFADC_TEACHING_CELL={cell}"]
    for key, value in (("CDS_XVFB_PATH", runner.config.xvfb_path),
                       ("DISPLAY", runner.config.display), ("XAUTHORITY", runner.config.xauthority)):
        if value:
            environment.append(f"{key}={value}")

    def ocean(script: str, log: str, prefix: str, *, cwd: str, extra: tuple[str, ...] = ()) -> bool:
        result = runner.run_remote(
            [*environment, *extra, runner.config.ocean_bin, "-nograph", "-restore", script,
             "-log", f"{remote_dir}/{log}"], cwd=cwd, timeout_seconds=240,
        )
        (output_dir / f"{prefix}_stdout.log").write_text(result.stdout, encoding="utf-8")
        (output_dir / f"{prefix}_stderr.log").write_text(result.stderr, encoding="utf-8")
        downloaded = fetch(f"{remote_dir}/{log}", log)
        return result.ok and downloaded

    if not ocean(_SCRIPTS["create"].name, "ocean_create.log", "create", cwd=remote_dir,
                 extra=(f"ORFADC_SCHEMATIC_CONTEXT={context}",)):
        return fail("schematic_creation_failed")
    if not fetch(f"{remote_dir}/create_teaching_three_stage_report.txt", "schematic_check.txt"):
        return fail("schematic_report_missing")
    check = (output_dir / "schematic_check.txt").read_text(encoding="utf-8")
    if "check_return=(0 0)" not in check or "save_return=t instances=64 nets=26" not in check:
        return fail("schematic_check_failed")
    if not fetch(f"{remote_dir}/orfadc_teaching_mos1/{cell}/schematic/sch.oa", "sch.oa"):
        return fail("oa_view_missing")

    if not ocean(_SCRIPTS["run"].name, "ocean_run.log", "run", cwd=remote_dir,
                 extra=("ORFADC_TEACHING_DAMPED=1",)):
        fetch(f"{remote_dir}/results/psf/spectre.out", "spectre.out")
        return fail("ocean_simulation_failed")
    if not fetch(f"{remote_dir}/teaching_flat_tb_run_report.txt", "ocean_run_report.txt"):
        return fail("ocean_run_report_missing")
    if not fetch(f"{remote_dir}/results/psf/spectre.out", "spectre.out"):
        return fail("spectre_log_missing")
    spectre_log = (output_dir / "spectre.out").read_text(encoding="utf-8", errors="replace")
    netlist_match = re.search(r"^Reading file:\s+(\S+/input\.scs)$", spectre_log, re.MULTILINE)
    if netlist_match is None or not re.search(r"spectre completes with 0 errors,\s*0 warnings", spectre_log):
        return fail("spectre_log_unclean")
    netlist_dir = str(PurePosixPath(netlist_match[1]).parent)
    if not fetch(netlist_match[1], "netlist.scs") or not fetch(f"{netlist_dir}/ade_e.scs", "ade_e.scs"):
        return fail("netlist_download_failed")
    for name in ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp"):
        if not fetch(f"{remote_dir}/results/psf/{name}", name):
            return fail("raw_download_failed")

    export_dir = f"{remote_dir}/ocnprint"
    if not runner.ensure_remote_dir(export_dir).ok:
        return fail("export_directory_failed")
    if not ocean(f"../{_SCRIPTS['export'].name}", "ocean_export.log", "export", cwd=export_dir,
                 extra=(f"ORFADC_TEACHING_RESULTS_PSF={remote_dir}/results/psf",)):
        return fail("ocean_export_failed")
    for name in _EXPORT_NAMES:
        if not fetch(f"{export_dir}/{name}", f"ocnprint/{name}"):
            return fail("trace_download_failed")
    for source in sources:
        if not fetch(f"{remote_dir}/{source.name}", f"remote_{source.name}"):
            return fail("remote_input_download_failed")
    try:
        rows, payload = extract_teaching_three_stage_oa(output_dir, direct_dir)
        write_active_oa_results(output_dir, rows, payload)
        write_evidence_manifest(output_dir, _ARTIFACTS)
        audit_teaching_three_stage_oa(output_dir, direct_dir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        if (output_dir / "metrics.json").exists():
            raise RuntimeError("three-stage OA audit failed; raw archive retained") from exc
        return fail(f"result_parse_{type(exc).__name__}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public MOS1 three-stage Virtuoso/OCEAN teaching cell")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_oa")
    parser.add_argument("--schematic-context", required=True)
    parser.add_argument("--direct-run", type=Path, default=_DEFAULT_DIRECT)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_three_stage_oa(
            args.config, output_dir, schematic_context=args.schematic_context,
            direct_dir=args.direct_run,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0 if payload["status"] == "ok_with_warnings" else 1


if __name__ == "__main__":
    raise SystemExit(main())
