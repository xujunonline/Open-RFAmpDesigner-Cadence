from __future__ import annotations

import math
import random


class TeachingStage2SA:
    """Seeded teaching SA over the same two normalized matching variables."""

    def __init__(self, seed: int, budget: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("SA seed must be a nonnegative integer")
        if type(budget) is not int or not 4 <= budget <= 12:
            raise ValueError("teaching SA budget must be 4..12")
        self.seed = seed
        self.budget = budget
        self.rng = random.Random(seed)
        self.evaluations_used = 0
        self.current_point: dict[str, float] | None = None
        self.current_cost = math.inf
        self.best_point: dict[str, float] | None = None
        self.best_cost = math.inf
        self._proposal: dict[str, float] | None = None
        self.temperature = 0.0

    def ask(self) -> dict[str, float]:
        if self._proposal is not None or self.evaluations_used >= self.budget:
            raise RuntimeError("SA needs the previous score or has exhausted its budget")
        if self.current_point is None:
            point = {
                "lgs_nh": round(self.rng.uniform(0.7, 1.3), 6),
                "lss_ph": round(self.rng.uniform(180.0, 320.0), 6),
            }
            self.temperature = 0.0
        else:
            self.temperature = 500.0 * 0.65 ** (self.evaluations_used - 1)
            x = (self.current_point["lgs_nh"] - 0.7) / 0.6
            y = (self.current_point["lss_ph"] - 180.0) / 140.0
            x = max(0.0, min(1.0, x + self.rng.uniform(-0.25, 0.25)))
            y = max(0.0, min(1.0, y + self.rng.uniform(-0.25, 0.25)))
            point = {"lgs_nh": round(0.7 + 0.6 * x, 6),
                     "lss_ph": round(180.0 + 140.0 * y, 6)}
        self._proposal = point
        return point.copy()

    def tell(self, cost: float) -> bool:
        if self._proposal is None:
            raise RuntimeError("SA has no pending proposal")
        if type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0:
            raise ValueError("SA score must be finite and nonnegative")
        accepted = (
            self.current_point is None or cost <= self.current_cost
            or self.rng.random() < math.exp(-(cost - self.current_cost) / self.temperature)
        )
        if accepted:
            self.current_point = self._proposal.copy()
            self.current_cost = float(cost)
        if cost < self.best_cost:
            self.best_point = self._proposal.copy()
            self.best_cost = float(cost)
        self.evaluations_used += 1
        self._proposal = None
        return accepted
