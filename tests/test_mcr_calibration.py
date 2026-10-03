from __future__ import annotations

import math

import pytest

from orfadc.experiments.run_mcr_calibration import compare_mcr_trace, render_mcr_netlist
from orfadc.tools.mcr_lumped import lumped_mcr_response, symmetric_parallel_mcr


def _model(k: float = 0.4):
    return symmetric_parallel_mcr(2 * math.pi * 30e9, 3, 100e-15, k)


def test_render_mcr_netlist_has_fixed_topology_and_validated_values() -> None:
    netlist = render_mcr_netlist(_model(), 20e9, 40e9, 41)
    assert "K12 mutual_inductor coupling=0.40000000000000002 ind1=L1 ind2=L2" in netlist
    assert "IEXC (0 n1) isource dc=0 mag=1" in netlist
    assert "ac ac start=20000000000 stop=40000000000 lin=40" in netlist
    with pytest.raises(ValueError, match="increasing positive"):
        render_mcr_netlist(_model(), 40e9, 20e9, 41)
    with pytest.raises(ValueError, match="2..401"):
        render_mcr_netlist(_model(), 20e9, 40e9, 402)


def test_compare_exact_solution_and_frequency_guard() -> None:
    model = _model()
    frequencies = [20e9, 30e9, 40e9]
    analytic = [lumped_mcr_response(f, model) for f in frequencies]
    n1 = (frequencies, [1 / row.input_admittance_s for row in analytic])
    n2 = (frequencies, [row.transfer_impedance_ohm for row in analytic])
    rows, summary = compare_mcr_trace(model, n1, n2, start_hz=20e9, stop_hz=40e9, points=3)
    assert len(rows) == 3
    assert summary["max_v1_error_normalized"] == 0
    assert summary["max_z21_error_normalized"] == 0
    assert summary["max_paper_z21_error_normalized"] < 1e-12
    with pytest.raises(ValueError, match="frequency grid"):
        compare_mcr_trace(model, ([20e9, 31e9, 40e9], n1[1]), ([20e9, 31e9, 40e9], n2[1]),
                          start_hz=20e9, stop_hz=40e9, points=3)
    with pytest.raises(ValueError, match="mismatched frequency axes"):
        compare_mcr_trace(model, n1, (frequencies[:-1], n2[1][:-1]),
                          start_hz=20e9, stop_hz=40e9, points=3)


def test_compare_detects_coupling_sign_mismatch() -> None:
    model = _model()
    frequencies = [20e9, 30e9, 40e9]
    analytic = [lumped_mcr_response(f, model) for f in frequencies]
    _, summary = compare_mcr_trace(
        model,
        (frequencies, [1 / row.input_admittance_s for row in analytic]),
        (frequencies, [-row.transfer_impedance_ohm for row in analytic]),
        start_hz=20e9, stop_hz=40e9, points=3,
    )
    assert summary["max_z21_error_normalized"] == pytest.approx(2)
    assert summary["max_paper_z21_error_normalized"] == pytest.approx(2)


def test_compare_zero_coupling_and_nonfinite_trace() -> None:
    model = _model(0)
    frequencies = [20e9, 30e9, 40e9]
    analytic = [lumped_mcr_response(f, model) for f in frequencies]
    n1 = (frequencies, [1 / row.input_admittance_s for row in analytic])
    rows, summary = compare_mcr_trace(model, n1, (frequencies, [0j] * 3),
                                      start_hz=20e9, stop_hz=40e9, points=3)
    assert all(row["z21_error_ohm"] == 0 for row in rows)
    assert summary["max_z21_error_normalized"] == 0
    assert summary["max_paper_z21_error_normalized"] == 0
    with pytest.raises(ValueError, match="nonfinite"):
        compare_mcr_trace(model, n1, (frequencies, [0j, complex(float("nan"), 0), 0j]),
                          start_hz=20e9, stop_hz=40e9, points=3)
