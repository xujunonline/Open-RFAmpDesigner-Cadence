from __future__ import annotations

import math

from orfadc.cadence.resource_guard import available_physical_memory_gb


def test_available_physical_memory_reports_finite_positive_host_value() -> None:
    available = available_physical_memory_gb()
    assert math.isfinite(available) and available > 0
