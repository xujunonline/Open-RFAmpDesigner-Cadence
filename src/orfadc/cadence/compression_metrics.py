from __future__ import annotations

import math
from collections.abc import Sequence


def extract_p1db(
    rows: Sequence[dict[str, float]],
    *,
    linear_points: int = 3,
    linearity_tolerance_db: float = 0.2,
) -> dict[str, object]:
    """Find the first measured 1 dB gain-compression crossing in a power sweep."""
    if linear_points < 2 or len(rows) < linear_points + 1:
        raise ValueError("compression sweep needs a linear reference and at least one later point")
    if not math.isfinite(linearity_tolerance_db) or linearity_tolerance_db < 0:
        raise ValueError("linearity tolerance must be finite and nonnegative")

    pins: list[float] = []
    pouts: list[float] = []
    for row in rows:
        if isinstance(row.get("pin_dbm"), bool) or isinstance(row.get("pout_dbm"), bool):
            raise ValueError("power sweep values must be finite numbers")
        try:
            pin = float(row["pin_dbm"])
            pout = float(row["pout_dbm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("each power row needs finite pin_dbm and pout_dbm") from exc
        if not math.isfinite(pin) or not math.isfinite(pout):
            raise ValueError("power sweep values must be finite")
        if pins and pin <= pins[-1]:
            raise ValueError("input power must be strictly increasing")
        pins.append(pin)
        pouts.append(pout)

    gains = [pout - pin for pin, pout in zip(pins, pouts, strict=True)]
    reference = gains[:linear_points]
    if max(reference) - min(reference) > linearity_tolerance_db:
        raise ValueError("first power points do not establish a linear gain reference")
    small_signal_gain = sum(reference) / linear_points
    compression = [small_signal_gain - gain for gain in gains]
    quality_flags = [
        "nonmonotonic_output_power"
        for left, right in zip(pouts, pouts[1:])
        if right < left
    ]
    quality_flags = sorted(set(quality_flags))

    for index in range(linear_points, len(rows)):
        if compression[index] < 1.0:
            continue
        previous = index - 1
        if compression[previous] >= 1.0:
            raise ValueError("compression crossing is not bracketed by adjacent sweep points")
        fraction = (1.0 - compression[previous]) / (compression[index] - compression[previous])
        ip1db = pins[previous] + fraction * (pins[index] - pins[previous])
        op1db = pouts[previous] + fraction * (pouts[index] - pouts[previous])
        return {
            "status": "quality_warning" if quality_flags else "ok",
            "ip1db_dbm": ip1db,
            "op1db_dbm": op1db,
            "small_signal_gain_db": small_signal_gain,
            "reference_points": linear_points,
            "crossing_indices": [previous, index],
            "quality_flags": quality_flags,
        }

    return {
        "status": "unbracketed",
        "ip1db_dbm": None,
        "op1db_dbm": None,
        "small_signal_gain_db": small_signal_gain,
        "reference_points": linear_points,
        "crossing_indices": None,
        "quality_flags": quality_flags,
    }
