from __future__ import annotations


def positive_part(value: float) -> float:
    return max(0.0, float(value))


def stage2_cost(nf_sim_db: float, nf_user_db: float, s11_sim_db: float, nf_headroom_db: float = 0.2) -> dict[str, float]:
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


def fullchain_violations(result: dict[str, float], spec: dict[str, float]) -> dict[str, float | bool]:
    s11_violation = positive_part(result.get("s11_db", 0.0) + 10.0)
    gain_violation = positive_part(spec["gain_db"] - result.get("s21_db", -1e9))
    nf_violation = positive_part(result.get("nf_db", 1e9) - spec["nf_max_db"])
    ip1db_violation = positive_part(spec["ip1db_min_dbm"] - result.get("ip1db_dbm", -1e9))
    power_violation = positive_part(result.get("power_ma", 1e9) - spec["power_ma"])
    total = s11_violation + gain_violation + nf_violation + ip1db_violation + power_violation
    return {
        "s11_violation": s11_violation,
        "gain_violation": gain_violation,
        "nf_violation": nf_violation,
        "ip1db_violation": ip1db_violation,
        "power_violation": power_violation,
        "total_violation": total,
        "pass": total == 0.0,
    }

