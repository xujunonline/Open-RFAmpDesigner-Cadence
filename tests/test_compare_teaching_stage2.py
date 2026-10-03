from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments.compare_teaching_stage2 import (
    audit_teaching_stage2_comparison,
    sample_efficiency_rows,
)


_RANDOM = Path("results/runs/teaching_matching_random/20260926T151700Z_061d699f")
_PSO = Path("results/runs/teaching_matching_pso/20260927T012145Z_92281c4d")
_REPORT = Path("results/runs/teaching_stage2_comparisons/20260927T012415Z_6b24413a")


def test_sample_efficiency_rows_enforces_order_and_budget() -> None:
    random = [{"point_index": 0, "diagnostic_cost": 5.0},
              {"point_index": 1, "diagnostic_cost": 4.0}]
    pso = [{"point_index": 0, "diagnostic_cost": 5.0},
           {"point_index": 1, "diagnostic_cost": 3.0}]
    rows = sample_efficiency_rows(random, pso)
    assert [row["random_best_cost"] for row in rows] == [5.0, 4.0]
    assert [row["pso_best_cost"] for row in rows] == [5.0, 3.0]
    with pytest.raises(ValueError, match="same nonzero"):
        sample_efficiency_rows(random, pso[:1])
    with pytest.raises(ValueError, match="evaluation order"):
        sample_efficiency_rows(random, [pso[1], pso[0]])
    with pytest.raises(ValueError, match="invalid"):
        sample_efficiency_rows(random, [{"point_index": 0, "diagnostic_cost": float("nan")}, pso[1]])


def _sources_available() -> None:
    if not all(path.is_dir() for path in (_RANDOM, _PSO, _REPORT)):
        pytest.skip("private equal-budget Stage 2 source archives are unavailable")


def test_real_equal_budget_comparison_rebuilds_from_sources() -> None:
    _sources_available()
    assert audit_teaching_stage2_comparison(_REPORT, _RANDOM, _PSO)["status"] == "verified"
    report = read_evidenced_metrics(_REPORT)
    assert report["budget_per_method"] == 4
    assert report["shared_initial_points"] == 2
    assert report["interpretation"] == "equal_observed_best"
    assert report["metrics"]["pso_minus_random_best_cost"] == 0
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_rehashed_comparison_claim_is_rejected(tmp_path: Path) -> None:
    _sources_available()
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["metrics"]["pso_minus_random_best_cost"] = -1.0
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from original"):
        audit_teaching_stage2_comparison(copied, _RANDOM, _PSO)
