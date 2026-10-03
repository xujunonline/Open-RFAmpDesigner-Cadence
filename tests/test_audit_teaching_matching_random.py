import copy
import csv
import hashlib
import json

import pytest

from orfadc.experiments import audit_teaching_matching_random as module
from orfadc.experiments.run_teaching_matching_random import _COLUMNS
from orfadc.tools.cost_functions import stage2_cost
from orfadc.tools.stage2_sampling import sample_teaching_stage2


def _fixture(tmp_path, monkeypatch):
    root = tmp_path / "run001"
    root.mkdir()
    points = sample_teaching_stage2(3, 1)
    config = {
        "schema_version": 1, "method": "seeded_uniform_random", "seed": 3,
        "budget": 1, "points": points, "nf_user_db": 2.0,
        "nf_headroom_db": 0.2, "vbias_v": 0.65, "wmos_um": 300.0,
        "ldd_nh": 2.0, "cblock_ff": 5000.0,
    }
    (root / "search_config.json").write_text(json.dumps(config), encoding="utf-8")
    point_dir = root / "point_00"
    point_dir.mkdir()
    (point_dir / "evidence_manifest.json").write_text("source", encoding="utf-8")
    cost = stage2_cost(1.1, 2.0, -10.0, 0.2)
    row = {
        "point_index": 0, "run_id": "point_00", **points[0],
        "nf_worst_db": 1.1, "s11_worst_db": -10.0,
        "s21_worst_db": 8.0, "nf_violation": cost["nf_violation"],
        "s11_violation": cost["s11_violation"],
        "diagnostic_cost": cost["cost"], "minimum_k_sampled": 1.00001,
    }
    with (root / "search.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    summary = {
        "status": "random_search_complete", "simulation_status": "unknown",
        "source": "cadence_spectre_archives", "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model", "not_lna_result": True,
        "spec_pass": None, "run_id": "run001", "seed": 3,
        "points_requested": 1, "points_completed": 1, "failures": [],
        "best_diagnostic_point": row, "rows": [row],
        "source_manifests": [{"run_id": "point_00", "evidence_manifest_sha256":
                              hashlib.sha256(b"source").hexdigest()}],
    }
    point = {
        "status": "ok_with_warnings", "design_parameters": {
            "vbias_v": 0.65, "wmos_um": 300.0, **points[0],
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        },
    }
    monkeypatch.setattr(module, "read_evidenced_metrics",
                        lambda path: summary if path == root else point)
    monkeypatch.setattr(module, "audit_teaching_lna", lambda _: {
        "metrics": {"nf_db": 1.1, "s11_db": -10.0, "s21_db": 8.0},
        "stability": {"minimum_k": 1.00001},
    })
    return root, config, summary


def test_random_search_audit_rescores_source_points(tmp_path, monkeypatch):
    root, _, _ = _fixture(tmp_path, monkeypatch)
    report = module.audit_teaching_matching_random(root)
    assert report["status"] == "verified"
    assert report["best_diagnostic_point"]["diagnostic_cost"] == 10000.0
    assert report["not_lna_result"] is True


def test_random_search_audit_rejects_rewritten_plan(tmp_path, monkeypatch):
    root, config, _ = _fixture(tmp_path, monkeypatch)
    config["points"][0]["lgs_nh"] = 1.0
    (root / "search_config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="plan"):
        module.audit_teaching_matching_random(root)


def test_random_search_audit_rejects_changed_score(tmp_path, monkeypatch):
    root, _, summary = _fixture(tmp_path, monkeypatch)
    modified = copy.deepcopy(summary)
    modified["rows"][0]["diagnostic_cost"] = 0.0
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: modified if path == root else {
        "status": "ok_with_warnings", "design_parameters": {
            "vbias_v": 0.65, "wmos_um": 300.0, **sample_teaching_stage2(3, 1)[0],
            "ldd_nh": 2.0, "cblock_ff": 5000.0,
        },
    })
    with pytest.raises(ValueError, match="cost"):
        module.audit_teaching_matching_random(root)
