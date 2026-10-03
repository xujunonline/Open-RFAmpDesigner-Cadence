from __future__ import annotations

import math

import pytest

from orfadc.tools.stage2_pso import TeachingStage2PSO


def test_pso_is_bounded_seeded_and_score_adaptive() -> None:
    first = TeachingStage2PSO(17, 4)
    second = TeachingStage2PSO(17, 4)
    points = []
    for score in (3.0, 2.0, 1.0, 4.0):
        left = first.ask()
        right = second.ask()
        assert left == right
        assert 0.7 <= left["lgs_nh"] <= 1.3
        assert 180 <= left["lss_ph"] <= 320
        first.tell(score)
        second.tell(score)
        points.append(left)
    assert len(points) == 4 and first.evaluations_used == 4
    assert first.global_best_cost == 1.0
    with pytest.raises(RuntimeError, match="exhausted"):
        first.ask()

    low_first = TeachingStage2PSO(17, 4)
    low_second = TeachingStage2PSO(17, 4)
    for index in range(2):
        assert low_first.ask() == low_second.ask()
        low_first.tell((0.0, 10.0)[index])
        low_second.tell((10.0, 0.0)[index])
    assert low_first.ask() != low_second.ask()


def test_pso_rejects_invalid_budget_state_and_score() -> None:
    for args in ((True, 4, 2), (-1, 4, 2), (0, 3, 2), (0, 5, 2), (0, 4, 1)):
        with pytest.raises(ValueError):
            TeachingStage2PSO(args[0], args[1], particles=args[2])
    optimizer = TeachingStage2PSO(0, 4)
    with pytest.raises(RuntimeError, match="pending"):
        optimizer.tell(1.0)
    optimizer.ask()
    with pytest.raises(RuntimeError, match="previous score"):
        optimizer.ask()
    for value in (float("nan"), float("inf"), -1.0, True):
        with pytest.raises(ValueError, match="score"):
            optimizer.tell(value)
    optimizer.tell(0.0)
    assert math.isfinite(optimizer.global_best_cost)
