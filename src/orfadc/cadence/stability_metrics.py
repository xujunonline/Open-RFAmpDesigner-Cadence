from __future__ import annotations

import math


def rollett_k_and_delta(
    s11: complex, s21: complex, s12: complex, s22: complex
) -> tuple[float | None, float]:
    for value in (s11, s21, s12, s22):
        if not math.isfinite(value.real) or not math.isfinite(value.imag):
            raise ValueError("S parameters must be finite")
    delta_abs = abs(s11 * s22 - s12 * s21)
    denominator = 2 * abs(s12 * s21)
    if denominator == 0:
        return None, delta_abs
    k = (1 - abs(s11) ** 2 - abs(s22) ** 2 + delta_abs**2) / denominator
    return k, delta_abs


def summarize_sampled_stability(
    s11: list[complex], s21: list[complex], s12: list[complex], s22: list[complex]
) -> dict[str, float | bool | None]:
    if not s11 or not (len(s11) == len(s21) == len(s12) == len(s22)):
        raise ValueError("S-parameter traces must be nonempty and aligned")
    pairs = [
        rollett_k_and_delta(*values)
        for values in zip(s11, s21, s12, s22, strict=True)
    ]
    known_k = [k for k, _ in pairs if k is not None]
    return {
        "minimum_k": min(known_k) if len(known_k) == len(pairs) else None,
        "maximum_delta_abs": max(delta for _, delta in pairs),
        "unconditionally_stable_on_sampled_grid": all(
            k is not None and k > 1 and delta < 1 for k, delta in pairs
        ),
    }
