from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments import audit_teaching_input_grid as auditor
from orfadc.experiments import run_teaching_input_grid as producer


def test_input_grid_audit_recomputes_best_after_rehashed_summary_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    points = {}

    def fake_run(config: Path, point: Path, *, vbias_v: float, wmos_um: float,
                 lgs_nh: float, lss_ph: float) -> dict:
        point.mkdir()
        (point / "evidence_manifest.json").write_text("mock", encoding="utf-8")
        payload = {
            "status": "ok_with_warnings",
            "design_parameters": {"vbias_v": vbias_v, "lgs_nh": lgs_nh,
                                  "lss_ph": lss_ph, "ldd_nh": 2.0, "cblock_ff": 5000.0,
                                  "wmos_um": wmos_um},
        }
        points[point.name] = payload
        return payload

    def fake_audit(point: Path) -> dict:
        index = int(point.name[-2:])
        return {
            "metrics": {"nf_db": 1.0, "s11_db": -11.0 - index,
                        "s21_db": 8.0, "ripple_db": 3.0, "supply_current_ma": 5.0},
            "stability": {"minimum_k": 1.1, "maximum_delta_abs": 0.9},
        }

    monkeypatch.setattr(producer, "_require_private_path", lambda _: None)
    monkeypatch.setattr(producer, "run_teaching_lna", fake_run)
    monkeypatch.setattr(producer, "read_evidenced_metrics", lambda point: points[point.name])
    monkeypatch.setattr(producer, "audit_teaching_lna", fake_audit)
    grid = tmp_path / "grid"
    producer.run_teaching_input_grid(
        tmp_path / "unused", grid, lgs_values_nh=[0.8, 1.0], lss_values_ph=[200, 240],
    )
    monkeypatch.setattr(
        auditor, "read_evidenced_metrics",
        lambda path: read_evidenced_metrics(path) if path == grid else points[path.name],
    )
    monkeypatch.setattr(auditor, "audit_teaching_lna", fake_audit)
    assert auditor.audit_teaching_input_grid(grid)["points_verified"] == 4

    summary_path = grid / "metrics.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["best_diagnostic_point"]["diagnostic_cost"] = 0.0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    manifest = build_evidence_manifest(
        grid, {"metrics": "metrics.json", "config": "sweep_config.json", "grid": "input_grid.csv"},
    )
    (grid / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="best point"):
        auditor.audit_teaching_input_grid(grid)
