from __future__ import annotations

import math
import random


def sample_teaching_stage2(seed: int, budget: int) -> list[dict[str, float]]:
    """Return a reproducible, bounded teaching-only Lg/Ls random baseline."""
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if type(budget) is not int or not 1 <= budget <= 12:
        raise ValueError("teaching Stage 2 budget must be 1..12")
    rng = random.Random(seed)
    points = []
    for _ in range(budget):
        lgs_nh = round(rng.uniform(0.7, 1.3), 6)
        lss_ph = round(rng.uniform(180.0, 320.0), 6)
        if not all(math.isfinite(value) for value in (lgs_nh, lss_ph)):
            raise ValueError("random teaching point is nonfinite")
        points.append({"lgs_nh": lgs_nh, "lss_ph": lss_ph})
    return points
