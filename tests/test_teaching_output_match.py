from __future__ import annotations

import math

import pytest

from orfadc.tools.impedance_matching import ideal_shunt_l_series_c_output_match


def test_ideal_output_match_reconstructs_known_parallel_rl() -> None:
    omega = 2 * math.pi * 10e9
    resistance = 14_000.0
    l_baseline = 2e-9
    c_baseline = 5e-12
    z_shunt = 1 / (1 / resistance + 1 / (1j * omega * l_baseline))
    z_port = z_shunt + 1 / (1j * omega * c_baseline)
    gamma = (z_port - 50) / (z_port + 50)
    result = ideal_shunt_l_series_c_output_match(
        gamma, frequency_hz=10e9, baseline_l_h=l_baseline,
        baseline_c_f=c_baseline,
    )
    assert result["inferred_parallel_r_ohm"] == pytest.approx(resistance)
    assert result["inferred_baseline_l_nh"] == pytest.approx(2.0)
    l_target = result["suggested_ldd_nh"] * 1e-9
    c_target = result["suggested_cblock_ff"] * 1e-15
    z_matched = 1 / (1 / resistance + 1 / (1j * omega * l_target)) + 1 / (1j * omega * c_target)
    assert z_matched == pytest.approx(50 + 0j, rel=1e-12, abs=1e-10)


def test_ideal_output_match_rejects_bad_provenance_or_inputs() -> None:
    with pytest.raises(ValueError, match="S22"):
        ideal_shunt_l_series_c_output_match(complex(float("nan"), 0), frequency_hz=10e9,
                                            baseline_l_h=2e-9, baseline_c_f=5e-12)
    with pytest.raises(ValueError, match="baseline shunt inductor"):
        ideal_shunt_l_series_c_output_match(0j, frequency_hz=10e9,
                                            baseline_l_h=2e-9, baseline_c_f=5e-12)
