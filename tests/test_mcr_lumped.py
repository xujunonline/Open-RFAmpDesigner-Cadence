from __future__ import annotations

import math

import pytest

from orfadc.tools.mcr_lumped import SymmetricParallelMCR, lumped_mcr_response, symmetric_parallel_mcr


def test_symmetric_parallel_mapping_has_requested_uncoupled_resonance_and_q() -> None:
    omega0 = 2 * math.pi * 10e9
    q0 = 3.0
    model = symmetric_parallel_mcr(omega0, q0, 20e-15, 0.0)
    assert model.inductance_h == pytest.approx(1 / (omega0**2 * model.capacitance_f))
    assert model.resistance_ohm * omega0 * model.capacitance_f == pytest.approx(q0)
    response = lumped_mcr_response(10e9, model)
    assert response.input_admittance_s.real == pytest.approx(1 / model.resistance_ohm)
    assert response.input_admittance_s.imag == pytest.approx(0, abs=1e-12)
    assert response.transfer_impedance_ohm == 0j


def test_coupled_response_is_finite_and_nonzero() -> None:
    model = symmetric_parallel_mcr(2 * math.pi * 10e9, 3.0, 20e-15, 0.4)
    assert model.mutual_inductance_h == pytest.approx(0.4 * model.inductance_h)
    response = lumped_mcr_response(10e9, model)
    assert abs(response.transfer_impedance_ohm) > 0
    assert response.input_admittance_s.real > 0


def test_documented_30ghz_mapping_example() -> None:
    model = symmetric_parallel_mcr(2 * math.pi * 30e9, 3.0, 100e-15, 0.4)
    assert model.inductance_h == pytest.approx(281.45e-12, rel=1e-4)
    assert model.resistance_ohm == pytest.approx(159.15, rel=1e-4)
    assert model.mutual_inductance_h == pytest.approx(112.58e-12, rel=1e-4)


@pytest.mark.parametrize("kwargs", [
    {"omega0_rad_s": 0}, {"q0": float("nan")},
    {"capacitance_f": 0}, {"coupling_k": 1}, {"coupling_k": -0.1},
])
def test_mapping_rejects_invalid_parameters(kwargs: dict[str, float]) -> None:
    values = dict(omega0_rad_s=2 * math.pi * 10e9, q0=3.0,
                  capacitance_f=20e-15, coupling_k=0.4)
    values.update(kwargs)
    with pytest.raises(ValueError):
        symmetric_parallel_mcr(**values)


def test_lumped_response_rejects_invalid_frequency() -> None:
    model = symmetric_parallel_mcr(2 * math.pi * 10e9, 3.0, 20e-15, 0.4)
    with pytest.raises(ValueError, match="frequency_hz"):
        lumped_mcr_response(0, model)


def test_manual_model_cannot_bypass_passive_parameter_checks() -> None:
    with pytest.raises(ValueError, match="L, C and R"):
        SymmetricParallelMCR(-1e-9, 20e-15, 100, 0, 0)
    with pytest.raises(ValueError, match="mutual inductance"):
        SymmetricParallelMCR(1e-9, 20e-15, 100, 0, 0.4)
