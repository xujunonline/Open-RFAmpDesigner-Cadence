from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage


_BROADBAND = Path("results/runs/teaching_three_stage/20260926T201404Z_b301241a")
_BASELINE = Path("results/runs/teaching_three_stage/probe_7eecbf34a74a")


def test_real_three_stage_broadband_probe_rebuilds() -> None:
    if not _BROADBAND.is_dir():
        pytest.skip("private Cadence three-stage broadband archive is unavailable")
    assert audit_teaching_three_stage(_BROADBAND)["points"] == 401
    result = read_evidenced_metrics(_BROADBAND)
    assert result["frequency_grid_ghz"] == {"low": 0.1, "high": 20.1, "points": 401}
    assert result["stability_failed_sample_count"] == 0
    assert result["stability"]["maximum_delta_abs"] == pytest.approx(0.9989896340477833)
    assert result["not_lna_result"] is True and result["spec_pass"] is None


def test_broadband_probe_matches_original_at_shared_frequencies() -> None:
    if not _BROADBAND.is_dir() or not _BASELINE.is_dir():
        pytest.skip("private Cadence three-stage archives are unavailable")
    audit_teaching_three_stage(_BROADBAND)
    audit_teaching_three_stage(_BASELINE)
    for signal in ("s11", "s21", "s12", "s22"):
        grid_original, values_original = parse_complex_trace(_BASELINE / "sp.sp", signal)
        grid_broad, values_broad = parse_complex_trace(_BROADBAND / "sp.sp", signal)
        original = dict(zip(grid_original, values_original, strict=True))
        broad = dict(zip(grid_broad, values_broad, strict=True))
        assert max(abs(original[f] - broad[f]) for f in (8e9, 10e9, 12e9)) < 1e-8


def test_rehashed_false_broadband_stability_is_rejected(tmp_path: Path) -> None:
    if not _BROADBAND.is_dir():
        pytest.skip("private Cadence three-stage broadband archive is unavailable")
    copied = tmp_path / _BROADBAND.name
    shutil.copytree(_BROADBAND, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["stability_out_of_band"]["maximum_delta_abs"] = 0.5
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="metrics differ from raw"):
        audit_teaching_three_stage(copied)
