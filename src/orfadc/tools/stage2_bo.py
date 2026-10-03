from __future__ import annotations

import math

from .stage2_sampling import sample_teaching_stage2


class TeachingStage2BO:
    """Bounded skopt GP/EI ask-tell controller for the MOS1 teaching domain."""

    def __init__(self, seed: int, budget: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("BO seed must be a nonnegative integer")
        if type(budget) is not int or not 4 <= budget <= 12:
            raise ValueError("teaching BO budget must be 4..12")
        try:
            import skopt
            from skopt import Optimizer
        except ImportError as exc:
            raise RuntimeError("scikit-optimize is required for the BO baseline") from exc
        if skopt.__version__ != "0.10.2":
            raise RuntimeError("BO replay requires scikit-optimize 0.10.2")
        self.seed = seed
        self.budget = budget
        self.version = skopt.__version__
        self.initial_points = sample_teaching_stage2(seed, 2)
        self.optimizer = Optimizer(
            [(0.7, 1.3), (180.0, 320.0)], base_estimator="GP",
            n_initial_points=2, acq_func="EI", acq_optimizer="sampling",
            acq_optimizer_kwargs={"n_points": 256}, random_state=seed,
        )
        self.evaluations_used = 0
        self.best_cost = math.inf
        self._pending: dict[str, float] | None = None

    def ask(self) -> dict[str, float]:
        if self._pending is not None or self.evaluations_used >= self.budget:
            raise RuntimeError("BO needs its previous score or exhausted its budget")
        if self.evaluations_used < 2:
            point = self.initial_points[self.evaluations_used].copy()
        else:
            lgs_nh, lss_ph = self.optimizer.ask()
            point = {"lgs_nh": round(float(lgs_nh), 6),
                     "lss_ph": round(float(lss_ph), 6)}
        if not 0.7 <= point["lgs_nh"] <= 1.3 or not 180 <= point["lss_ph"] <= 320:
            raise ValueError("BO proposal is outside the teaching search bounds")
        self._pending = point
        return point.copy()

    def tell(self, cost: float) -> None:
        if self._pending is None:
            raise RuntimeError("BO has no pending proposal")
        if type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0:
            raise ValueError("BO score must be finite and nonnegative")
        self.optimizer.tell([self._pending["lgs_nh"], self._pending["lss_ph"]], float(cost))
        self.best_cost = min(self.best_cost, float(cost))
        self.evaluations_used += 1
        self._pending = None
