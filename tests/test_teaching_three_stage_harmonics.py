from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments.audit_teaching_three_stage_harmonics import (
    audit_three_stage_harmonic_comparison, build_three_stage_harmonic_comparison,
)


_HB_ROOT = Path("results/runs/teaching_three_stage_hb")
_REPORT = Path("results/runs/teaching_three_stage_harmonics/20260926T200221Z_c224bdf6")
_IDS = [
    "20260926T194557Z_15443d06", "20260926T195821Z_73d4fab5", "20260926T195945Z_d6be091e",
    "20260926T194420Z_b2c9e93e", "20260926T195854Z_8be83a0d", "20260926T200019Z_16548891",
]


def test_real_three_stage_harmonic_comparison_rebuilds() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage harmonic comparison archive is unavailable")
    assert audit_three_stage_harmonic_comparison(_REPORT, _HB_ROOT)["status"] == "verified"
    report = read_evidenced_metrics(_REPORT)
    assert report["point_run_ids"] == _IDS
    assert report["metrics"]["max_gain_delta_9_11_db"] < 0.002
    assert report["metrics"]["max_ip_delta_7_11_dbm"] < 0.01
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_three_stage_harmonic_comparison_rejects_wrong_matrix() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage harmonic comparison archive is unavailable")
    with pytest.raises(ValueError, match="expected matrix"):
        build_three_stage_harmonic_comparison(_HB_ROOT, [_IDS[1], _IDS[0], *_IDS[2:]], "new_report")


def test_rehashed_harmonic_sensitivity_tamper_is_rejected(tmp_path: Path) -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage harmonic comparison archive is unavailable")
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["metrics"]["max_gain_delta_9_11_db"] = 0.0
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from raw"):
        audit_three_stage_harmonic_comparison(copied, _HB_ROOT)
