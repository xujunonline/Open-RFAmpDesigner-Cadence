from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments.audit_pdk_rf_default_harmonics import (
    audit_pdk_rf_harmonic_comparison,
    build_pdk_rf_harmonic_comparison,
    local_harmonic_crossings,
)


_HB_ROOT = Path("results/runs/pdk_three_stage_fixed")
_CREATE = _HB_ROOT / "rf_default_create_20260926T231047Z_38b59de6"
_BASELINE = _HB_ROOT / "rf_default_sp_20260926T231333Z_19c5f59b"
_REPORT = Path("results/runs/pdk_rf_harmonics/20260927T004019Z_b943aa87")
_IDS = [
    "rf_default_hb_20260927T001751Z_f072791f",
    "rf_default_hb_20260927T003307Z_e779ea20",
    "rf_default_hb_20260927T003522Z_0b0f8d30",
    "rf_default_hb_20260927T001640Z_691c716a",
    "rf_default_hb_20260927T003413Z_588f1032",
    "rf_default_hb_20260927T003628Z_47bd0a90",
]


def _matrix() -> list[dict]:
    points = []
    for power in (-11, -10):
        for harmonics in (7, 9, 11):
            gain = -20.9 if power == -11 else -21.2
            points.append({
                "pin_dbm": power, "harmonics": harmonics,
                "pout_dbm": power + gain, "gain_db": gain,
                "s21_db": -20.0, "compression_sp_reference_db": -20.0 - gain,
            })
    return points


def test_local_harmonic_crossings_requires_full_ordered_bracket() -> None:
    crossings = local_harmonic_crossings(_matrix())
    assert [item["harmonics"] for item in crossings] == [7, 9, 11]
    assert all(-11 < item["ip1db_sp_reference_dbm"] < -10 for item in crossings)
    with pytest.raises(ValueError, match="matrix"):
        local_harmonic_crossings(_matrix()[:-1])
    swapped = _matrix()
    swapped[1], swapped[2] = swapped[2], swapped[1]
    with pytest.raises(ValueError, match="matrix"):
        local_harmonic_crossings(swapped)
    unbracketed = _matrix()
    unbracketed[3]["compression_sp_reference_db"] = 0.5
    with pytest.raises(ValueError, match="bracketed"):
        local_harmonic_crossings(unbracketed)


def test_real_rf_harmonic_comparison_rebuilds() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private RF harmonic comparison archive is unavailable")
    assert audit_pdk_rf_harmonic_comparison(_REPORT, _HB_ROOT, _CREATE, _BASELINE)["status"] == "verified"
    report = read_evidenced_metrics(_REPORT)
    assert report["point_run_ids"] == _IDS
    assert report["metrics"]["maximum_gain_delta_9_to_11_db"] < 1e-5
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_rf_harmonic_comparison_rejects_wrong_matrix() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private RF harmonic comparison archive is unavailable")
    with pytest.raises(ValueError, match="incompatible context"):
        build_pdk_rf_harmonic_comparison(
            _HB_ROOT, [_IDS[1], _IDS[0], *_IDS[2:]], _CREATE, _BASELINE, "new_report",
        )


def test_rehashed_rf_harmonic_report_tamper_is_rejected(tmp_path: Path) -> None:
    if not _REPORT.is_dir():
        pytest.skip("private RF harmonic comparison archive is unavailable")
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["metrics"]["maximum_gain_delta_9_to_11_db"] = 0.0
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from raw"):
        audit_pdk_rf_harmonic_comparison(copied, _HB_ROOT, _CREATE, _BASELINE)
