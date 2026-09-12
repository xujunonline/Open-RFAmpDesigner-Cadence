from __future__ import annotations

from .cost_functions import stage2_cost


def impedance_matching(active_params: dict, nf_user_db: float, nf_headroom_db: float = 0.2, gain_require_db: float | None = None) -> dict:
    result = {
        "active_params": active_params,
        "gain_require_db": gain_require_db,
        "passive_params_cpstages": {},
        "sim_result_cpstages": {},
        "status": "needs_cadence",
        "note": "Run Stage 2 PSO with Cadence OCEAN to fill NF/S11 metrics.",
    }
    nf_sim = active_params.get("nf_db")
    s11_sim = active_params.get("s11_db")
    if nf_sim is not None and s11_sim is not None:
        result["stage2_cost"] = stage2_cost(float(nf_sim), nf_user_db, float(s11_sim), nf_headroom_db)
        result["status"] = "scored"
    return result

