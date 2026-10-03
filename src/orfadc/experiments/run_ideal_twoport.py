from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.touchstone import parse_touchstone_2port, write_sparameter_csv
from orfadc.config_loader import write_json
from orfadc.metric_contract import validate_metrics_payload


def run_ideal_twoport(
    config_path: Path,
    netlist_path: Path,
    output_dir: Path,
    *,
    low_ghz: float = 0.1,
    high_ghz: float = 20.0,
) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"run output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex[:12]
    local_netlist = output_dir / "netlist.scs"
    shutil.copy2(netlist_path, local_netlist)
    runner = RemoteRunner(load_remote_config(config_path))
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_smoke_ideal_twoport_{run_id}")
    remote_netlist = str(PurePosixPath(remote_dir) / "netlist.scs")

    mkdir_result = runner.ensure_remote_dir(remote_dir)
    if not mkdir_result.ok:
        return _write_failure(output_dir, "mkdir_failed", run_id=run_id, mkdir=_step(mkdir_result))
    upload_result = runner.upload(local_netlist, remote_netlist)
    if not upload_result.ok:
        return _write_failure(
            output_dir,
            "upload_failed",
            run_id=run_id,
            mkdir=_step(mkdir_result),
            upload=_step(upload_result),
        )

    command = [
        runner.config.spectre_bin,
        "-64",
        "+escchars",
        "-format",
        "psfascii",
        "-raw",
        "psf",
        "+log",
        "spectre.log",
        "netlist.scs",
    ]
    spectre_result = runner.run_remote(command, cwd=remote_dir)
    (output_dir / "spectre.stdout.log").write_text(spectre_result.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(spectre_result.stderr, encoding="utf-8")
    if not spectre_result.ok:
        return _write_failure(
            output_dir,
            "spectre_failed",
            run_id=run_id,
            mkdir=_step(mkdir_result),
            upload=_step(upload_result),
            spectre=_step(spectre_result),
        )

    downloads = {
        "spectre_log": ("spectre.log", output_dir / "spectre.log"),
        "touchstone": ("ideal_twoport.s2p", output_dir / "ideal_twoport.s2p"),
        "psfascii": ("psf/sp_test.sp", output_dir / "sp_test.sp"),
    }
    download_results = {}
    for name, (remote_relative, local_path) in downloads.items():
        result = runner.download(
            str(PurePosixPath(remote_dir) / remote_relative), local_path
        )
        download_results[name] = _step(result)
        if not result.ok:
            return _write_failure(
                output_dir,
                f"{name}_download_failed",
                run_id=run_id,
                spectre=_step(spectre_result),
                downloads=download_results,
            )

    try:
        rows = parse_touchstone_2port(output_dir / "ideal_twoport.s2p")
        if any(row["reference_ohm"] != 50.0 for row in rows):
            raise ValueError("smoke test requires 50-ohm Touchstone ports")
        summary = summarize_sparams(rows, low_ghz, high_ghz)
        write_sparameter_csv(output_dir / "sparams.csv", rows)
    except (OSError, ValueError) as exc:
        return _write_failure(
            output_dir, "result_parse_failed", run_id=run_id, error=str(exc), spectre=_step(spectre_result)
        )
    payload = {
        "schema_version": 1,
        "status": "ok",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "circuit_class": "passive_twoport",
        "run_id": run_id,
        "scope": "PDK-independent passive two-port RF plumbing smoke test",
        "not_lna_result": True,
        "spec_pass": None,
        "spec": None,
        "candidate": None,
        "seed": None,
        "timeout_seconds": runner.config.command_timeout_seconds,
        "analysis": ["sp"],
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        "units": {"s11_db": "dB", "s21_db": "dB", "s22_db": "dB", "ripple_db": "dB"},
        "violation": None,
        "frequency_band_ghz": {"low": low_ghz, "high": high_ghz},
        "points": len(rows),
        "metrics": summary,
        "artifacts": {
            "netlist": "netlist.scs",
            "touchstone": "ideal_twoport.s2p",
            "psfascii": "sp_test.sp",
            "csv": "sparams.csv",
            "spectre_log": "spectre.log",
        },
        "spectre": _step(spectre_result),
        "downloads": download_results,
    }
    validate_metrics_payload(payload)
    write_json(output_dir / "metrics.json", payload)
    return payload


def _write_failure(output_dir: Path, status: str, **details: object) -> dict:
    payload = {
        "schema_version": 1,
        "status": status,
        "simulation_status": "failed" if status == "spectre_failed" else "unknown",
        "circuit_class": "passive_twoport",
        "not_lna_result": True,
        "spec_pass": None,
        **details,
    }
    validate_metrics_payload(payload)
    write_json(output_dir / "metrics.json", payload)
    return payload


def _step(result: object) -> dict[str, int | bool]:
    return {"returncode": result.returncode, "ok": result.ok}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ideal RF two-port Spectre smoke test")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--netlist", type=Path, default=Path("circuit/spectre/ideal_twoport.scs"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--low-ghz", type=float, default=0.1)
    parser.add_argument("--high-ghz", type=float, default=20.0)
    args = parser.parse_args()
    output = args.output or Path("results/runs/rf_smoke/ideal_twoport") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    )
    try:
        payload = run_ideal_twoport(
            args.config, args.netlist, output, low_ghz=args.low_ghz, high_ghz=args.high_ghz
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"status=configuration_error error={exc}")
        return 2
    print(f"status={payload['status']}")
    print(f"output={output.resolve()}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
