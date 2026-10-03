from __future__ import annotations

import math
from pathlib import Path

import pytest

from orfadc.cadence.noise_parameters import (
    NoiseParameterPoint, matched_load_transducer_gain, noise_factor_at_source,
    read_noise_parameter_points, source_reflection_from_admittance,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_rf_source_termination import render_source_termination_netlist


def test_noise_parameter_formula_and_passive_source_guard() -> None:
    point = NoiseParameterPoint(10e9, 2.0, 0.01, -0.002, 10.0, 2.052, 10 * math.log10(2.052))
    assert math.isclose(noise_factor_at_source(point, 0.01 - 0.002j), 2.0)
    assert math.isclose(noise_factor_at_source(point, 0.02 + 0j), 2.052)
    assert source_reflection_from_admittance(0.01 + 0j, 50) == pytest.approx(1 / 3)
    assert matched_load_transducer_gain(0.5 + 0j, 0.1 + 0j, 0j) == pytest.approx(0.01)
    for source in (0j, -0.01 + 0j, complex(float("nan"), 0)):
        with pytest.raises(ValueError):
            noise_factor_at_source(point, source)
        with pytest.raises(ValueError):
            source_reflection_from_admittance(source, 50)
    with pytest.raises(ValueError):
        matched_load_transducer_gain(0.5 + 0j, 0.1 + 0j, 1 + 0j)


def test_real_cadence_50ohm_noise_parameters_reproduce_f() -> None:
    path = (_PRIVATE_ROOT / "pdk_three_stage_fixed" /
            "rf_default_sp_20260926T231333Z_19c5f59b" / "sp.noise.sp")
    if not path.is_file():
        pytest.skip("private authorized RF noise archive is unavailable")
    points = read_noise_parameter_points(path)
    assert len(points) == 161
    assert max(abs(noise_factor_at_source(point, 0.02 + 0j) - point.measured_f) /
               point.measured_f for point in points) < 1e-12
    gamma_opt = source_reflection_from_admittance(points[80].yopt_s, 50)
    assert abs(gamma_opt) < 1


def test_source_termination_changes_only_unique_port_resistance() -> None:
    source = b"PORT1 (in 0) port r=50 num=1 type=sine\nR1 (in out) resistor r=100\n"
    assert render_source_termination_netlist(source, 100) == source.replace(b"r=50", b"r=100")
    for invalid in (50, 75, 100.0, True):
        with pytest.raises(ValueError):
            render_source_termination_netlist(source, invalid)
    with pytest.raises(ValueError):
        render_source_termination_netlist(source + source, 100)
