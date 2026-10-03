from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MCRParameters:
    coupling_k: float
    omega0_rad_s: float
    q0: float
    source_resistance_ohm: float
    output_resistance_ohm: float
    source_capacitance_f: float
    gm_s: float
    reference_resistance_ohm: float = 50.0

    def __post_init__(self) -> None:
        values = vars(self)
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in values.values()):
            raise ValueError("MCR parameters must be finite real numbers")
        if not 0 <= self.coupling_k < 1:
            raise ValueError("coupling_k must be in [0, 1)")
        for name in (
            "omega0_rad_s", "q0", "source_resistance_ohm",
            "output_resistance_ohm", "gm_s", "reference_resistance_ohm",
        ):
            if values[name] <= 0:
                raise ValueError(f"{name} must be positive")
        if self.source_capacitance_f < 0:
            raise ValueError("source_capacitance_f must be nonnegative")


@dataclass(frozen=True)
class MCRResponse:
    frequency_hz: float
    y11_s: complex
    z21_ohm: complex
    load_resistance_ohm: float
    load_capacitance_f: float
    passive_parallel_rc: bool
    i11_a_per_v: complex
    normalized_v21_v_per_v: complex


def _mcr_numerator(s: complex, k: float, q: float, w0: float) -> complex:
    one_minus_k2 = 1 - k * k
    return (
        one_minus_k2 * q**2 * s**4
        + 2 * one_minus_k2 * q * w0 * s**3
        + (one_minus_k2 + 2 * q**2) * w0**2 * s**2
        + 2 * q * w0**3 * s
        + q**2 * w0**4
    )


def y11_dimensional_candidate(frequency_hz: float, params: MCRParameters) -> complex:
    """A hypothesized missing-s correction, not the paper's printed Y11 formula."""
    if type(frequency_hz) not in {int, float} or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("frequency_hz must be finite and positive")
    if not isinstance(params, MCRParameters):
        raise TypeError("params must be MCRParameters")
    s = 1j * 2 * math.pi * frequency_hz
    k, q, w0 = params.coupling_k, params.q0, params.omega0_rad_s
    rs = params.source_resistance_ohm
    numerator = _mcr_numerator(s, k, q, w0)
    denominator = (
        (1 - k * k) * rs * w0 * q * s**3
        + (1 - k * k) * rs * w0**2 * s**2
        + rs * w0**3 * q * s
    )
    if denominator == 0:
        raise ValueError("dimensionally corrected Y11 is singular")
    result = numerator / denominator
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        raise ValueError("dimensionally corrected Y11 is nonfinite")
    return result


def paper_equation_3(frequency_hz: float, params: MCRParameters) -> MCRResponse:
    """Evaluate the paper's symmetric, single-point-load MCR approximation."""
    if type(frequency_hz) not in {int, float} or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("frequency_hz must be finite and positive")
    if not isinstance(params, MCRParameters):
        raise TypeError("params must be MCRParameters")
    s = 1j * 2 * math.pi * frequency_hz
    k = params.coupling_k
    q = params.q0
    w0 = params.omega0_rad_s
    rs = params.source_resistance_ohm
    r2 = params.output_resistance_ohm
    cs = params.source_capacitance_f
    rref = params.reference_resistance_ohm
    one_minus_k2 = 1 - k * k
    numerator = _mcr_numerator(s, k, q, w0)
    y_denominator = (
        one_minus_k2 * rs * w0 * q * s**3
        + one_minus_k2 * rs * w0**2 * s**2
        + rs * w0**3 * q
    )
    if y_denominator == 0 or numerator == 0:
        raise ValueError("MCR response is singular at this frequency")
    y11 = numerator / y_denominator
    if y11.real == 0:
        raise ValueError("Y11 has no finite parallel resistance")
    rl = 1 / y11.real
    cl = y11.imag / s.imag
    z21 = k * q * w0**3 * math.sqrt(rs * r2) * s / numerator
    i_denominator = rs * rl * (cs + cl) * s + rs + rl
    if i_denominator == 0:
        raise ValueError("MCR current response is singular at this frequency")
    i11 = (
        params.gm_s
        * (rref * rs * cs * s + rs + rref) / rs
        * rs * (rl * cl * s + 1) / i_denominator
    )
    voltage = i11 * z21 / 2
    if any(not math.isfinite(component) for value in (y11, z21, i11, voltage)
           for component in (value.real, value.imag)):
        raise ValueError("MCR response is nonfinite")
    return MCRResponse(
        frequency_hz=float(frequency_hz),
        y11_s=y11,
        z21_ohm=z21,
        load_resistance_ohm=rl,
        load_capacitance_f=cl,
        passive_parallel_rc=rl > 0 and cl >= 0,
        i11_a_per_v=i11,
        normalized_v21_v_per_v=voltage,
    )
