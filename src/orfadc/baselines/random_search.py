from __future__ import annotations

import random


def random_power_ratios(stages: int = 3) -> list[float]:
    values = [random.random() for _ in range(stages)]
    total = sum(values)
    return [value / total for value in values]

