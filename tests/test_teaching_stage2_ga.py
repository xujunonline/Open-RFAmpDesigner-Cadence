from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_teaching_matching_ga import audit_teaching_matching_ga
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_RUN = _PRIVATE_ROOT / "teaching_matching_ga" / "20260927T100305Z_b891a9ae"
_FILES = {"metrics": "metrics.json", "config": "search_config.json", "search": "search.csv"}


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private teaching GA Spectre pilot is unavailable")
    return _RUN


def test_real_teaching_ga_replays_four_spectre_points() -> None:
    report = audit_teaching_matching_ga(_private())
    assert report["status"] == "verified" and report["points_verified"] == 4
    assert report["not_lna_result"] is True
    payload = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert payload["spec_pass"] is None
    assert payload["source"] == "cadence_spectre_archives"
    assert len(payload["source_manifests"]) == 4


@pytest.mark.parametrize("mutation", ("metrics", "csv", "config"))
def test_ga_audit_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_teaching_ga_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "metrics":
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["best_diagnostic_point"]["diagnostic_cost"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "csv":
            path = copied / "search.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("point_00", "changed_point", 1), encoding="utf-8")
        else:
            path = copied / "search_config.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["normalized_mutation_radius"] = 0.5
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(copied, _FILES)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_teaching_matching_ga(copied)
