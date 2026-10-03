from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.summarize_teaching_stage2_three_methods import (
    audit_teaching_stage2_three_methods,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_SUMMARY = _PRIVATE_ROOT / "teaching_stage2_three_methods" / "20260927T065413Z_42538ea4"


def _private() -> Path:
    if not _SUMMARY.is_dir():
        pytest.skip("private teaching three-method Spectre evidence is unavailable")
    return _SUMMARY


def test_real_three_method_summary_reaudits_sixty_spectre_points() -> None:
    report = audit_teaching_stage2_three_methods(_private())
    assert report == {"status": "verified", "seed_count": 5,
                      "budget_per_method": 4, "not_lna_result": True}
    payload = json.loads((_SUMMARY / "metrics.json").read_text(encoding="utf-8"))
    assert payload["seeds"] == [1, 2, 3, 4, 17]
    assert len(payload["per_seed"]) == 5
    assert payload["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("metrics", "csv", "config"))
def test_three_method_summary_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_three_method_", dir=_PRIVATE_ROOT.resolve()) as root:
        report_dir = Path(root) / source.name
        shutil.copytree(source, report_dir)
        if mutation == "metrics":
            path = report_dir / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"]["sa_mean_final_best_cost"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "csv":
            path = report_dir / "per_seed.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("20260927T065114Z_2bcd0d3f", "changed_run", 1), encoding="utf-8")
        else:
            path = report_dir / "source_runs.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sa_run_ids"][0] = "not_a_real_run"
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(report_dir, {
            "config": "source_runs.json", "per_seed": "per_seed.csv",
            "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
        })
        (report_dir / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, FileNotFoundError)):
            audit_teaching_stage2_three_methods(report_dir)


def test_three_method_false_spec_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_three_method_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        report_dir = Path(root) / source.name
        shutil.copytree(source, report_dir)
        path = report_dir / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(report_dir, {"metrics": "metrics.json"})
