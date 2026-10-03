from __future__ import annotations

import pytest

from orfadc.cadence.stability_metrics import rollett_k_and_delta, summarize_sampled_stability


def test_rollett_k_and_delta_known_values() -> None:
    k, delta = rollett_k_and_delta(0.1 + 0j, 2 + 0j, 0.01 + 0j, 0.2 + 0j)
    assert k == pytest.approx(23.75)
    assert delta == pytest.approx(0)
    stable = summarize_sampled_stability([0.1 + 0j], [2 + 0j], [0.01 + 0j], [0.2 + 0j])
    assert stable["unconditionally_stable_on_sampled_grid"] is True


def test_rollett_k_below_one_is_not_unconditional() -> None:
    k, delta = rollett_k_and_delta(0.8 + 0j, 2 + 0j, 0.3 + 0j, 0.4 + 0j)
    assert k == pytest.approx(0.232)
    assert delta == pytest.approx(0.28)
    result = summarize_sampled_stability([0.8 + 0j], [2 + 0j], [0.3 + 0j], [0.4 + 0j])
    assert result["unconditionally_stable_on_sampled_grid"] is False


def test_unilateral_sample_is_indeterminate() -> None:
    k, delta = rollett_k_and_delta(0.1 + 0j, 2 + 0j, 0j, 0.2 + 0j)
    assert k is None
    assert delta == pytest.approx(0.02)
    result = summarize_sampled_stability([0.1 + 0j], [2 + 0j], [0j], [0.2 + 0j])
    assert result["minimum_k"] is None
    assert result["unconditionally_stable_on_sampled_grid"] is False


def test_stability_rejects_bad_traces() -> None:
    with pytest.raises(ValueError, match="aligned"):
        summarize_sampled_stability([0.1 + 0j], [], [0.01 + 0j], [0.2 + 0j])
    with pytest.raises(ValueError, match="finite"):
        rollett_k_and_delta(complex(float("nan"), 0), 1 + 0j, 0.1 + 0j, 0.1 + 0j)
