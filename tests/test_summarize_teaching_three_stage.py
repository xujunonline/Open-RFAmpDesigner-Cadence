import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments import summarize_teaching_three_stage as module


def _sources():
    root = Path("results/runs/teaching_three_stage")
    names = ("probe_7eecbf34a74a", "20260926T180711Z_1a26f372", "20260926T181001Z_a2b462ac")
    paths = [root / name for name in names]
    if any(not path.is_dir() for path in paths):
        pytest.skip("private three-stage Cadence archives are unavailable")
    return paths


def _copy_report(tmp_path):
    source = Path("results/runs/teaching_three_stage_summaries/20260926T181140Z_14ea3389")
    if not source.is_dir():
        pytest.skip("private three-stage summary is unavailable")
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _rehash(path):
    manifest = path / "evidence_manifest.json"
    previous = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in previous["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(path, artifacts)), encoding="utf-8")


def test_real_three_stage_summary_tracks_distinct_passive_candidates():
    result = module.build_three_stage_summary(_sources(), "read_only_test")
    assert [(row["output_secondary_nh"], row["output_tune_ff"]) for row in result["rows"]] == [
        (1.0, 0.0), (1.0, 190.0), (4.1, 0.0),
    ]
    assert result["rows"][0]["s22_db"] > result["rows"][2]["s22_db"]
    assert result["not_lna_result"] is True and result["spec_pass"] is None


def test_three_stage_summary_rejects_duplicate_source():
    paths = _sources()
    with pytest.raises(ValueError, match="distinct source runs"):
        module.build_three_stage_summary([paths[0], paths[0]], "read_only_test")


def test_real_three_stage_summary_is_reauditable(tmp_path):
    copied = _copy_report(tmp_path)
    result = module.audit_three_stage_summary(copied, _sources()[0].parent)
    assert result["status"] == "verified" and result["source_runs"] == 3


def test_rehashed_three_stage_summary_metric_tamper_is_rejected(tmp_path):
    copied = _copy_report(tmp_path)
    path = copied / "metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][2]["s21_db"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash(copied)
    with pytest.raises(ValueError, match="differs from source archives"):
        module.audit_three_stage_summary(copied, _sources()[0].parent)
