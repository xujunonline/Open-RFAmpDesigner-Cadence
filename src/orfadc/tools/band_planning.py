from __future__ import annotations

from .cost_functions import stage3_cost


def band_planning(active_params: dict, gain_list_db: list[float], gain_user_db: float, gain_require_list: list[float] | None = None) -> dict:
    cost = stage3_cost(gain_list_db, gain_user_db)
    return {
        "active_params": active_params,
        "gain_require_list": gain_require_list,
        "passive_params_dict": {},
        "cal_gain_dict": {"gain_db": gain_list_db},
        "stage3_cost": cost,
        "status": "low_fidelity_scored",
    }

