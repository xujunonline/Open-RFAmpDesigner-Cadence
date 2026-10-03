import pytest

from orfadc.tools.active_sizing import active_sizing, normalize_power_ratios
from orfadc.tools.cost_functions import fullchain_violations, stage2_cost, stage3_cost


def test_stage2_cost_passes_when_nf_and_s11_have_margin():
    result = stage2_cost(nf_sim_db=4.6, nf_user_db=5.0, s11_sim_db=-21.0)
    assert result["cost"] == 0.0


def test_stage3_cost_penalizes_ripple():
    result = stage3_cost([20.0, 25.0], gain_user_db=25.0)
    assert result["ripple_violation"] == 2.0
    assert result["cost"] > 0.0


def test_fullchain_requires_all_real_metrics():
    spec = {"gain_db": 25, "nf_max_db": 5, "ip1db_min_dbm": -25, "power_ma": 30}
    result = {"s21_db": 26, "nf_db": 4, "ip1db_dbm": -20, "power_ma": 20}
    outcome = fullchain_violations(result, spec)
    assert outcome["status"] == "incomplete"
    assert outcome["pass"] is False
    assert outcome["missing_metrics"] == ["result.s11_db"]


def test_fullchain_rejects_nonfinite_and_respects_explicit_s11_limit():
    spec = {"gain_db": 25, "nf_max_db": 5, "ip1db_min_dbm": -25, "power_ma": 30, "s11_max_db": -20}
    result = {"s11_db": -15, "s21_db": 26, "nf_db": 4, "ip1db_dbm": -20, "power_ma": 20}
    assert fullchain_violations(result, spec)["s11_violation"] == 5
    result["nf_db"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        fullchain_violations(result, spec)


def test_fullchain_cannot_pass_without_cadence_provenance():
    spec = {"gain_db": 25, "nf_max_db": 5, "ip1db_min_dbm": -25, "power_ma": 30}
    result = {"s11_db": -15, "s21_db": 26, "nf_db": 4, "ip1db_dbm": -20, "power_ma": 20}
    unverified = fullchain_violations(result, spec)
    assert unverified["constraints_met"] is True
    assert unverified["status"] == "unverified_score"
    assert unverified["pass"] is False
    verified = fullchain_violations({
        **result, "source": "cadence_spectre", "simulation_status": "ok",
        "circuit_class": "active_lna", "not_lna_result": False,
    }, spec)
    assert verified["status"] == "evaluated"
    assert verified["pass"] is True

    passive = fullchain_violations({
        **result, "source": "cadence_spectre", "simulation_status": "ok",
        "circuit_class": "passive_twoport", "not_lna_result": True,
    }, spec)
    assert passive["status"] == "unverified_score"
    assert passive["pass"] is False


def test_costs_reject_nonfinite_and_negative_headroom():
    with pytest.raises(ValueError, match="finite"):
        stage2_cost(float("nan"), 5, -21)
    with pytest.raises(ValueError, match="nonnegative"):
        stage2_cost(4, 5, -21, -0.1)
    with pytest.raises(ValueError, match="finite"):
        stage3_cost([20, float("inf")], 25)


def test_active_sizing_never_exceeds_stage_current_budget():
    context = {
        "model_kind": "teaching_model", "technology_id": "synthetic",
        "model_revision": "v1", "corner": "tt", "temperature_c": 27,
    }

    def row(stage, current):
        return {
            "stage": stage, "current_ma": current, "metadata": dict(context),
            "source_run_id": f"synthetic_stage{stage}",
            "w_um": 10, "l_um": 0.1, "vgs_v": 0.6,
            "gm_s": 0.005, "gds_s": 0.0001, "cgs_f": 1e-14, "cgd_f": 1e-15,
        }

    with pytest.raises(ValueError, match="nonnegative"):
        normalize_power_ratios([0.4, -0.1, 0.7])
    with pytest.raises(ValueError, match="current budget"):
        active_sizing([0.4, 0.3, 0.3], 30, [row(1, 13)], context)
    rows = [row(1, 11), row(2, 8), row(3, 7)]
    selected = active_sizing([0.4, 0.3, 0.3], 30, rows, context)
    assert [row["current_ma"] for row in selected] == [11, 8, 7]
    assert all(row["lookup_status"] == "metadata_matched_unverified" for row in selected)

    with pytest.raises(ValueError, match="empty"):
        active_sizing([0.4, 0.3, 0.3], 30, [], context)
    with pytest.raises(ValueError, match="context"):
        active_sizing([0.4, 0.3, 0.3], 30, rows)
    cross_process = [dict(row(1, 11), metadata=dict(context, technology_id="other"))]
    with pytest.raises(ValueError, match="another model context"):
        active_sizing([0.4, 0.3, 0.3], 30, cross_process, context)
    malformed = [dict(row(1, 11), gm_s=float("nan"))]
    with pytest.raises(ValueError, match="gm_s"):
        active_sizing([0.4, 0.3, 0.3], 30, malformed, context)
    with pytest.raises(ValueError, match="total_current_ma"):
        active_sizing([1], True)
