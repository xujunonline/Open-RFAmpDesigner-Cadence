from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.summarize_pdk_rf_ladder_hb import audit_pdk_rf_ladder_hb_sweep


_REPORT = (_PRIVATE_ROOT / "pdk_rf_ladder_hb_sweeps" /
           "20260927T105441Z_1eb1a1c9")
_FILES = {"config": "sweep_config.json", "search": "power_sweep.csv",
          "metrics": "metrics.json"}


def _private() -> Path:
    if not _REPORT.is_dir():
        pytest.skip("private RF ladder HB sweep archive is unavailable")
    return _REPORT


def test_real_ladder_hb_sweep_reaudits_all_six_raw_points() -> None:
    result = audit_pdk_rf_ladder_hb_sweep(_private())
    assert result == {
        "status": "verified_diagnostic_only",
        "run_id": _REPORT.name,
        "points_verified": 6,
        "compression_status": "ok",
        "not_lna_result": True,
        "spec_pass": None,
    }
    payload = json.loads((_REPORT / "metrics.json").read_text(encoding="utf-8"))
    assert payload["compression"]["bracket_width_db"] == pytest.approx(1.0)
    assert payload["compression"]["ip1db_dbm"] == pytest.approx(-20.4582287157)
    assert payload["physical_qualification"] is False


@pytest.mark.parametrize("mutation", ("result", "source", "missing_manifest_entry"))
def test_ladder_hb_sweep_rejects_rehashed_tampering(mutation: str) -> None:
    report = _private()
    with tempfile.TemporaryDirectory(prefix="test_ladder_hb_sweep_",
                                     dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / report.name
        shutil.copytree(report, copied)
        if mutation == "result":
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["compression"]["ip1db_dbm"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "source":
            path = copied / "sweep_config.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["point_run_ids"][2] = payload["point_run_ids"][3]
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = copied / "evidence_manifest.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["artifacts"]["search"]
            path.write_text(json.dumps(payload), encoding="utf-8")
        if mutation != "missing_manifest_entry":
            manifest = build_evidence_manifest(copied, _FILES)
            (copied / "evidence_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            audit_pdk_rf_ladder_hb_sweep(copied)
