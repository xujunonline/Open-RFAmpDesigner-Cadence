from __future__ import annotations

import math

from .cost_functions import stage2_cost


def ideal_shunt_l_series_c_output_match(
    s22: complex, *, frequency_hz: float, baseline_l_h: float,
    baseline_c_f: float, reference_ohm: float = 50.0,
) -> dict[str, float | str]:
    """Estimate a single-frequency ideal output match from a measured S22."""
    if type(s22) is not complex or any(not math.isfinite(x) for x in (s22.real, s22.imag)):
        raise ValueError("S22 must be a finite complex reflection coefficient")
    values = (frequency_hz, baseline_l_h, baseline_c_f, reference_ohm)
    if any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("frequency, baseline L/C and reference impedance must be finite and positive")
    if abs(1 - s22) < 1e-9:
        raise ValueError("S22 is too close to unity for an impedance estimate")
    omega = 2 * math.pi * frequency_hz
    z_port = reference_ohm * (1 + s22) / (1 - s22)
    z_shunt = z_port + 1j / (omega * baseline_c_f)
    if abs(z_shunt) < 1e-12:
        raise ValueError("inferred output impedance is singular")
    y_shunt = 1 / z_shunt
    if y_shunt.real <= 0 or y_shunt.imag >= 0:
        raise ValueError("measured output does not fit a positive parallel R/L model")
    effective_r = 1 / y_shunt.real
    inferred_l = -1 / (omega * y_shunt.imag)
    if not math.isclose(inferred_l, baseline_l_h, rel_tol=0.1):
        raise ValueError("measured S22 disagrees with the claimed baseline shunt inductor")
    if effective_r <= reference_ohm:
        raise ValueError("parallel resistance is too low for this output matching topology")
    target_x = effective_r * math.sqrt(reference_ohm / (effective_r - reference_ohm))
    z_target_shunt = 1 / (1 / effective_r - 1j / target_x)
    target_l_h = target_x / omega
    target_c_f = 1 / (omega * z_target_shunt.imag)
    if not all(math.isfinite(x) and x > 0 for x in (target_l_h, target_c_f)):
        raise ValueError("output match estimate is nonphysical")
    return {
        "method": "ideal_parallel_r_l_plus_series_c_single_frequency",
        "frequency_hz": frequency_hz,
        "inferred_parallel_r_ohm": effective_r,
        "inferred_baseline_l_nh": inferred_l * 1e9,
        "suggested_ldd_nh": target_l_h * 1e9,
        "suggested_cblock_ff": target_c_f * 1e15,
        "reference_ohm": reference_ohm,
    }


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
        result["status"] = "unverified_score"
        result["note"] = "Cost was computed from supplied metrics; Cadence provenance is not verified."
    return result
