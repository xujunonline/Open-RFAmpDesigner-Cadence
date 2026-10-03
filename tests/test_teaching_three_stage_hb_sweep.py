from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments.audit_teaching_three_stage_hb_sweep import (
    audit_three_stage_hb_sweep, build_three_stage_hb_sweep,
)


_HB_ROOT = Path("results/runs/teaching_three_stage_hb")
_REPORT = Path("results/runs/teaching_three_stage_hb_sweeps/20260926T194808Z_2c6fec7e")
_IDS = [
    "20260926T190425Z_dc513e8b", "20260926T193924Z_3c5b6053",
    "20260926T194013Z_5495c825", "20260926T194102Z_09009ae6",
    "20260926T194149Z_b57ff672", "20260926T194334Z_cc426be6",
    "20260926T194509Z_4f874739", "20260926T194557Z_15443d06",
    "20260926T194420Z_b2c9e93e", "20260926T194243Z_a915337e",
]


def test_real_three_stage_hb_sweep_rebuilds_from_independent_runs() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage HB sweep archive is unavailable")
    result = audit_three_stage_hb_sweep(_REPORT, _HB_ROOT)
    assert result["status"] == "verified"
    report = read_evidenced_metrics(_REPORT)
    assert report["point_run_ids"] == _IDS
    assert report["compression"]["crossing_indices"] == [7, 8]
    assert report["compression"]["ip1db_dbm"] == pytest.approx(-13.1556470955)
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_three_stage_hb_sweep_rejects_duplicate_and_reordered_runs() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage HB sweep archive is unavailable")
    with pytest.raises(ValueError, match="duplicate"):
        build_three_stage_hb_sweep(_HB_ROOT, [_IDS[0]] * 4, "new_report")
    with pytest.raises(ValueError, match="strictly increasing"):
        build_three_stage_hb_sweep(_HB_ROOT, [_IDS[1], _IDS[0], *_IDS[2:]], "new_report")


def test_rehashed_three_stage_hb_sweep_metric_tamper_is_rejected(tmp_path: Path) -> None:
    if not _REPORT.is_dir():
        pytest.skip("private three-stage HB sweep archive is unavailable")
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["compression"]["ip1db_dbm"] += 1.0
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from raw"):
        audit_three_stage_hb_sweep(copied, _HB_ROOT)
