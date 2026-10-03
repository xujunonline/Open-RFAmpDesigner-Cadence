from pathlib import Path

import pytest

from orfadc.config_loader import load_specs, load_yaml
from orfadc.tools.cost_functions import stage2_cost, stage3_cost


ROOT = Path(__file__).resolve().parents[1]


def test_table_iii_spec_values_match_english_paper_page_8() -> None:
    specs = load_specs(ROOT / "config/specs_table_iii.yaml")
    actual = [
        (spec.id, spec.fc_ghz, spec.fbw_ratio, spec.power_ma,
         spec.gain_db, spec.nf_max_db, spec.ip1db_min_dbm)
        for spec in specs
    ]
    assert actual == [
        ("S1", 10, 0.20, 30, 25, 5, -25),
        ("S2", 30, 0.20, 30, 25, 5, -25),
        ("S3", 50, 0.20, 30, 20, 5, -20),
        ("S4", 30, 0.10, 30, 25, 5, -25),
        ("S5", 30, 0.60, 30, 25, 5, -25),
        ("S6", 30, 0.80, 30, 20, 5, -20),
        ("S7", 30, 0.20, 30, 25, 2.5, -25),
        ("S8", 30, 0.20, 15, 25, 5, -25),
        ("S9", 30, 0.20, 30, 25, 5, -15),
        ("S10", 30, 0.20, 30, 25, 3.5, -15),
    ]


def test_table_ii_ranges_match_english_paper_page_5() -> None:
    data = load_yaml(ROOT / "config/variable_ranges_table_ii.yaml")
    assert data["stage2"] == {
        "k": [0.1, 0.7], "l1_ph": [100, 1000], "l2_ph": [100, 1000],
        "r1_ohm": [100, 1000], "r2_ohm": [100, 1000],
        "c1_ff": [0, 50], "c2_ff": [0, 50], "ls_ph": [0, 150],
    }
    assert data["stage3"] == {
        "k": [0.1, 0.8], "omega0_ghz": ["omega_l", "omega_h"],
        "q0": [0.1, 8], "c_ff": ["C2", 200],
    }


def test_paper_equations_one_and_two() -> None:
    assert stage2_cost(nf_sim_db=5.0, nf_user_db=5.0, s11_sim_db=-18.0) == pytest.approx({
        "nf_violation": 0.2, "s11_violation": 2.0, "cost": 2200.0,
    })
    assert stage3_cost([20.0, 25.0], gain_user_db=25.0) == {
        "min_gain_db": 20.0, "max_gain_db": 25.0,
        "gain_violation": 2.0, "ripple_violation": 2.0, "cost": 4000.0,
    }
