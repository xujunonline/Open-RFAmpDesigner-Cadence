from __future__ import annotations

import pytest

from orfadc.agents.model_usage import ModelPriceSnapshot, price_usage_event


def _snapshot(**changes) -> ModelPriceSnapshot:
    fields = {
        "model": "mock-model-1",
        "version": "test-2026-09-28",
        "source_url": "https://example.org/mock-prices",
        "input_usd_per_million": "2.00",
        "cached_input_usd_per_million": "0.50",
        "cache_write_usd_per_million": "2.00",
        "output_usd_per_million": "8.00",
    }
    fields.update(changes)
    return ModelPriceSnapshot(**fields)


def _event(**changes):
    event = {
        "model_reported": "mock-model-1",
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "output_tokens": 30,
        "total_tokens": 150,
    }
    event.update(changes)
    return event


def test_explicit_price_snapshot_distinguishes_cached_input() -> None:
    priced = price_usage_event(_event(), _snapshot())
    assert priced == {
        "status": "priced", "reason": None, "cost_usd": "0.00045",
        "price_version": "test-2026-09-28",
    }


def test_cache_write_is_not_charged_twice_and_missing_write_count_blocks_different_rate() -> None:
    snapshot = _snapshot(cache_write_usd_per_million="2.50")
    assert price_usage_event(_event(cache_write_input_tokens=None), snapshot)["reason"] == "cache_write_usage_unavailable"
    priced = price_usage_event(_event(cache_write_input_tokens=10), snapshot)
    assert priced["cost_usd"] == "0.000455"
    assert price_usage_event(_event(cache_write_input_tokens=110), snapshot)["reason"] == "usage_inconsistent"


@pytest.mark.parametrize("changes,reason", [
    ({"model_reported": None}, "model_mismatch_or_unreported"),
    ({"model_reported": "different-model"}, "model_mismatch_or_unreported"),
    ({"cached_input_tokens": None}, "usage_unavailable"),
    ({"total_tokens": None}, "usage_unavailable"),
    ({"output_tokens": True}, "usage_unavailable"),
    ({"cached_input_tokens": 121}, "usage_inconsistent"),
    ({"total_tokens": 151}, "usage_inconsistent"),
])
def test_missing_or_inconsistent_evidence_is_unpriced(changes, reason) -> None:
    priced = price_usage_event(_event(**changes), _snapshot())
    assert priced["status"] == "unpriced"
    assert priced["reason"] == reason
    assert priced["cost_usd"] is None


@pytest.mark.parametrize("changes", [
    {"model": "bad/model"},
    {"version": ""},
    {"source_url": "file:///private/prices"},
    {"input_usd_per_million": "-1"},
    {"cached_input_usd_per_million": "NaN"},
    {"cache_write_usd_per_million": "Infinity"},
    {"output_usd_per_million": 8.0},
])
def test_invalid_snapshot_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        _snapshot(**changes)
