from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.config_loader import load_specs
from orfadc.experiments.aggregate_pdk_rf_diagnostic_fullchain import (
    audit_diagnostic_fullchain, build_diagnostic_fullchain,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_RUN = _PRIVATE_ROOT / "pdk_rf_diagnostic_fullchain" / "20260927T103033Z_127b9b3e"
_CREATE = _PRIVATE_ROOT / "pdk_three_stage_fixed" / "rf_default_create_20260926T231047Z_38b59de6"
_BASELINE = _PRIVATE_ROOT / "pdk_three_stage_fixed" / "rf_default_sp_20260926T231333Z_19c5f59b"
_SWEEP = _PRIVATE_ROOT / "pdk_rf_hb_sweeps" / "20260927T002112Z_84e382b1"
_FILES = {"config": "source_runs.json", "metrics": "metrics.json"}


def _private() -> Path:
    if not all(path.is_dir() for path in (_RUN, _CREATE, _BASELINE, _SWEEP)):
        pytest.skip("private authorized RF diagnostic archives are unavailable")
    return _RUN


def test_real_archived_fullchain_is_diagnostic_only() -> None:
    result = audit_diagnostic_fullchain(_private())
    assert result == {"status": "verified_diagnostic_only", "run_id": _RUN.name,
                      "points_in_band": 81, "not_lna_result": True, "spec_pass": None}
    saved = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert saved["violations"]["status"] == "unverified_score"
    assert saved["violations"]["pass"] is False
    assert saved["violations"]["gain_violation"] > 0
    assert saved["violations"]["nf_violation"] > 0
    assert saved["physical_qualification"] is False


def test_out_of_band_paper_spec_is_rejected() -> None:
    _private()
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S2")
    with pytest.raises(ValueError, match="only supports the S1"):
        build_diagnostic_fullchain(_CREATE, _BASELINE, _SWEEP, spec, "invalid_spec")


@pytest.mark.parametrize("mutation", ("metric", "source", "reference_plane"))
def test_rehashed_diagnostic_tampering_is_rejected(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_fullchain_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "source":
            path = copied / "source_runs.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["baseline_run_id"] = "not_a_real_run"
        else:
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "metric":
                payload["metrics"]["s21_db"] += 1.0
            else:
                payload["reference_planes"]["output_z0_ohm"] = 50.0
        path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(copied, _FILES)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, FileNotFoundError)):
            audit_diagnostic_fullchain(copied)


def test_false_lna_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_fullchain_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        path = copied / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["not_lna_result"] = False
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(copied, _FILES)
