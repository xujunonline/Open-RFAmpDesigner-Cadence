from __future__ import annotations

import math

import pytest

from orfadc.tools.stage2_ga import TeachingStage2GA


@pytest.mark.parametrize("seed,budget", ((0, 4), (17, 8), (23, 12)))
def test_ga_is_seeded_bounded_and_replayable(seed: int, budget: int) -> None:
    runs = []
    for _ in range(2):
        ga = TeachingStage2GA(seed, budget)
        points = []
        for index in range(budget):
            point = ga.ask()
            assert 0.7 <= point["lgs_nh"] <= 1.3
            assert 180 <= point["lss_ph"] <= 320
            assert ga.generation == index // 2
            points.append(point)
            ga.tell(float(budget - index))
        assert ga.evaluations_used == budget
        assert math.isfinite(ga.best_cost)
        with pytest.raises(RuntimeError):
            ga.ask()
        runs.append(points)
    assert runs[0] == runs[1]


def test_ga_enforces_ask_tell_and_numeric_contract() -> None:
    for seed, budget in ((-1, 4), (True, 4), (0, 3), (0, 5), (0, 14)):
        with pytest.raises(ValueError):
            TeachingStage2GA(seed, budget)
    ga = TeachingStage2GA(1, 4)
    with pytest.raises(RuntimeError):
        ga.tell(1.0)
    ga.ask()
    with pytest.raises(RuntimeError):
        ga.ask()
    for invalid in (-1.0, math.nan, math.inf, True):
        with pytest.raises(ValueError):
            ga.tell(invalid)
    ga.tell(1.0)
    assert ga.evaluations_used == 1
