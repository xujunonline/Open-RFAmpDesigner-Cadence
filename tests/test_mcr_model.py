from __future__ import annotations

import math
from dataclasses import replace

import pytest

from orfadc.tools.mcr_lumped import lumped_mcr_response, symmetric_parallel_mcr
from orfadc.tools.mcr_model import MCRParameters, paper_equation_3, y11_dimensional_candidate


def _params(**overrides: float) -> MCRParameters:
    values = dict(
        coupling_k=0.4,
        omega0_rad_s=2 * math.pi * 10e9,
        q0=3.0,
        source_resistance_ohm=50.0,
        output_resistance_ohm=200.0,
        source_capacitance_f=20e-15,
        gm_s=0.01,
    )
    values.update(overrides)
    return MCRParameters(**values)


def test_paper_equation_3_matches_component_identities() -> None:
    params = _params()
    frequency = 10e9
    result = paper_equation_3(frequency, params)
    omega = 2 * math.pi * frequency
    assert result.load_resistance_ohm == pytest.approx(1 / result.y11_s.real)
    assert result.load_capacitance_f == pytest.approx(result.y11_s.imag / omega)
    assert result.load_resistance_ohm == pytest.approx(-700.0)
    assert result.load_capacitance_f == pytest.approx(-295.573307e-15, rel=1e-6)
    assert result.passive_parallel_rc is False
    assert result.normalized_v21_v_per_v == pytest.approx(result.i11_a_per_v * result.z21_ohm / 2)
    assert all(math.isfinite(part) for part in (
        result.y11_s.real, result.y11_s.imag, result.z21_ohm.real,
        result.z21_ohm.imag, result.normalized_v21_v_per_v.real,
    ))


def test_uncoupled_network_has_zero_transfer_and_gm_scales_current() -> None:
    uncoupled = paper_equation_3(10e9, _params(coupling_k=0.0))
    assert uncoupled.z21_ohm == 0j
    assert uncoupled.normalized_v21_v_per_v == 0j
    base = paper_equation_3(10e9, _params())
    doubled = paper_equation_3(10e9, replace(_params(), gm_s=0.02))
    assert doubled.i11_a_per_v == pytest.approx(2 * base.i11_a_per_v)
    assert doubled.normalized_v21_v_per_v == pytest.approx(2 * base.normalized_v21_v_per_v)


@pytest.mark.parametrize("k", [0.0, 0.2, 0.4, 0.7])
@pytest.mark.parametrize("frequency_ghz", [20.0, 30.0, 40.0])
def test_dimensional_y11_candidate_matches_project_lumped_network(k: float, frequency_ghz: float) -> None:
    omega0 = 2 * math.pi * 30e9
    model = symmetric_parallel_mcr(omega0, 3.0, 100e-15, k)
    params = _params(coupling_k=k, omega0_rad_s=omega0, q0=3.0,
                     source_resistance_ohm=model.resistance_ohm,
                     output_resistance_ohm=model.resistance_ohm,
                     source_capacitance_f=model.capacitance_f)
    corrected = y11_dimensional_candidate(frequency_ghz * 1e9, params)
    expected = lumped_mcr_response(frequency_ghz * 1e9, model).input_admittance_s
    assert corrected == pytest.approx(expected, rel=1e-12)
    if frequency_ghz == 30 and k == 0.4:
        assert abs(paper_equation_3(frequency_ghz * 1e9, params).y11_s - corrected) > 1e-3


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), 0, -1, True])
def test_invalid_frequency_rejected(invalid: float) -> None:
    with pytest.raises(ValueError, match="frequency_hz"):
        paper_equation_3(invalid, _params())
    with pytest.raises(ValueError, match="frequency_hz"):
        y11_dimensional_candidate(invalid, _params())


@pytest.mark.parametrize(
    "overrides", [{"coupling_k": 1.0}, {"q0": 0.0}, {"source_capacitance_f": -1e-15},
                  {"omega0_rad_s": float("nan")}, {"gm_s": False}],
)
def test_invalid_parameters_rejected(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        _params(**overrides)
