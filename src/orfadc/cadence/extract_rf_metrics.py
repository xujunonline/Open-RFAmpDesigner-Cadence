from __future__ import annotations

import math
from bisect import bisect_left


def band_values(rows: list[dict], x_key: str, y_key: str, low: float, high: float) -> list[float]:
    if not math.isfinite(low) or not math.isfinite(high) or low <= 0 or high <= low:
        raise ValueError("frequency band must be finite, positive, and increasing")
    frequencies: list[float] = []
    amplitudes: list[float] = []
    for row in rows:
        x = float(row[x_key])
        value = float(row[y_key])
        if not math.isfinite(x) or x <= 0 or (frequencies and x <= frequencies[-1]):
            raise ValueError("frequency samples must be finite, positive, and strictly increasing")
        if not math.isfinite(value):
            raise ValueError(f"{y_key} must be finite")
        frequencies.append(x)
        amplitudes.append(value)
    if (
        not frequencies
        or (low < frequencies[0] and not math.isclose(low, frequencies[0], rel_tol=1e-12))
        or (high > frequencies[-1] and not math.isclose(high, frequencies[-1], rel_tol=1e-12))
    ):
        raise ValueError("frequency samples do not cover the requested band")

    def edge_value(edge: float) -> float:
        index = bisect_left(frequencies, edge)
        if index < len(frequencies) and math.isclose(frequencies[index], edge, rel_tol=1e-12):
            return amplitudes[index]
        if index > 0 and math.isclose(frequencies[index - 1], edge, rel_tol=1e-12):
            return amplitudes[index - 1]
        if index == 0 or index == len(frequencies):
            raise ValueError("frequency samples do not cover the requested band")
        fraction = (math.log(edge) - math.log(frequencies[index - 1])) / (
            math.log(frequencies[index]) - math.log(frequencies[index - 1])
        )
        return amplitudes[index - 1] + fraction * (amplitudes[index] - amplitudes[index - 1])

    interior = [
        value for frequency, value in zip(frequencies, amplitudes, strict=True)
        if low < frequency < high
        and not math.isclose(frequency, low, rel_tol=1e-12)
        and not math.isclose(frequency, high, rel_tol=1e-12)
    ]
    return [edge_value(low), *interior, edge_value(high)]


def summarize_sparams(rows: list[dict], low_ghz: float, high_ghz: float) -> dict[str, float]:
    s11 = band_values(rows, "freq_ghz", "s11_db", low_ghz, high_ghz)
    s21 = band_values(rows, "freq_ghz", "s21_db", low_ghz, high_ghz)
    s22 = band_values(rows, "freq_ghz", "s22_db", low_ghz, high_ghz)
    if not s11 or not s21 or not s22:
        raise ValueError("missing band data for s-parameter summary")
    return {
        "s11_db": max(s11),
        "s21_db": min(s21),
        "s22_db": max(s22),
        "ripple_db": max(s21) - min(s21),
    }
