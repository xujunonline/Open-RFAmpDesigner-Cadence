from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.summarize_teaching_stage2_four_methods import (
    audit_teaching_stage2_four_methods,
)


_RUN = _PRIVATE_ROOT / "teaching_stage2_four_methods" / "20260927T101428Z_4e5d538c"
_FILES = {
    "config": "source_runs.json", "per_seed": "per_seed.csv",
    "per_evaluation": "per_evaluation.csv", "metrics": "metrics.json",
}


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private four-method teaching comparison is unavailable")
    return _RUN


def test_real_four_method_summary_reaudits_eighty_spectre_points() -> None:
    result = audit_teaching_stage2_four_methods(_private())
    assert result == {"status": "verified", "seed_count": 5,
                      "budget_per_method": 4, "not_lna_result": True}
    payload = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert payload["seeds"] == [1, 2, 3, 4, 17]
    assert len(payload["ga_sources"]) == 5
    assert payload["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("metrics", "csv", "config"))
def test_four_method_summary_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_four_method_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "metrics":
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"]["ga_mean_final_best_cost"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "csv":
            path = copied / "per_seed.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("20260927T101112Z_e482256c", "changed_run", 1), encoding="utf-8")
        else:
            path = copied / "source_runs.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["ga_run_ids"][0] = "not_a_real_run"
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(copied, _FILES)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, FileNotFoundError)):
            audit_teaching_stage2_four_methods(copied)
