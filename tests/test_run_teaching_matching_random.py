import json

from orfadc.experiments import run_teaching_matching_random as module


def test_teaching_random_backend_warning_stops_without_a_false_score(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    failed = {"status": "model_validity_warning"}
    monkeypatch.setattr(module, "run_teaching_lna", lambda *args, **kwargs: failed)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda _: failed)
    result = module.run_teaching_matching_random(
        tmp_path / "private.yaml", tmp_path / "diagnostic", seed=17, budget=2,
    )
    assert result["status"] == "incomplete"
    assert result["points_completed"] == 0
    assert result["best_diagnostic_point"] is None
    assert result["failures"] == [{"point_index": 0, "run_id": "point_00",
                                   "backend_status": "model_validity_warning"}]
    saved = json.loads((tmp_path / "diagnostic" / "metrics.json").read_text())
    assert saved["not_lna_result"] is True
    assert saved["spec_pass"] is None
