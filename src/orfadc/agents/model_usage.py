from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _rate(value: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("price rates must be decimal strings")
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid price rate") from exc
    if not rate.is_finite() or not 0 <= rate <= 1_000_000:
        raise ValueError("price rate must be finite and nonnegative")
    return rate


@dataclass(frozen=True)
class ModelPriceSnapshot:
    """Explicit USD per million token rates; never derived from a live price page."""

    model: str
    version: str
    source_url: str
    input_usd_per_million: str
    cached_input_usd_per_million: str
    cache_write_usd_per_million: str
    output_usd_per_million: str

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not _ID.fullmatch(self.model):
            raise ValueError("price model must be an explicit model identifier")
        if not isinstance(self.version, str) or not _ID.fullmatch(self.version):
            raise ValueError("price version must be an explicit snapshot identifier")
        if not isinstance(self.source_url, str) or not self.source_url.startswith("https://"):
            raise ValueError("price source must be an HTTPS URL")
        for value in (self.input_usd_per_million,
                      self.cached_input_usd_per_million,
                      self.cache_write_usd_per_million,
                      self.output_usd_per_million):
            _rate(value)


def price_usage_event(event: dict[str, Any], snapshot: ModelPriceSnapshot) -> dict[str, str | None]:
    """Price complete server-reported counts only; unavailable inputs stay unpriced."""
    result: dict[str, str | None] = {
        "status": "unpriced", "reason": None, "cost_usd": None,
        "price_version": snapshot.version,
    }
    if event.get("model_reported") != snapshot.model:
        result["reason"] = "model_mismatch_or_unreported"
        return result
    counts = [event.get(key) for key in (
        "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens",
    )]
    if any(type(value) is not int or value < 0 for value in counts):
        result["reason"] = "usage_unavailable"
        return result
    input_tokens, cached_tokens, output_tokens, total_tokens = counts
    if cached_tokens > input_tokens or total_tokens != input_tokens + output_tokens:
        result["reason"] = "usage_inconsistent"
        return result
    write_tokens = event.get("cache_write_input_tokens")
    if type(write_tokens) is not int or write_tokens < 0:
        if _rate(snapshot.cache_write_usd_per_million) != _rate(snapshot.input_usd_per_million):
            result["reason"] = "cache_write_usage_unavailable"
            return result
        write_tokens = 0
    if cached_tokens + write_tokens > input_tokens:
        result["reason"] = "usage_inconsistent"
        return result
    amount = (
        Decimal(input_tokens - cached_tokens - write_tokens) * _rate(snapshot.input_usd_per_million)
        + Decimal(cached_tokens) * _rate(snapshot.cached_input_usd_per_million)
        + Decimal(write_tokens) * _rate(snapshot.cache_write_usd_per_million)
        + Decimal(output_tokens) * _rate(snapshot.output_usd_per_million)
    ) / Decimal(1_000_000)
    result.update(status="priced", cost_usd=str(amount))
    return result
