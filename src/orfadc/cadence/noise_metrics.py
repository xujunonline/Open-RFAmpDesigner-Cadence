from __future__ import annotations

import csv
import math
from pathlib import Path

from .extract_rf_metrics import band_values
from .psfascii_reader import parse_scalar_trace


def noise_rows_from_psfascii(
    path: Path,
    *,
    nf_signal: str,
    nf_unit: str,
    nfmin_signal: str | None = None,
) -> list[dict[str, float | None]]:
    if not nf_signal or nfmin_signal == nf_signal:
        raise ValueError("noise signal names must be nonempty and distinct")
    nf_trace = parse_scalar_trace(path, nf_signal, require_each_sweep=True)
    nfmin_trace = (
        parse_scalar_trace(path, nfmin_signal, require_each_sweep=True) if nfmin_signal else None
    )
    return normalize_noise_traces(nf_trace, nf_unit=nf_unit, nfmin_trace=nfmin_trace)


def normalize_noise_traces(
    nf_trace: tuple[list[float], list[float]],
    *,
    nf_unit: str,
    nfmin_trace: tuple[list[float], list[float]] | None = None,
) -> list[dict[str, float | None]]:
    if nf_unit not in {"db", "linear_factor"}:
        raise ValueError("nf_unit must be 'db' or 'linear_factor'")
    frequencies, values = nf_trace
    if not frequencies or len(frequencies) != len(values):
        raise ValueError("NF trace must contain paired frequency samples")
    if nfmin_trace is not None:
        min_frequencies, min_values = nfmin_trace
        if len(min_frequencies) != len(frequencies) or len(min_values) != len(frequencies):
            raise ValueError("NFmin and NF frequency grids differ")
    else:
        min_frequencies, min_values = [], []

    rows: list[dict[str, float | None]] = []
    previous = 0.0
    for index, (frequency, value) in enumerate(zip(frequencies, values, strict=True)):
        if not math.isfinite(frequency) or frequency <= previous:
            raise ValueError("noise frequencies must be finite, positive, and strictly increasing")
        previous = frequency
        if nfmin_trace is not None and not math.isclose(
            frequency, min_frequencies[index], rel_tol=1e-10, abs_tol=1e-3
        ):
            raise ValueError("NFmin and NF frequency grids differ")
        rows.append(
            {
                "freq_hz": frequency,
                "freq_ghz": frequency / 1e9,
                "nf_db": _as_db(value, nf_unit),
                "nfmin_db": _as_db(min_values[index], nf_unit) if nfmin_trace is not None else None,
            }
        )
    return rows


def summarize_noise(
    rows: list[dict[str, float | None]], low_ghz: float, high_ghz: float
) -> dict[str, float | int | None]:
    nf = band_values(rows, "freq_ghz", "nf_db", low_ghz, high_ghz)
    available_nfmin = [row["nfmin_db"] is not None for row in rows]
    if any(available_nfmin) and not all(available_nfmin):
        raise ValueError("NFmin must be present for every frequency or none")
    nfmin = (
        max(band_values(rows, "freq_ghz", "nfmin_db", low_ghz, high_ghz))
        if all(available_nfmin) else None
    )
    return {"nf_db": max(nf), "nfmin_db": nfmin, "points_in_band": len(nf)}


def require_same_frequency_grid(
    noise_rows: list[dict[str, float | None]], sparameter_rows: list[dict[str, float]]
) -> None:
    if not noise_rows or len(noise_rows) != len(sparameter_rows):
        raise ValueError("noise and S-parameter frequency grids differ")
    for noise, sparameter in zip(noise_rows, sparameter_rows, strict=True):
        if not math.isclose(
            float(noise["freq_hz"]), float(sparameter["freq_hz"]), rel_tol=1e-10, abs_tol=1e-3
        ):
            raise ValueError("noise and S-parameter frequency grids differ")


def write_noise_csv(path: Path, rows: list[dict[str, float | None]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty noise table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("freq_hz", "freq_ghz", "nf_db", "nfmin_db"))
        writer.writeheader()
        writer.writerows(rows)


def _as_db(value: float, unit: str) -> float:
    if not math.isfinite(value):
        raise ValueError("noise factor or figure must be finite")
    if unit == "linear_factor":
        if value <= 0:
            raise ValueError("linear noise factor must be positive")
        return 10 * math.log10(value)
    return value
