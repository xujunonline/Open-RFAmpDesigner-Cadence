from __future__ import annotations

import math


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def positive_part(value: float) -> float:
    return max(0.0, _finite(value, "value"))


def stage2_cost(nf_sim_db: float, nf_user_db: float, s11_sim_db: float, nf_headroom_db: float = 0.2) -> dict[str, float]:
    nf_sim_db = _finite(nf_sim_db, "nf_sim_db")
    nf_user_db = _finite(nf_user_db, "nf_user_db")
    s11_sim_db = _finite(s11_sim_db, "s11_sim_db")
    nf_headroom_db = _finite(nf_headroom_db, "nf_headroom_db")
    if nf_headroom_db < 0:
        raise ValueError("nf_headroom_db must be nonnegative")
    nf_violation = positive_part(nf_sim_db - (nf_user_db - nf_headroom_db))
    s11_violation = positive_part(s11_sim_db + 20.0)
    cost = 1000.0 * nf_violation + 1000.0 * s11_violation
    return {
        "nf_violation": nf_violation,
        "s11_violation": s11_violation,
        "cost": cost,
    }


def stage3_cost(gain_cal_db: list[float], gain_user_db: float, ripple_limit_db: float = 3.0) -> dict[str, float]:
    if not gain_cal_db:
        raise ValueError("gain_cal_db must not be empty")
    gain_cal_db = [_finite(value, "gain_cal_db") for value in gain_cal_db]
    gain_user_db = _finite(gain_user_db, "gain_user_db")
    ripple_limit_db = _finite(ripple_limit_db, "ripple_limit_db")
    if ripple_limit_db < 0:
        raise ValueError("ripple_limit_db must be nonnegative")
    min_gain = min(gain_cal_db)
    max_gain = max(gain_cal_db)
    gain_violation = positive_part(abs(gain_user_db - min_gain) - ripple_limit_db)
    ripple_violation = positive_part(max_gain - min_gain - ripple_limit_db)
    cost = 1000.0 * gain_violation + 1000.0 * ripple_violation
    return {
        "min_gain_db": min_gain,
        "max_gain_db": max_gain,
        "gain_violation": gain_violation,
        "ripple_violation": ripple_violation,
        "cost": cost,
    }
