import pytest

from orfadc.tools.stage2_sampling import sample_teaching_stage2


def test_teaching_stage2_plan_is_reproducible_and_bounded():
    points = sample_teaching_stage2(17, 4)
    assert points == sample_teaching_stage2(17, 4)
    assert points != sample_teaching_stage2(18, 4)
    assert len(points) == 4
    assert all(0.7 <= point["lgs_nh"] <= 1.3 and 180 <= point["lss_ph"] <= 320
               for point in points)


@pytest.mark.parametrize("seed,budget", [(-1, 4), (1.2, 4), (0, 0), (0, 13), (0, True)])
def test_teaching_stage2_plan_rejects_invalid_budget_or_seed(seed, budget):
    with pytest.raises(ValueError):
        sample_teaching_stage2(seed, budget)
