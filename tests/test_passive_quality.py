from __future__ import annotations

import math

import pytest

from orfadc.cadence.passive_quality import oneport_impedance, summarize_inductor_oneport


def _rlc_response(*, stop_ghz: float = 30.0) -> tuple[list[float], list[complex]]:
    frequencies = [0.5e9 + index * 50e6 for index in range(int((stop_ghz - 0.5) / 0.05) + 1)]
    reflection = []
    for sample in frequencies:
        omega = 2 * math.pi * sample
        series = 2 + 1j * omega * 1e-9
        impedance = 1 / (1 / series + 1j * omega * 100e-15)
        reflection.append((impedance - 50) / (impedance + 50))
    return frequencies, reflection


def test_one_port_impedance_roundtrip_and_singularity() -> None:
    impedance = 2 + 1j * 100
    gamma = (impedance - 50) / (impedance + 50)
    assert oneport_impedance(gamma, 50) == pytest.approx(impedance)
    with pytest.raises(ValueError, match="open circuit"):
        oneport_impedance(1 + 0j, 50)


def test_inductor_quality_screen_finds_rlc_srf_and_band_q() -> None:
    frequencies, reflection = _rlc_response()
    result = summarize_inductor_oneport(
        frequencies, reflection, reference_ohm=50,
        band_low_hz=8e9, band_high_hz=12e9,
        minimum_q=15, minimum_srf_ratio=1.2,
    )
    expected_srf = math.sqrt(1 / (1e-9 * 100e-15) - (2 / 1e-9) ** 2) / (2 * math.pi)
    assert result["status"] == "response_screen_pass"
    assert result["minimum_q_in_band"] == pytest.approx(16.2524937569, rel=1e-5)
    assert result["observed_srf_hz"] == pytest.approx(expected_srf, rel=0.002)
    assert result["srf_evidence_kind"] == "observed_zero_crossing"
    assert result["effective_l_at_center_h"] == pytest.approx(1.65049952233e-9, rel=1e-5)


def test_inductor_quality_screen_fails_high_q_or_srf_requirement() -> None:
    frequencies, reflection = _rlc_response()
    common = dict(reference_ohm=50, band_low_hz=8e9, band_high_hz=12e9)
    assert summarize_inductor_oneport(
        frequencies, reflection, minimum_q=17, minimum_srf_ratio=1.2, **common,
    )["status"] == "response_screen_fail"
    assert summarize_inductor_oneport(
        frequencies, reflection, minimum_q=15, minimum_srf_ratio=1.5, **common,
    )["status"] == "response_screen_fail"


def test_inductor_quality_screen_uses_sweep_lower_bound_when_srf_unobserved() -> None:
    frequencies, reflection = _rlc_response(stop_ghz=13.0)
    result = summarize_inductor_oneport(
        frequencies, reflection, reference_ohm=50,
        band_low_hz=8e9, band_high_hz=12e9,
        minimum_q=15, minimum_srf_ratio=1.2,
    )
    assert result["observed_srf_hz"] is None
    assert result["srf_evidence_kind"] == "sweep_lower_bound"
    assert result["status"] == "response_screen_fail"


def test_inductor_quality_rejects_disordered_and_uncovered_grid() -> None:
    frequencies, reflection = _rlc_response()
    with pytest.raises(ValueError, match="strictly increasing"):
        summarize_inductor_oneport(
            list(reversed(frequencies)), reflection, reference_ohm=50,
            band_low_hz=8e9, band_high_hz=12e9, minimum_q=15, minimum_srf_ratio=1.2,
        )
    with pytest.raises(ValueError, match="cover"):
        summarize_inductor_oneport(
            frequencies[:100], reflection[:100], reference_ohm=50,
            band_low_hz=8e9, band_high_hz=12e9, minimum_q=15, minimum_srf_ratio=1.2,
        )
