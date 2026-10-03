from __future__ import annotations

import argparse
import hashlib
import math
import re
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Callable

from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteCadenceConfig, RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.extract_active_oa import extract_active_oa, write_active_oa_results
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate, Spec


_PRIVATE_ROOT = Path(__file__).resolve().parents[3] / "results/runs"
_MINIMUM_HOST_FREE_GB = 2.66
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_BIAS_LINE = re.compile(
    r"^(VBIAS \([^\r\n)]+\) vsource dc=)[0-9.eE+-]+( type=dc)(?=\r?$)", re.MULTILINE
)
_LOAD_LINE = re.compile(
    r"^(RD \([^\r\n)]+\) resistor r=)[0-9.eE+-]+(?=\r?$)", re.MULTILINE
)
_SUPPLY_LINE = re.compile(
    r"^VDD \([^\r\n)]+\) vsource dc=([0-9.eE+-]+) type=dc(?=\r?$)", re.MULTILINE
)
_ADE_INCLUDE = re.compile(r'^include "ade_e\.scs"(?=\r?$)', re.MULTILINE)
_ARTIFACTS = {
    "metrics": "metrics.json", "candidate": "candidate.json", "netlist": "netlist.scs",
    "ade_companion": "ade_e.scs",
    "spectre_log": "spectre.log", "waveforms": "waveforms.csv",
    "dc_raw": "psf/dcOp.dc", "sp_raw": "psf/sp.sp", "noise_raw": "psf/sp.noise.sp",
    "op_raw": "psf/dcOpInfo.info", "stdout": "spectre.stdout.log",
    "stderr": "spectre.stderr.log",
}


def _require_private_path(path: Path) -> None:
    if not path.resolve().is_relative_to(_PRIVATE_ROOT.resolve()) or path.is_symlink():
        raise ValueError("active diagnostic files must stay under the private results/runs root")


def render_active_diagnostic_netlist(
    candidate: Candidate, template: Path, expected_sha256: str
) -> str:
    _require_private_path(template)
    if not _HASH_RE.fullmatch(expected_sha256):
        raise ValueError("expected template SHA-256 must be 64 lowercase hex characters")
    if not isinstance(candidate.active_params, dict) or set(candidate.active_params) != {"rd_ohm", "vbias_v"}:
        raise ValueError("diagnostic active candidate requires only rd_ohm and vbias_v")
    if candidate.passive_params or candidate.sim_result is not None:
        raise ValueError("diagnostic active candidate cannot contain passive parameters or results")
    rd = candidate.active_params["rd_ohm"]
    vbias = candidate.active_params["vbias_v"]
    if type(rd) not in {int, float} or not math.isfinite(rd) or not 50 <= rd <= 1000:
        raise ValueError("rd_ohm must be finite and in [50, 1000]")
    if type(vbias) not in {int, float} or not math.isfinite(vbias) or not 0.4 <= vbias <= 0.8:
        raise ValueError("vbias_v must be finite and in [0.4, 0.8]")
    raw = template.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("private OA netlist template hash changed")
    source = raw.decode("utf-8")
    rendered, bias_count = _BIAS_LINE.subn(lambda m: f"{m[1]}{vbias:.17g}{m[2]}", source)
    rendered, load_count = _LOAD_LINE.subn(lambda m: f"{m[1]}{rd:.17g}", rendered)
    if bias_count != 1 or load_count != 1:
        raise ValueError("OA netlist lacks unique expected bias/load lines")
    if (
        len(_SUPPLY_LINE.findall(rendered)) != 1
        or len(re.findall(r"^PORT1 \([^\r\n)]+\) port r=50 num=1\b", rendered, re.MULTILINE)) != 1
        or len(re.findall(r"^PORT2 \([^\r\n)]+\) port r=50 num=2\b", rendered, re.MULTILINE)) != 1
        or len(re.findall(r"^dcOp dc\b", rendered, re.MULTILINE)) != 1
        or len(re.findall(r"^sp sp ports=\[PORT1 PORT2\](?=\s|$)", rendered, re.MULTILINE)) != 1
        or "donoise=yes" not in rendered
    ):
        raise ValueError("OA diagnostic testbench structure is not the expected DC/SP-noise two-port")
    return rendered


def _read_ade_companion(template: Path, netlist: str) -> bytes | None:
    count = len(_ADE_INCLUDE.findall(netlist))
    if count == 0:
        return None
    if count != 1:
        raise ValueError("OA netlist must reference ade_e.scs exactly once")
    companion = template.with_name("ade_e.scs")
    _require_private_path(companion)
    if not companion.is_file():
        raise ValueError("OA netlist companion ade_e.scs is missing")
    data = companion.read_bytes()
    if not data:
        raise ValueError("OA netlist companion ade_e.scs is empty")
    return data


def _step(result: object) -> dict[str, int | bool]:
    return {"returncode": result.returncode, "ok": result.ok}


def _spectre_failure_code(run_dir: Path, returncode: int) -> str:
    logs = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for name in ("spectre.log", "spectre.stderr.log")
        if (path := run_dir / name).is_file()
    )
    license_related = bool(re.search(
        r"waiting for (?:a )?licen[sc]e|licen[sc]e (?:checkout failed|unavailable|wait)",
        logs, re.IGNORECASE,
    ))
    if returncode == 124:
        return "license_related_timeout" if license_related else "spectre_timeout"
    return "license_checkout_failed" if license_related else "spectre_error"


def run_active_diagnostic_candidate(
    config_path: Path,
    runs_root: Path,
    spec: Spec,
    candidate: Candidate,
    *,
    template: Path,
    template_sha256: str,
    run_id: str | None = None,
    remote_config: RemoteCadenceConfig | None = None,
    runner: RemoteRunner | None = None,
    minimum_host_free_gb: float = _MINIMUM_HOST_FREE_GB,
    memory_provider: Callable[[], float] = available_physical_memory_gb,
    preserve_uncertain_dispatch: bool = False,
) -> tuple[Path, dict]:
    """Evaluate only RD/VBIAS derivatives of an authorized OA smoke netlist."""
    _require_private_path(runs_root)
    netlist = render_active_diagnostic_netlist(candidate, template, template_sha256)
    companion_data = _read_ade_companion(template, netlist)
    if (type(minimum_host_free_gb) not in {int, float}
            or not math.isfinite(minimum_host_free_gb)
            or minimum_host_free_gb < _MINIMUM_HOST_FREE_GB):
        raise ValueError("minimum_host_free_gb cannot be below the accepted resource floor")
    available_gb = memory_provider()
    if type(available_gb) not in {int, float} or not math.isfinite(available_gb) or available_gb < 0:
        raise ValueError("host memory reading is unavailable or invalid")
    if available_gb < minimum_host_free_gb:
        raise ValueError("host memory below the configured preflight threshold")
    supply_voltage_v = float(_SUPPLY_LINE.search(netlist).group(1))
    if not math.isfinite(supply_voltage_v) or supply_voltage_v <= 0:
        raise ValueError("OA diagnostic supply voltage must be finite and positive")
    config = remote_config or load_remote_config(config_path)
    active_runner = runner or RemoteRunner(config)
    run_dir = reserve_candidate_run(runs_root, spec, candidate, run_id=run_id)
    (run_dir / "netlist.scs").write_bytes(netlist.encode("utf-8"))
    if companion_data is not None:
        (run_dir / "ade_e.scs").write_bytes(companion_data)
    context = {
        "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
        "timeout_seconds": config.command_timeout_seconds, "run_id": run_dir.name,
        "template_sha256": template_sha256,
    }
    remote_name = f"rf_active_{spec.id}_seed{candidate.seed}_{candidate.candidate_id}_{run_dir.name}"
    remote_dir = str(PurePosixPath(config.remote_root) / remote_name)
    status = "backend_error"
    failure_code = "backend_error"
    details: dict = {}
    try:
        mkdir = active_runner.ensure_remote_dir(remote_dir)
        details["mkdir"] = _step(mkdir)
        if not mkdir.ok:
            status, failure_code = "mkdir_failed", "remote_directory_failed"
        else:
            upload = active_runner.upload(run_dir / "netlist.scs", str(PurePosixPath(remote_dir) / "netlist.scs"))
            details["upload"] = _step(upload)
            companion_upload = None
            if upload.ok and companion_data is not None:
                companion_upload = active_runner.upload(
                    run_dir / "ade_e.scs", str(PurePosixPath(remote_dir) / "ade_e.scs")
                )
                details["companion_upload"] = _step(companion_upload)
            if not upload.ok or (companion_upload is not None and not companion_upload.ok):
                status, failure_code = "upload_failed", "upload_failed"
            else:
                try:
                    spectre = active_runner.run_remote(
                        [config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
                         "+log", "spectre.log", "netlist.scs"],
                        cwd=remote_dir,
                    )
                except Exception as exc:
                    if preserve_uncertain_dispatch:
                        write_json(run_dir / "candidate.json", candidate.to_dict())
                        raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain") from exc
                    raise
                if preserve_uncertain_dispatch and spectre.returncode in {124, 255}:
                    control = run_dir / "control_attempt"
                    control.mkdir(exist_ok=False)
                    (control / "spectre.stdout.log").write_text(spectre.stdout, encoding="utf-8")
                    (control / "spectre.stderr.log").write_text(spectre.stderr, encoding="utf-8")
                    write_json(control / "dispatch.json", {
                        "schema_version": 1, "run_id": run_dir.name,
                        "returncode": spectre.returncode, "status": "uncertain",
                    })
                    write_json(run_dir / "candidate.json", candidate.to_dict())
                    raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain")
                details["spectre"] = _step(spectre)
                (run_dir / "spectre.stdout.log").write_text(spectre.stdout, encoding="utf-8")
                (run_dir / "spectre.stderr.log").write_text(spectre.stderr, encoding="utf-8")
                files = ["spectre.log"]
                if spectre.ok:
                    files += ["psf/dcOp.dc", "psf/sp.sp", "psf/sp.noise.sp"]
                downloads = {}
                for relative in files:
                    destination = run_dir / relative
                    result = active_runner.download(str(PurePosixPath(remote_dir) / relative), destination)
                    downloads[relative] = _step(result)
                details["downloads"] = downloads
                if not spectre.ok:
                    status = "spectre_failed"
                    failure_code = _spectre_failure_code(run_dir, spectre.returncode)
                elif not all(step["ok"] for step in downloads.values()):
                    status, failure_code = "download_failed", "result_download_failed"
                else:
                    try:
                        rows, payload = extract_active_oa(
                            run_dir / "psf", run_id=run_dir.name, supply_voltage_v=supply_voltage_v,
                            source_run_kind="oa_netlist_derivative_bias_load_direct_spectre",
                        )
                        payload.update(context)
                        payload["source_template_sha256"] = template_sha256
                        payload["failure_code"] = None
                        validate_metrics_payload(payload)
                        write_active_oa_results(run_dir, rows, payload)
                        status, failure_code = payload["status"], ""
                    except (OSError, ValueError, TypeError):
                        status, failure_code = "result_parse_failed", "result_parse_failed"
    except RemoteEvaluationUncertain:
        raise
    except Exception as exc:
        details["error_type"] = type(exc).__name__

    if status not in {"ok", "ok_with_warnings"}:
        simulation_status = (
            "failed" if status == "spectre_failed" else
            "ok" if status == "result_parse_failed" else "unknown"
        )
        payload = {
            "schema_version": 1, "status": status,
            "simulation_status": simulation_status,
            "circuit_class": "active_common_source_smoke", "not_lna_result": True,
            "spec_pass": None, "failure_code": failure_code, "analysis": [],
            **context, **details,
        }
        if simulation_status == "ok":
            payload["source"] = "cadence_spectre"
        validate_metrics_payload(payload)
        write_json(run_dir / "metrics.json", payload)
    write_json(run_dir / "candidate.json", candidate.to_dict())
    artifacts = {key: relative for key, relative in _ARTIFACTS.items() if (run_dir / relative).is_file()}
    try:
        write_evidence_manifest(run_dir, artifacts)
    except ValueError:
        payload["upstream_status"] = payload["status"]
        payload["status"] = "evidence_failed"
        payload["simulation_status"] = "unknown"
        payload["failure_code"] = "evidence_validation_failed"
        payload.pop("source", None)
        validate_metrics_payload(payload)
        write_json(run_dir / "metrics.json", payload)
        write_evidence_manifest(run_dir, artifacts)
    return run_dir, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one private OA common-source diagnostic candidate")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    parser.add_argument("--min-host-free-gb", type=float, default=2.66)
    args = parser.parse_args()
    try:
        specs = {item.id: item for item in load_specs(args.specs)}
        spec = specs[args.spec]
        candidate = Candidate(
            candidate_id=args.candidate_id, spec_id=spec.id, seed=args.seed,
            power_ratio_list=[], active_params={"rd_ohm": args.rd_ohm, "vbias_v": args.vbias_v},
            status="active_common_source_diagnostic",
        )
        run_dir, payload = run_active_diagnostic_candidate(
            args.config, args.runs_root, spec, candidate,
            template=args.template, template_sha256=args.template_sha256,
            minimum_host_free_gb=args.min_host_free_gb,
        )
    except (KeyError, OSError, ValueError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} failure_code={payload['failure_code']}")
    print(f"run_id={run_dir.name}")
    return 0 if payload["status"] in {"ok", "ok_with_warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
