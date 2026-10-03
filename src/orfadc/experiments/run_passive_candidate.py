from __future__ import annotations

import argparse
import math
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteCadenceConfig, RemoteRunner, load_remote_config
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.run_passive_noise import run_passive_noise
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate, Spec


_PARAMETERS = {
    "rloss_ohm": (0.1, 100.0, "RLOSS", ""),
    "lpath_nh": (0.1, 20.0, "LPATH", "n"),
    "cshunt_pf": (0.01, 10.0, "CSHUNT", "p"),
}
_TEMPLATE_LINE = re.compile(r"^parameters RLOSS=5 LPATH=1n CSHUNT=0\.5p$", re.MULTILINE)
_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[3] / "circuit/spectre/ideal_twoport_noise_unverified.scs"
_ARTIFACTS = {
    "metrics": "metrics.json",
    "candidate": "candidate.json",
    "netlist": "netlist.scs",
    "spectre_log": "spectre.log",
    "touchstone": "ideal_twoport_noise.s2p",
    "sp_raw": "sp_noise.sp",
    "noise_raw": "sp_noise.noise.sp",
    "sparams_csv": "sparams.csv",
    "noise_csv": "noise.csv",
    "stdout": "spectre.stdout.log",
    "stderr": "spectre.stderr.log",
}


def render_passive_candidate_netlist(candidate: Candidate, template: Path = _DEFAULT_TEMPLATE) -> str:
    if candidate.active_params or candidate.sim_result is not None:
        raise ValueError("passive diagnostic candidate cannot contain active parameters or results")
    if not isinstance(candidate.passive_params, dict) or set(candidate.passive_params) != set(_PARAMETERS):
        raise ValueError("passive candidate requires exactly rloss_ohm, lpath_nh, cshunt_pf")
    values: dict[str, float] = {}
    for key, (low, high, _, _) in _PARAMETERS.items():
        value = candidate.passive_params[key]
        if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be finite and in [{low}, {high}]")
        values[key] = float(value)
    original = template.read_text(encoding="ascii")
    replacement = "parameters " + " ".join(
        f"{name}={values[key]:.17g}{suffix}"
        for key, (_, _, name, suffix) in _PARAMETERS.items()
    )
    rendered, count = _TEMPLATE_LINE.subn(replacement, original)
    if count != 1:
        raise ValueError("passive netlist template has changed")
    return rendered


def _failure_code(payload: dict, run_dir: Path) -> str | None:
    status = payload["status"]
    if status == "ok":
        return None
    if status == "spectre_failed":
        logs = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for name in ("spectre.log", "spectre.stderr.log")
            if (path := run_dir / name).is_file()
        )
        license_diagnostic = bool(re.search(
            r"waiting for (?:a )?licen[sc]e|licen[sc]e (?:checkout failed|unavailable|wait)",
            logs, re.IGNORECASE,
        ))
        if payload.get("spectre", {}).get("returncode") == 124:
            return "license_related_timeout" if license_diagnostic else "spectre_timeout"
        return "license_checkout_failed" if license_diagnostic else "spectre_error"
    return {
        "mkdir_failed": "remote_directory_failed",
        "upload_failed": "upload_failed",
        "download_failed": "result_download_failed",
        "result_parse_failed": "result_parse_failed",
        "backend_error": "backend_error",
    }.get(status, "other_failure")


def run_passive_candidate(
    config_path: Path,
    runs_root: Path,
    spec: Spec,
    candidate: Candidate,
    *,
    template: Path = _DEFAULT_TEMPLATE,
    run_id: str | None = None,
    remote_config: RemoteCadenceConfig | None = None,
) -> tuple[Path, dict]:
    """Run a PDK-independent diagnostic candidate; never score it as an LNA."""
    netlist = render_passive_candidate_netlist(candidate, template)
    config = remote_config if remote_config is not None else load_remote_config(config_path)
    run_dir = reserve_candidate_run(runs_root, spec, candidate, run_id=run_id)
    context = {
        "spec": asdict(spec),
        "candidate": candidate.to_dict(),
        "seed": candidate.seed,
        "timeout_seconds": config.command_timeout_seconds,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="orfadc_passive_", dir=runs_root) as temporary:
            source = Path(temporary) / "netlist.scs"
            source.write_text(netlist, encoding="ascii")
            payload = run_passive_noise(
                config_path,
                source,
                run_dir,
                run_id=run_dir.name,
                runner=RemoteRunner(config) if remote_config is not None else None,
            )
    except (OSError, ValueError) as exc:
        payload = {
            "schema_version": 1,
            "status": "backend_error",
            "simulation_status": "unknown",
            "circuit_class": "passive_twoport",
            "not_lna_result": True,
            "spec_pass": None,
            "run_id": run_dir.name,
            "error_type": type(exc).__name__,
        }
    payload.update(context)
    payload["failure_code"] = _failure_code(payload, run_dir)
    if payload["simulation_status"] == "ok" and not (run_dir / "spectre.log").is_file():
        payload["upstream_status"] = payload["status"]
        payload["status"] = "incomplete_evidence"
        payload["simulation_status"] = "unknown"
        payload["failure_code"] = "missing_spectre_log"
        payload.pop("source", None)
    validate_metrics_payload(payload)
    write_json(run_dir / "candidate.json", candidate.to_dict())
    write_json(run_dir / "metrics.json", payload)
    artifacts = {key: name for key, name in _ARTIFACTS.items() if (run_dir / name).is_file()}
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
    parser = argparse.ArgumentParser(description="Run one passive Spectre diagnostic candidate")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=Path("results/runs"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-id")
    parser.add_argument("--rloss-ohm", type=float, required=True)
    parser.add_argument("--lpath-nh", type=float, required=True)
    parser.add_argument("--cshunt-pf", type=float, required=True)
    args = parser.parse_args()
    try:
        specs = {item.id: item for item in load_specs(args.specs)}
        if args.spec not in specs:
            raise ValueError(f"unknown spec: {args.spec}")
        candidate = Candidate(
            candidate_id=args.candidate_id or f"{args.spec}_seed{args.seed}_passive",
            spec_id=args.spec,
            seed=args.seed,
            power_ratio_list=[],
            passive_params={
                "rloss_ohm": args.rloss_ohm,
                "lpath_nh": args.lpath_nh,
                "cshunt_pf": args.cshunt_pf,
            },
            status="passive_diagnostic",
        )
        run_dir, payload = run_passive_candidate(args.config, args.runs_root, specs[args.spec], candidate)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"status={payload['status']} failure_code={payload['failure_code']}")
    print(f"run_dir={run_dir.resolve()}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
