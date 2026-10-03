from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.analyze_pdk_rf_input_match import _at, audit_pdk_rf_input_match
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_REPORT = _PRIVATE_ROOT / "pdk_rf_input_match_estimates" / "20260927T045841Z_9acec9b5"


def _private() -> Path:
    if not _REPORT.is_dir():
        pytest.skip("private authorized RF input-match source archives are unavailable")
    return _REPORT


def test_audited_input_match_estimate_is_not_a_candidate() -> None:
    report_dir = _private()
    result = audit_pdk_rf_input_match(report_dir)
    assert result == {
        "status": "verified", "points": 3,
        "no_candidate_simulated": True, "not_lna_result": True,
    }
    report = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))
    assert report["spec_pass"] is None and report["physical_qualification"] is False
    assert report["ideal_l_to_default_spiral_l_ratio"] > 10
    assert math.isclose(report["samples"][1]["frequency_ghz"], 10)
    assert -9 < report["samples"][1]["predicted_s11_with_center_series_l_db"] < -7
    assert report["samples"][0]["ideal_additional_series_l_nh"] > report["samples"][2]["ideal_additional_series_l_nh"]


@pytest.mark.parametrize("mutation", (
    "predicted_s11", "source_hash", "unsafe_source", "false_simulation", "false_lna", "false_physical",
))
def test_input_match_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_input_match_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        path = copied / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "predicted_s11":
            payload["samples"][1]["predicted_s11_with_center_series_l_db"] = -30.0
        elif mutation == "source_hash":
            payload["source_record_sha256"]["active"] = "0" * 64
        elif mutation == "unsafe_source":
            payload["source_run_ids"]["active"] = "../../unrelated"
        elif mutation == "false_simulation":
            payload["no_candidate_simulated"] = False
        elif mutation == "false_lna":
            payload["not_lna_result"] = False
        else:
            payload["physical_qualification"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(copied, {"metrics": "metrics.json"})
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_pdk_rf_input_match(copied)


def test_input_match_requires_an_exact_unique_frequency() -> None:
    with pytest.raises(ValueError):
        _at([8e9, 12e9], [0j, 1j], 10e9)
    with pytest.raises(ValueError):
        _at([10e9, 10e9], [0j, 1j], 10e9)
