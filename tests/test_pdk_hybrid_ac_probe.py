from __future__ import annotations

import math

import pytest

from orfadc.experiments.audit_pdk_hybrid_ac_probe import ac_voltage_steps


def _nodes() -> dict[str, complex]:
    return {
        "in": 1 + 0j, "d1": 0.5 + 0j,
        "g2p": 0.1 + 0j, "g2n": -0.1 + 0j,
        "d2p": 0.05 + 0j, "d2n": -0.05 + 0j,
        "g3p": 0.025 + 0j, "g3n": -0.025 + 0j,
        "d3p": 0.01 + 0j, "d3n": -0.01 + 0j,
        "outp": 0.005 + 0j, "outn": -0.005 + 0j,
    }


def test_ac_voltage_steps_telescope_to_overall_ratio() -> None:
    result = ac_voltage_steps(_nodes())
    assert math.isclose(result["first_stage"], 20 * math.log10(0.5))
    assert math.isclose(result["first_coupler"], 20 * math.log10(0.4))
    assert math.isclose(result["overall_voltage_db"], -40.0)
    assert math.isclose(sum(value for key, value in result.items() if key != "overall_voltage_db"), -40.0)


def test_ac_voltage_steps_rejects_missing_nonfinite_or_zero() -> None:
    missing = _nodes()
    del missing["outn"]
    with pytest.raises(ValueError, match="incomplete"):
        ac_voltage_steps(missing)
    invalid = _nodes()
    invalid["d1"] = complex(float("nan"), 0)
    with pytest.raises(ValueError, match="nonfinite"):
        ac_voltage_steps(invalid)
    zero = _nodes()
    zero["outp"] = zero["outn"]
    with pytest.raises(ValueError, match="zero"):
        ac_voltage_steps(zero)
