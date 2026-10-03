from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.search_pdk_rf_input_ladder import (
    audit_pdk_rf_input_ladder_search, predict_ladder_s11,
)


_SEARCH = _PRIVATE_ROOT / "pdk_rf_input_ladder_search" / "20260927T051628Z_23e709de"


def _private() -> Path:
    if not _SEARCH.is_dir():
        pytest.skip("private authorized RF ladder search is unavailable")
    return _SEARCH


def test_real_search_replays_but_remains_unqualified() -> None:
    result = audit_pdk_rf_input_ladder_search(_private())
    assert result == {
        "status": "verified", "evaluations": 16_384,
        "no_candidate_simulated": True, "not_lna_result": True,
    }
    metrics = json.loads((_SEARCH / "metrics.json").read_text(encoding="utf-8"))
    assert -7 < metrics["predicted_worst_s11_db"] < -5
    assert metrics["best_ideal_parameters"]["l_inner_nh"] > 5
    assert metrics["physical_qualification"] is False and metrics["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("predicted", "source_id", "false_qualification", "trace"))
def test_search_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_ladder_search_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        if mutation == "trace":
            path = run / "search_trace.csv"
            content = path.read_bytes()
            assert b"-6.1151103985189295" in content
            path.write_bytes(content.replace(b"-6.1151103985189295", b"-30.0"))
        else:
            path = run / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "predicted":
                payload["predicted_worst_s11_db"] = -30.0
            elif mutation == "source_id":
                payload["source_run_ids"]["active"] = "../../unrelated"
            else:
                payload["physical_qualification"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(run, {
            "metrics": "metrics.json", "trace": "search_trace.csv", "waveforms": "predicted_waveforms.csv",
        })
        (run / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_pdk_rf_input_ladder_search(run)


def test_ladder_prediction_rejects_unbounded_or_incomplete_parameters() -> None:
    params = {"c_outer_ff": 100.0, "c_inner_ff": 50.0,
              "l_middle_nh": 1.0, "l_inner_nh": 2.0}
    assert len(predict_ladder_s11([10e9], [100 - 100j], params)) == 1
    with pytest.raises(ValueError):
        predict_ladder_s11([10e9], [100 - 100j], {**params, "l_inner_nh": 20.0})
    with pytest.raises(ValueError):
        predict_ladder_s11([10e9], [100 - 100j], {"c_outer_ff": 100.0})
