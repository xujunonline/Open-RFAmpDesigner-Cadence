from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.summarize_teaching_stage2_multiseed import (
    audit_teaching_stage2_multiseed,
    build_teaching_stage2_multiseed,
)


_REPORT = Path("results/runs/teaching_stage2_multiseed/20260927T033634Z_f6923862")
_SOURCES = (
    Path("results/runs/teaching_stage2_comparisons/20260927T012415Z_6b24413a"),
    Path("results/runs/teaching_stage2_comparisons/20260927T033148Z_a0af3407"),
    Path("results/runs/teaching_stage2_comparisons/20260927T033243Z_cad37566"),
    Path("results/runs/teaching_stage2_comparisons/20260927T033333Z_988fc074"),
    Path("results/runs/teaching_stage2_comparisons/20260927T033425Z_d1e01337"),
)
_ARTIFACTS = {
    "config": "comparison_sources.json", "per_seed": "per_seed.csv",
    "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
}


def _private() -> None:
    if not _REPORT.is_dir() or not all(path.is_dir() for path in _SOURCES):
        pytest.skip("private teaching multiseed Spectre archives are unavailable")


def test_real_five_seed_report_reaudits_and_stays_teaching_only() -> None:
    _private()
    result = audit_teaching_stage2_multiseed(_REPORT)
    assert result == {
        "status": "verified", "seed_count": 5, "budget_per_method": 4,
        "not_lna_result": True,
    }
    seeds, evaluations, report = build_teaching_stage2_multiseed(list(_SOURCES), _REPORT.name)
    assert [row["seed"] for row in seeds] == [1, 2, 3, 4, 17]
    assert len(evaluations) == 4
    assert report["spec_pass"] is None
    assert report["metrics"]["pso_lower_seed_count"] == 1
    assert report["metrics"]["random_lower_seed_count"] == 2
    assert report["metrics"]["equal_seed_count"] == 2


def test_multiseed_rejects_duplicate_seed() -> None:
    _private()
    with pytest.raises(ValueError, match="distinct source"):
        build_teaching_stage2_multiseed([_SOURCES[0], _SOURCES[0]], "test_duplicate")


@pytest.mark.parametrize("mutation", ("metric", "csv", "source_list", "false_pass"))
def test_multiseed_rejects_rehashed_tampering(mutation: str) -> None:
    _private()
    with tempfile.TemporaryDirectory(
        prefix="test_stage2_multiseed_", dir=Path("results/runs").resolve(),
    ) as root:
        copied = Path(root) / _REPORT.name
        shutil.copytree(_REPORT, copied)
        if mutation in {"metric", "false_pass"}:
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "metric":
                payload["metrics"]["pso_mean_final_best_cost"] += 1
            else:
                payload["spec_pass"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "csv":
            path = copied / "per_seed.csv"
            source = path.read_text(encoding="utf-8")
            path.write_text(source.replace("20260927T033148Z_a0af3407", "20260927T033243Z_cad37566", 1), encoding="utf-8")
        else:
            path = copied / "comparison_sources.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["comparison_run_ids"][1] = payload["comparison_run_ids"][0]
            path.write_text(json.dumps(payload), encoding="utf-8")
        if mutation == "false_pass":
            with pytest.raises(ValueError, match="non-LNA result"):
                build_evidence_manifest(copied, _ARTIFACTS)
            return
        manifest = build_evidence_manifest(copied, _ARTIFACTS)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_teaching_stage2_multiseed(copied)
