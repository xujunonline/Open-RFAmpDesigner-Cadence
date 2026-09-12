from __future__ import annotations


def band_values(rows: list[dict], x_key: str, y_key: str, low: float, high: float) -> list[float]:
    values = []
    for row in rows:
        x = float(row[x_key])
        if low <= x <= high:
            values.append(float(row[y_key]))
    return values


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

