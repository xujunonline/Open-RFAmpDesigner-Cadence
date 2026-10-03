from __future__ import annotations

import math
from bisect import bisect_left


def oneport_impedance(s11: complex, reference_ohm: float) -> complex:
    if (type(s11) is not complex or any(not math.isfinite(part) for part in (s11.real, s11.imag))
            or type(reference_ohm) not in {int, float} or not math.isfinite(reference_ohm)
            or reference_ohm <= 0):
        raise ValueError("one-port S11 and reference impedance must be finite")
    if abs(1 - s11) < 1e-10:
        raise ValueError("one-port S11 is too close to an open circuit")
    impedance = reference_ohm * (1 + s11) / (1 - s11)
    if any(not math.isfinite(part) for part in (impedance.real, impedance.imag)):
        raise ValueError("one-port impedance is nonfinite")
    return impedance


def summarize_inductor_oneport(
    frequency_hz: list[float], s11: list[complex], *, reference_ohm: float,
    band_low_hz: float, band_high_hz: float, minimum_q: float,
    minimum_srf_ratio: float,
) -> dict:
    if not isinstance(frequency_hz, list) or not isinstance(s11, list) or len(frequency_hz) != len(s11) or len(s11) < 3:
        raise ValueError("inductor characterization needs aligned frequency and S11 arrays")
    limits = (band_low_hz, band_high_hz, minimum_q, minimum_srf_ratio)
    if any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in limits):
        raise ValueError("inductor characterization limits must be finite and positive")
    if band_high_hz <= band_low_hz or minimum_srf_ratio <= 1:
        raise ValueError("inductor band and SRF ratio are invalid")
    frequencies = []
    reactances = []
    qualities = []
    inductances = []
    for sample, reflection in zip(frequency_hz, s11, strict=True):
        if (type(sample) not in {int, float} or not math.isfinite(sample) or sample <= 0
                or frequencies and sample <= frequencies[-1]):
            raise ValueError("inductor frequencies must be strictly increasing")
        impedance = oneport_impedance(reflection, reference_ohm)
        if impedance.real <= 0:
            raise ValueError("inductor one-port impedance must have positive resistance")
        frequencies.append(float(sample))
        reactances.append(impedance.imag)
        qualities.append(impedance.imag / impedance.real)
        inductances.append(impedance.imag / (2 * math.pi * sample))
    if frequencies[0] > band_low_hz or frequencies[-1] < band_high_hz:
        raise ValueError("inductor characterization does not cover the design band")

    def at(values: list[float], target: float) -> float:
        index = bisect_left(frequencies, target)
        if index < len(frequencies) and math.isclose(frequencies[index], target, rel_tol=1e-12):
            return values[index]
        if index == 0 or index == len(frequencies):
            raise ValueError("inductor characterization lacks a requested frequency")
        fraction = (target - frequencies[index - 1]) / (frequencies[index] - frequencies[index - 1])
        return values[index - 1] + fraction * (values[index] - values[index - 1])

    band_reactances = [at(reactances, band_low_hz), at(reactances, band_high_hz)]
    band_q = [at(qualities, band_low_hz), at(qualities, band_high_hz)]
    for sample, reactance, quality in zip(frequencies, reactances, qualities, strict=True):
        if band_low_hz < sample < band_high_hz:
            band_reactances.append(reactance)
            band_q.append(quality)
    inductive_in_band = all(value > 0 for value in band_reactances)
    inductive_through_band = inductive_in_band and all(
        reactance > 0 for sample, reactance in zip(frequencies, reactances, strict=True)
        if sample <= band_high_hz
    )
    srf_hz = None
    for index in range(1, len(frequencies)):
        if reactances[index - 1] > 0 >= reactances[index]:
            fraction = reactances[index - 1] / (reactances[index - 1] - reactances[index])
            srf_hz = frequencies[index - 1] + fraction * (frequencies[index] - frequencies[index - 1])
            break
    srf_evidence_hz = srf_hz if srf_hz is not None else frequencies[-1]
    q_min = min(band_q) if inductive_in_band else None
    eligible_response = (
        inductive_through_band and q_min is not None and q_min >= minimum_q
        and srf_evidence_hz >= band_high_hz * minimum_srf_ratio
    )
    return {
        "status": "response_screen_pass" if eligible_response else "response_screen_fail",
        "band_low_hz": band_low_hz, "band_high_hz": band_high_hz,
        "minimum_q_required": minimum_q, "minimum_srf_ratio_required": minimum_srf_ratio,
        "minimum_q_in_band": q_min,
        "effective_l_at_center_h": at(inductances, (band_low_hz + band_high_hz) / 2),
        "observed_srf_hz": srf_hz,
        "srf_screen_frequency_hz": srf_evidence_hz,
        "srf_evidence_kind": "observed_zero_crossing" if srf_hz is not None else "sweep_lower_bound",
        "inductive_in_band": inductive_in_band,
        "inductive_through_band": inductive_through_band,
        "sample_count": len(frequencies),
        "note": "One-port sampled response screen only; technology provenance and coupling are separate gates.",
    }
