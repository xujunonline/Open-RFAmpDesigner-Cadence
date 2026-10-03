from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from orfadc.cadence.noise_metrics import (
    noise_rows_from_psfascii,
    require_same_frequency_grid,
    summarize_noise,
    write_noise_csv,
)
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.config_loader import write_json


def extract_noise(
    psfascii: Path,
    output_dir: Path,
    *,
    nf_signal: str,
    nf_unit: str,
    low_ghz: float,
    high_ghz: float,
    nfmin_signal: str | None = None,
    sparameters: Path | None = None,
) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"run output directory is not empty: {output_dir}")
    rows = noise_rows_from_psfascii(
        psfascii, nf_signal=nf_signal, nf_unit=nf_unit, nfmin_signal=nfmin_signal
    )
    if sparameters is not None:
        require_same_frequency_grid(rows, parse_touchstone_2port(sparameters))
    summary = summarize_noise(rows, low_ghz, high_ghz)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(psfascii, output_dir / "noise_raw.psfascii")
    if sparameters is not None:
        shutil.copy2(sparameters, output_dir / "sparams_raw.s2p")
    write_noise_csv(output_dir / "noise.csv", rows)
    payload = {
        "schema_version": 1,
        "status": "parsed_unverified",
        "simulation_status": "unknown",
        "source": "external_psfascii",
        "spec_pass": None,
        "circuit_class": "unspecified",
        "frequency_band_ghz": {"low": low_ghz, "high": high_ghz},
        "points": len(rows),
        "sparameter_grid_checked": sparameters is not None,
        "metrics": summary,
        "artifacts": {"raw_noise": "noise_raw.psfascii", "csv": "noise.csv"},
    }
    if sparameters is not None:
        payload["artifacts"]["raw_sparameters"] = "sparams_raw.s2p"
    write_json(output_dir / "metrics.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize an existing PSFASCII NF trace")
    parser.add_argument("--psfascii", required=True, type=Path)
    parser.add_argument("--nf-signal", required=True)
    parser.add_argument("--nf-unit", required=True, choices=("db", "linear_factor"))
    parser.add_argument("--nfmin-signal")
    parser.add_argument("--sparams", type=Path)
    parser.add_argument("--low-ghz", required=True, type=float)
    parser.add_argument("--high-ghz", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = extract_noise(
            args.psfascii,
            args.output,
            nf_signal=args.nf_signal,
            nf_unit=args.nf_unit,
            nfmin_signal=args.nfmin_signal,
            sparameters=args.sparams,
            low_ghz=args.low_ghz,
            high_ghz=args.high_ghz,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"status={payload['status']}")
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
