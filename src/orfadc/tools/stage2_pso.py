from __future__ import annotations

import math
import random


class TeachingStage2PSO:
    """Small deterministic PSO in normalized LGS/LSS coordinates."""

    def __init__(self, seed: int, budget: int, *, particles: int = 2) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("PSO seed must be a nonnegative integer")
        if type(budget) is not int or not 4 <= budget <= 12:
            raise ValueError("teaching PSO budget must be 4..12")
        if type(particles) is not int or not 2 <= particles <= 4 or budget % particles:
            raise ValueError("teaching PSO requires 2..4 particles and complete generations")
        self.seed = seed
        self.budget = budget
        self.particles = particles
        self.rng = random.Random(seed)
        self.positions = [[self.rng.random(), self.rng.random()] for _ in range(particles)]
        self.velocities = [[self.rng.uniform(-0.2, 0.2) for _ in range(2)] for _ in range(particles)]
        self.personal_best_positions = [point.copy() for point in self.positions]
        self.personal_best_costs = [math.inf] * particles
        self.global_best_position: list[float] | None = None
        self.global_best_cost = math.inf
        self.evaluations_used = 0
        self._awaiting_score = False

    def ask(self) -> dict[str, float]:
        if self._awaiting_score or self.evaluations_used >= self.budget:
            raise RuntimeError("PSO needs the previous score or has exhausted its budget")
        self._awaiting_score = True
        x, y = self.positions[self.evaluations_used % self.particles]
        return {"lgs_nh": round(0.7 + 0.6 * x, 6), "lss_ph": round(180.0 + 140.0 * y, 6)}

    def tell(self, cost: float) -> None:
        if not self._awaiting_score:
            raise RuntimeError("PSO has no pending proposal")
        if type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0:
            raise ValueError("PSO score must be finite and nonnegative")
        index = self.evaluations_used % self.particles
        if cost < self.personal_best_costs[index]:
            self.personal_best_costs[index] = float(cost)
            self.personal_best_positions[index] = self.positions[index].copy()
        if cost < self.global_best_cost:
            self.global_best_cost = float(cost)
            self.global_best_position = self.positions[index].copy()
        self.evaluations_used += 1
        self._awaiting_score = False
        if self.evaluations_used % self.particles == 0 and self.evaluations_used < self.budget:
            self._advance_swarm()

    def _advance_swarm(self) -> None:
        if self.global_best_position is None:
            raise RuntimeError("PSO cannot advance without a measured best point")
        for index in range(self.particles):
            for axis in range(2):
                current = self.positions[index][axis]
                velocity = (
                    0.55 * self.velocities[index][axis]
                    + 1.4 * self.rng.random() * (self.personal_best_positions[index][axis] - current)
                    + 1.4 * self.rng.random() * (self.global_best_position[axis] - current)
                )
                velocity = max(-0.25, min(0.25, velocity))
                self.velocities[index][axis] = velocity
                self.positions[index][axis] = max(0.0, min(1.0, current + velocity))
