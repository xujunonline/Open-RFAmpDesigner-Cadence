from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import run_teaching_input_grid as module


def test_input_grid_scores_only_evidenced_audited_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = {}

    def fake_run(config: Path, point: Path, *, vbias_v: float, wmos_um: float,
                 lgs_nh: float, lss_ph: float) -> dict:
        point.mkdir()
        (point / "evidence_manifest.json").write_text("mock", encoding="utf-8")
        payload = {
            "status": "ok_with_warnings",
            "design_parameters": {"vbias_v": vbias_v, "lgs_nh": lgs_nh, "lss_ph": lss_ph,
                                  "ldd_nh": 2.0, "cblock_ff": 5000.0, "wmos_um": wmos_um},
        }
        results[point.name] = payload
        return payload

    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "run_teaching_lna", fake_run)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda point: results[point.name])
    monkeypatch.setattr(
        module, "audit_teaching_lna",
        lambda point: {"metrics": {"nf_db": 1.0, "s11_db": -10.0 - int(point.name[-2:]),
                                   "s21_db": 8.0, "ripple_db": 3.0,
                                   "supply_current_ma": 5.0},
                       "stability": {"minimum_k": 1.1, "maximum_delta_abs": 0.9}},
    )
    output = tmp_path / "grid"
    result = module.run_teaching_input_grid(
        tmp_path / "unused", output, lgs_values_nh=[0.8, 1.0], lss_values_ph=[200, 240],
    )
    assert result["status"] == "input_grid_complete"
    assert result["points_completed"] == 4
    assert result["best_diagnostic_point"]["run_id"] == "point_03"
    assert result["best_diagnostic_point"]["diagnostic_cost"] == 7000.0
    assert (output / "sweep_config.json").read_text(encoding="utf-8").find('"wmos_um": 300.0') >= 0
    assert result["spec_pass"] is None and result["not_lna_result"] is True
    assert read_evidenced_metrics(output) == result


def test_input_grid_rejects_invalid_plan_before_output_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="distinct"):
        module.run_teaching_input_grid(
            tmp_path / "unused", output, lgs_values_nh=[1.0, 1.0], lss_values_ph=[200, 240],
        )
    assert not output.exists()
    with pytest.raises(ValueError, match="LGS"):
        module.run_teaching_input_grid(
            tmp_path / "unused", output, lgs_values_nh=[0.1, 1.0], lss_values_ph=[200, 240],
        )
    assert not output.exists()
