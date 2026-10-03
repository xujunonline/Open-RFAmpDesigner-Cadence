from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments import audit_teaching_matching_sa as audit_module
from orfadc.experiments import run_teaching_matching_sa as run_module


def _fake_backend(config_path: Path, point_dir: Path, **settings: float) -> dict:
    point_dir.mkdir()
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "teaching_mos1_common_source",
        "not_lna_result": True, "spec_pass": None, "run_id": point_dir.name,
        "design_parameters": {**settings, "ldd_nh": 2.0, "cblock_ff": 5000.0},
        "metrics": {"s11_db": -8.0},
    }
    write_json(point_dir / "metrics.json", payload)
    (point_dir / "netlist.scs").write_text("teaching mock\n", encoding="ascii")
    (point_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="ascii")
    write_evidence_manifest(point_dir, {
        "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
    })
    return payload


def _fake_audit(point_dir: Path) -> dict:
    settings = json.loads((point_dir / "metrics.json").read_text(encoding="utf-8"))["design_parameters"]
    return {
        "metrics": {
            "nf_db": 1.0 + settings["lgs_nh"] / 10,
            "s11_db": -6.0 - settings["lss_ph"] / 100,
            "s21_db": 5.0,
        },
        "stability": {"minimum_k": 1.00001},
    }


@pytest.mark.parametrize("mutation", ("none", "config", "summary", "csv", "source"))
def test_sa_runner_and_auditor_replay_mock_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    monkeypatch.setattr(run_module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(run_module, "run_teaching_lna", _fake_backend)
    monkeypatch.setattr(run_module, "audit_teaching_lna", _fake_audit)
    monkeypatch.setattr(audit_module, "audit_teaching_lna", _fake_audit)
    root = tmp_path / "sa_mock"
    payload = run_module.run_teaching_matching_sa(tmp_path / "unused", root, seed=17, budget=4)
    assert payload["status"] == "sa_search_complete"
    assert payload["points_completed"] == 4
    assert payload["not_lna_result"] is True and payload["spec_pass"] is None
    assert audit_module.audit_teaching_matching_sa(root)["status"] == "verified"
    if mutation == "none":
        return
    if mutation == "config":
        path = root / "search_config.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        content["cooling"] = 0.75
        write_json(path, content)
    elif mutation == "summary":
        path = root / "metrics.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        content["rows"][1]["accepted"] = 1 - content["rows"][1]["accepted"]
        write_json(path, content)
    elif mutation == "csv":
        path = root / "search.csv"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("point_00", "changed_00", 1), encoding="utf-8")
    else:
        path = root / "point_00" / "metrics.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        content["design_parameters"]["lgs_nh"] = 1.3
        write_json(path, content)
        manifest = build_evidence_manifest(path.parent, {
            "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
        })
        (path.parent / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if mutation != "source":
        manifest = build_evidence_manifest(root, {
            "metrics": "metrics.json", "config": "search_config.json", "search": "search.csv",
        })
        (root / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        audit_module.audit_teaching_matching_sa(root)
