from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.config_loader import load_specs
from orfadc.experiments.aggregate_pdk_rf_ladder_fullchain import (
    audit_pdk_rf_ladder_fullchain, build_pdk_rf_ladder_fullchain,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_RUN = _PRIVATE_ROOT / "pdk_rf_ladder_fullchain" / "20260927T111305Z_1748e1d0"
_LADDER = _PRIVATE_ROOT / "pdk_rf_input_ladder" / "20260927T051926Z_93744611"
_SWEEP = _PRIVATE_ROOT / "pdk_rf_ladder_hb_sweeps" / "20260927T105441Z_1eb1a1c9"
_FILES = {"config": "source_runs.json", "metrics": "metrics.json"}


def _private() -> Path:
    if not all(path.is_dir() for path in (_RUN, _LADDER, _SWEEP)):
        pytest.skip("private RF ladder fullchain archives are unavailable")
    return _RUN


def test_real_ladder_fullchain_reaudits_same_candidate_sources() -> None:
    result = audit_pdk_rf_ladder_fullchain(_private())
    assert result == {
        "status": "verified_diagnostic_only", "run_id": _RUN.name,
        "points_in_band": 81, "not_lna_result": True, "spec_pass": None,
    }
    saved = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert saved["source_run_ids"] == {
        "ladder_run_id": _LADDER.name, "sweep_run_id": _SWEEP.name,
    }
    assert saved["violations"]["status"] == "unverified_score"
    assert saved["violations"]["pass"] is False
    assert saved["violations"]["gain_violation"] > 0
    assert saved["violations"]["nf_violation"] > 0
    assert saved["physical_qualification"] is False


def test_ladder_fullchain_rejects_out_of_band_paper_spec() -> None:
    _private()
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S2")
    with pytest.raises(ValueError, match="only supports the S1"):
        build_pdk_rf_ladder_fullchain(_LADDER, _SWEEP, spec, "wrong_spec")


@pytest.mark.parametrize("mutation", ("metric", "source", "reference_plane", "manifest_entry"))
def test_rehashed_ladder_fullchain_tampering_is_rejected(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_ladder_fullchain_",
                                     dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "source":
            path = copied / "source_runs.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sweep_run_id"] = "20260927T002112Z_84e382b1"  # Different circuit's sweep.
        elif mutation == "manifest_entry":
            path = copied / "evidence_manifest.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["artifacts"]["config"]
        else:
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "metric":
                payload["metrics"]["s21_db"] += 1.0
            else:
                payload["reference_planes"]["input_z0_ohm"] = 100.0
        path.write_text(json.dumps(payload), encoding="utf-8")
        if mutation != "manifest_entry":
            manifest = build_evidence_manifest(copied, _FILES)
            (copied / "evidence_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, FileNotFoundError)):
            audit_pdk_rf_ladder_fullchain(copied)


def test_ladder_fullchain_false_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_ladder_fullchain_pass_",
                                     dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        path = copied / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["not_lna_result"] = False
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(copied, _FILES)
