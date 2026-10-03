from __future__ import annotations

import math

import pytest

pytest.importorskip("skopt")

from orfadc.tools.stage2_bo import TeachingStage2BO
from orfadc.tools.stage2_sampling import sample_teaching_stage2


def test_bo_shared_initial_points_then_deterministic_gp_proposal() -> None:
    trajectories = []
    for _ in range(2):
        bo = TeachingStage2BO(seed=17, budget=4)
        points = []
        for score in (10300.0, 10100.0, 9900.0, 9800.0):
            point = bo.ask()
            assert 0.7 <= point["lgs_nh"] <= 1.3
            assert 180 <= point["lss_ph"] <= 320
            points.append(point)
            bo.tell(score)
        assert points[:2] == sample_teaching_stage2(17, 2)
        assert bo.best_cost == 9800.0
        with pytest.raises(RuntimeError, match="exhausted"):
            bo.ask()
        trajectories.append(points)
    assert trajectories[0] == trajectories[1]


def test_bo_rejects_invalid_state_and_score() -> None:
    for seed, budget in ((-1, 4), (True, 4), (1, 3), (1, 13)):
        with pytest.raises(ValueError):
            TeachingStage2BO(seed, budget)
    bo = TeachingStage2BO(1, 4)
    with pytest.raises(RuntimeError, match="no pending"):
        bo.tell(1.0)
    bo.ask()
    with pytest.raises(RuntimeError, match="previous score"):
        bo.ask()
    for bad in (-1.0, math.nan, math.inf, True):
        with pytest.raises(ValueError, match="finite and nonnegative"):
            bo.tell(bad)
    bo.tell(1.0)
    assert bo.evaluations_used == 1
