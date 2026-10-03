from __future__ import annotations

import math
import random


class TeachingStage2GA:
    """Two-individual, seeded teaching GA over normalized LGS/LSS."""

    def __init__(self, seed: int, budget: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("GA seed must be a nonnegative integer")
        if type(budget) is not int or not 4 <= budget <= 12 or budget % 2:
            raise ValueError("teaching GA budget must be even and in 4..12")
        self.seed = seed
        self.budget = budget
        self.rng = random.Random(seed)
        self.positions = [[self.rng.random(), self.rng.random()] for _ in range(2)]
        self.generation_costs = [math.inf, math.inf]
        self.evaluations_used = 0
        self.best_point: dict[str, float] | None = None
        self.best_cost = math.inf
        self._awaiting_score = False

    @property
    def generation(self) -> int:
        return self.evaluations_used // 2

    def ask(self) -> dict[str, float]:
        if self._awaiting_score or self.evaluations_used >= self.budget:
            raise RuntimeError("GA needs the previous score or has exhausted its budget")
        self._awaiting_score = True
        x, y = self.positions[self.evaluations_used % 2]
        return {"lgs_nh": round(0.7 + 0.6 * x, 6),
                "lss_ph": round(180.0 + 140.0 * y, 6)}

    def tell(self, cost: float) -> None:
        if not self._awaiting_score:
            raise RuntimeError("GA has no pending proposal")
        if type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0:
            raise ValueError("GA score must be finite and nonnegative")
        index = self.evaluations_used % 2
        self.generation_costs[index] = float(cost)
        point = self.positions[index]
        if cost < self.best_cost:
            self.best_cost = float(cost)
            self.best_point = {"lgs_nh": round(0.7 + 0.6 * point[0], 6),
                               "lss_ph": round(180.0 + 140.0 * point[1], 6)}
        self.evaluations_used += 1
        self._awaiting_score = False
        if self.evaluations_used % 2 == 0 and self.evaluations_used < self.budget:
            self._advance_generation()

    def _advance_generation(self) -> None:
        better = 0 if self.generation_costs[0] <= self.generation_costs[1] else 1
        a, b = self.positions[better], self.positions[1 - better]
        children = []
        for _ in range(2):
            alpha = self.rng.uniform(0.55, 0.9)
            children.append([
                max(0.0, min(1.0, alpha * a[axis] + (1 - alpha) * b[axis]
                             + self.rng.uniform(-0.2, 0.2)))
                for axis in range(2)
            ])
        self.positions = children
        self.generation_costs = [math.inf, math.inf]
