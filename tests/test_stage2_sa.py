from __future__ import annotations

import pytest

from orfadc.tools.stage2_sa import TeachingStage2SA
from orfadc.tools.stage2_sampling import sample_teaching_stage2


def test_sa_is_seeded_bounded_and_replays_acceptance() -> None:
    left = TeachingStage2SA(17, 4)
    right = TeachingStage2SA(17, 4)
    assert left.ask() == sample_teaching_stage2(17, 4)[0]
    assert right.ask() == sample_teaching_stage2(17, 4)[0]
    assert left.tell(1000.0) is True
    assert right.tell(1000.0) is True
    for cost in (900.0, 2000.0, 800.0):
        point = left.ask()
        assert point == right.ask()
        assert 0.7 <= point["lgs_nh"] <= 1.3
        assert 180.0 <= point["lss_ph"] <= 320.0
        assert left.tell(cost) == right.tell(cost)
    assert left.evaluations_used == 4
    assert left.best_cost == 800.0
    assert left.current_point == right.current_point
    with pytest.raises(RuntimeError, match="exhausted"):
        left.ask()


def test_sa_rejects_invalid_state_and_score() -> None:
    for seed, budget in ((True, 4), (-1, 4), (0, 3), (0, 13)):
        with pytest.raises(ValueError):
            TeachingStage2SA(seed, budget)
    optimizer = TeachingStage2SA(0, 4)
    with pytest.raises(RuntimeError, match="pending"):
        optimizer.tell(1.0)
    optimizer.ask()
    with pytest.raises(RuntimeError, match="previous score"):
        optimizer.ask()
    for cost in (float("nan"), float("inf"), -1.0, True):
        with pytest.raises(ValueError, match="score"):
            optimizer.tell(cost)
    optimizer.tell(1.0)


def test_sa_next_proposal_depends_on_measured_acceptance() -> None:
    improve = TeachingStage2SA(3, 4)
    reject = TeachingStage2SA(3, 4)
    assert improve.ask() == reject.ask()
    improve.tell(1000.0)
    reject.tell(1000.0)
    assert improve.ask() == reject.ask()
    assert improve.tell(900.0) is True
    assert reject.tell(1_000_000.0) is False
    assert improve.ask() != reject.ask()
