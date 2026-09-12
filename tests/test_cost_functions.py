from orfadc.tools.cost_functions import stage2_cost, stage3_cost


def test_stage2_cost_passes_when_nf_and_s11_have_margin():
    result = stage2_cost(nf_sim_db=4.6, nf_user_db=5.0, s11_sim_db=-21.0)
    assert result["cost"] == 0.0


def test_stage3_cost_penalizes_ripple():
    result = stage3_cost([20.0, 25.0], gain_user_db=25.0)
    assert result["ripple_violation"] == 2.0
    assert result["cost"] > 0.0

