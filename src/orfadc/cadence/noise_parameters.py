from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .psfascii_reader import parse_scalar_trace


@dataclass(frozen=True)
class NoiseParameterPoint:
    frequency_hz: float
    fmin: float
    gopt_s: float
    bopt_s: float
    rn_ohm: float
    measured_f: float
    measured_nf_db: float

    @property
    def yopt_s(self) -> complex:
        return complex(self.gopt_s, self.bopt_s)


def noise_factor_at_source(point: NoiseParameterPoint, source_admittance_s: complex) -> float:
    values = (
        point.frequency_hz, point.fmin, point.gopt_s,
        point.bopt_s, point.rn_ohm, point.measured_f,
    )
    if (
        any(not math.isfinite(value) for value in values)
        or point.frequency_hz <= 0 or point.fmin < 1
        or point.gopt_s <= 0 or point.rn_ohm < 0 or point.measured_f <= 0
        or not math.isfinite(source_admittance_s.real)
        or not math.isfinite(source_admittance_s.imag)
        or source_admittance_s.real <= 0
    ):
        raise ValueError("noise parameters or passive source admittance are invalid")
    factor = point.fmin + point.rn_ohm / source_admittance_s.real * abs(
        source_admittance_s - point.yopt_s
    ) ** 2
    if not math.isfinite(factor) or factor < 1:
        raise ValueError("source noise factor is invalid")
    return factor


def source_reflection_from_admittance(source_admittance_s: complex, reference_ohm: float) -> complex:
    if (
        type(reference_ohm) not in {int, float} or not math.isfinite(reference_ohm)
        or reference_ohm <= 0 or not math.isfinite(source_admittance_s.real)
        or not math.isfinite(source_admittance_s.imag)
        or source_admittance_s.real <= 0
    ):
        raise ValueError("source admittance and real reference impedance must be passive")
    yref = 1 / reference_ohm
    return (yref - source_admittance_s) / (yref + source_admittance_s)


def matched_load_transducer_gain(s11: complex, s21: complex, gamma_s: complex) -> float:
    if any(not math.isfinite(value) for value in (
        s11.real, s11.imag, s21.real, s21.imag, gamma_s.real, gamma_s.imag,
    )) or abs(gamma_s) >= 1:
        raise ValueError("source-pull S parameters or source reflection are invalid")
    denominator = abs(1 - s11 * gamma_s) ** 2
    if denominator <= 0:
        raise ValueError("source-pull gain denominator is zero")
    gain = abs(s21) ** 2 * (1 - abs(gamma_s) ** 2) / denominator
    if not math.isfinite(gain) or gain <= 0:
        raise ValueError("source-pull transducer gain is nonphysical")
    return gain


def read_noise_parameter_points(path: Path) -> list[NoiseParameterPoint]:
    names = ("F", "Fmin", "NF", "NFmin", "Gopt", "Bopt", "RN")
    traces = {name: parse_scalar_trace(path, name, require_each_sweep=True) for name in names}
    frequencies = traces["F"][0]
    if not frequencies or any(traces[name][0] != frequencies for name in names):
        raise ValueError("Spectre noise-parameter traces have inconsistent frequency grids")
    result = []
    previous = 0.0
    for index, frequency in enumerate(frequencies):
        point = NoiseParameterPoint(
            frequency_hz=frequency, fmin=traces["Fmin"][1][index],
            gopt_s=traces["Gopt"][1][index], bopt_s=traces["Bopt"][1][index],
            rn_ohm=traces["RN"][1][index], measured_f=traces["F"][1][index],
            measured_nf_db=traces["NF"][1][index],
        )
        if (
            frequency <= previous or not math.isfinite(point.measured_nf_db)
            or not math.isclose(10 * math.log10(point.fmin), traces["NFmin"][1][index],
                                rel_tol=0, abs_tol=1e-9)
            or not math.isclose(10 * math.log10(point.measured_f), point.measured_nf_db,
                                rel_tol=0, abs_tol=1e-9)
        ):
            raise ValueError("Spectre noise-parameter point is inconsistent")
        noise_factor_at_source(point, complex(1 / 50, 0))
        result.append(point)
        previous = frequency
    return result
