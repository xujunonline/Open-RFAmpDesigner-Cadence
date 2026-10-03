from __future__ import annotations

import pytest

from orfadc.experiments.audit_teaching_oa_crosscheck import compare_samples


def test_crosscheck_matches_high_precision_samples() -> None:
    frequency_delta, value_delta = compare_samples(
        [1e9, 2e9], [0.1 + 0.2j, 0.4 + 0.1j],
        [1e9 + 1e-5, 2e9 - 2e-5], [0.1 + 0.2j, 0.4 + 0.1j],
        name="s21", value_tolerance=1e-8,
    )
    assert frequency_delta == pytest.approx(2e-5, abs=1e-7)
    assert value_delta == 0


def test_crosscheck_rejects_changed_frequency_or_s_parameter() -> None:
    with pytest.raises(ValueError, match="frequency grids differ"):
        compare_samples([1e9], [0.5 + 0j], [1e9 + 1000], [0.5 + 0j],
                        name="s21", value_tolerance=1e-8)
    with pytest.raises(ValueError, match="PSFASCII and high-precision OCEAN"):
        compare_samples([1e9], [0.5 + 0j], [1e9], [0.501 + 0j],
                        name="s21", value_tolerance=1e-8)
    with pytest.raises(ValueError, match="point counts differ"):
        compare_samples([1e9, 2e9], [0.5 + 0j], [1e9, 2e9], [0.5 + 0j],
                        name="s21", value_tolerance=1e-8)
