from __future__ import annotations

import argparse
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.noise_metrics import (
    noise_rows_from_psfascii,
    require_same_frequency_grid,
    summarize_noise,
    write_noise_csv,
)
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.psfascii_reader import parse_scalar_trace, parse_trace_kinds
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.touchstone import parse_touchstone_2port, write_sparameter_csv
from orfadc.config_loader import write_json
from orfadc.metric_contract import validate_metrics_payload


def _step(result: object) -> dict[str, int | bool]:
    return {"returncode": result.returncode, "ok": result.ok}


def _failure(output_dir: Path, status: str, **details: object) -> dict:
    payload = {
        "schema_version": 1,
        "status": status,
        "simulation_status": (
            "failed" if status == "spectre_failed" else
            "ok" if status in {"download_failed", "result_parse_failed"} else "unknown"
        ),
        "spec_pass": None,
        "circuit_class": "passive_twoport",
        "not_lna_result": True,
        **details,
    }
    if payload["simulation_status"] == "ok":
        payload["source"] = "cadence_spectre"
    validate_metrics_payload(payload)
    write_json(output_dir / "metrics.json", payload)
    return payload


def validate_passive_noise_files(
    noise_path: Path, sparameter_path: Path, low_ghz: float, high_ghz: float
) -> tuple[list[dict], list[dict], dict]:
    kinds = parse_trace_kinds(noise_path)
    required = {"NF": "dB", "NFmin": "dB", "F": "Noise factor", "Fmin": "Noise factor"}
    for signal, kind in required.items():
        if kinds.get(signal) != kind:
            raise ValueError(f"expected {signal} trace with {kind} type")
    noise_rows = noise_rows_from_psfascii(
        noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin"
    )
    sparameter_rows = parse_touchstone_2port(sparameter_path)
    if any(row["reference_ohm"] != 50.0 for row in sparameter_rows):
        raise ValueError("passive noise smoke requires 50-ohm ports")
    require_same_frequency_grid(noise_rows, sparameter_rows)
    for factor_name, db_name in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        frequencies, factors = parse_scalar_trace(noise_path, factor_name, require_each_sweep=True)
        if len(frequencies) != len(noise_rows):
            raise ValueError(f"{factor_name} frequency grid differs")
        for frequency, factor, row in zip(frequencies, factors, noise_rows, strict=True):
            if not math.isclose(frequency, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError(f"{factor_name} frequency grid differs")
            if factor <= 0 or not math.isfinite(factor):
                raise ValueError(f"{factor_name} must be positive and finite")
            if not math.isclose(10 * math.log10(factor), row[db_name], abs_tol=1e-6):
                raise ValueError(f"{factor_name} and {db_name} disagree")
    return noise_rows, sparameter_rows, summarize_noise(noise_rows, low_ghz, high_ghz)


def run_passive_noise(
    config_path: Path,
    netlist_path: Path,
    output_dir: Path,
    *,
    run_id: str | None = None,
    runner: RemoteRunner | None = None,
) -> dict:
    if run_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("run_id must be a safe path segment")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"run output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(netlist_path, output_dir / "netlist.scs")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    run_id = run_id or uuid4().hex[:12]
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_noise_{run_id}")
    mkdir = runner.ensure_remote_dir(remote_dir)
    if not mkdir.ok:
        return _failure(output_dir, "mkdir_failed", run_id=run_id, mkdir=_step(mkdir))
    upload = runner.upload(output_dir / "netlist.scs", str(PurePosixPath(remote_dir) / "netlist.scs"))
    if not upload.ok:
        return _failure(output_dir, "upload_failed", run_id=run_id, upload=_step(upload))

    spectre = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
         "+log", "spectre.log", "netlist.scs"],
        cwd=remote_dir,
    )
    (output_dir / "spectre.stdout.log").write_text(spectre.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(spectre.stderr, encoding="utf-8")
    downloads: dict[str, dict[str, int | bool]] = {}
    files = {"spectre.log": "spectre.log"}
    if spectre.ok:
        files.update({
            "ideal_twoport_noise.s2p": "ideal_twoport_noise.s2p",
            "sp_noise.sp": "psf/sp_noise.sp",
            "sp_noise.noise.sp": "psf/sp_noise.noise.sp",
        })
    for local_name, remote_name in files.items():
        result = runner.download(str(PurePosixPath(remote_dir) / remote_name), output_dir / local_name)
        downloads[local_name] = _step(result)
        if not result.ok and spectre.ok:
            return _failure(output_dir, "download_failed", run_id=run_id, downloads=downloads)
    if not spectre.ok:
        return _failure(output_dir, "spectre_failed", run_id=run_id, spectre=_step(spectre), downloads=downloads)

    try:
        noise_rows, sparameter_rows, summary = validate_passive_noise_files(
            output_dir / "sp_noise.noise.sp", output_dir / "ideal_twoport_noise.s2p", 0.1, 20.0
        )
        summary = {**summary, **summarize_sparams(sparameter_rows, 0.1, 20.0)}
        write_noise_csv(output_dir / "noise.csv", noise_rows)
        write_sparameter_csv(output_dir / "sparams.csv", sparameter_rows)
    except (OSError, ValueError) as exc:
        return _failure(output_dir, "result_parse_failed", run_id=run_id, error=str(exc), downloads=downloads)
    payload = {
        "schema_version": 1,
        "status": "ok",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "raw_format": "psfascii",
        "circuit_class": "passive_twoport",
        "scope": "PDK-independent passive two-port noise data pipeline smoke test",
        "not_lna_result": True,
        "spec_pass": None,
        "spec": None,
        "candidate": None,
        "seed": None,
        "timeout_seconds": runner.config.command_timeout_seconds,
        "analysis": ["sp", "noise"],
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        "units": {
            "nf_db": "dB", "nfmin_db": "dB", "points_in_band": "count",
            "s11_db": "dB", "s21_db": "dB", "s22_db": "dB", "ripple_db": "dB",
        },
        "violation": None,
        "run_id": run_id,
        "frequency_band_ghz": {"low": 0.1, "high": 20.0},
        "points": len(noise_rows),
        "sparameter_grid_checked": True,
        "factor_db_crosscheck": True,
        "metrics": summary,
        "spectre": _step(spectre),
        "downloads": downloads,
        "artifacts": ["netlist.scs", *files, "noise.csv", "sparams.csv", "spectre.stdout.log", "spectre.stderr.log"],
    }
    validate_metrics_payload(payload)
    write_json(output_dir / "metrics.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the passive two-port Spectre noise smoke test")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--netlist", type=Path, default=Path("circuit/spectre/ideal_twoport_noise_unverified.scs"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path("results/runs/rf_smoke/passive_noise") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    )
    try:
        payload = run_passive_noise(args.config, args.netlist, output)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"status=configuration_error error={exc}")
        return 2
    print(f"status={payload['status']}")
    print(f"output={output.resolve()}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
