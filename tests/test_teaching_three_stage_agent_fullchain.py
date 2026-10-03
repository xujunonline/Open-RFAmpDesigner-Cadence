from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.config_loader import load_specs
from orfadc.experiments.audit_teaching_three_stage_agent_fullchain import (
    audit_teaching_three_stage_agent_fullchain, build_teaching_three_stage_agent_fullchain,
)
from orfadc.experiments.audit_teaching_three_stage_hb_sweep import (
    audit_three_stage_hb_sweep, build_three_stage_hb_sweep,
)


_ROOT = Path("results/runs")
_CANDIDATES = _ROOT / "teaching_three_stage_candidates"
_HB_ROOT = _ROOT / "teaching_three_stage_hb"
_AGENT = _ROOT / "teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba"
_SWEEP = _ROOT / "teaching_three_stage_hb_sweeps/20260927T194309Z_29931698"
_BASELINE_SWEEP = _ROOT / "teaching_three_stage_hb_sweeps/20260926T194808Z_2c6fec7e"
_REPORT = _ROOT / "teaching_three_stage_agent_fullchain/20260927T194442Z_94ec29cd"


def _spec():
    return next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")


def test_new_variable_inductance_sweep_and_same_candidate_report_rebuild() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private teaching agent/HB same-candidate report is unavailable")
    assert audit_three_stage_hb_sweep(_SWEEP, _HB_ROOT)["status"] == "verified"
    saved = read_evidenced_metrics(_REPORT)
    assert saved == build_teaching_three_stage_agent_fullchain(
        _AGENT, _CANDIDATES, _SWEEP, _HB_ROOT, _spec(), _REPORT.name,
    )
    assert saved["hb_points"] == 12
    assert saved["compression_status"] == "diagnostic_p1db_bracketed"
    assert saved["metrics"]["diagnostic_ip1db_dbm"] == pytest.approx(-11.8200183369677)
    assert saved["not_lna_result"] is True and saved["spec_pass"] is None


def test_mixed_secondary_inductances_and_wrong_candidate_pair_are_rejected() -> None:
    if not _REPORT.is_dir() or not _BASELINE_SWEEP.is_dir():
        pytest.skip("private teaching HB sources are unavailable")
    ids = read_evidenced_metrics(_SWEEP)["point_run_ids"]
    old = read_evidenced_metrics(_BASELINE_SWEEP)["point_run_ids"]
    with pytest.raises(ValueError, match="settings differ"):
        build_three_stage_hb_sweep(_HB_ROOT, [ids[0], ids[1], ids[2], old[-1]], "mixed")
    with pytest.raises(ValueError, match="does not belong"):
        build_teaching_three_stage_agent_fullchain(
            _AGENT, _CANDIDATES, _BASELINE_SWEEP, _HB_ROOT, _spec(), "wrong",
        )


def test_rehashed_summary_claim_cannot_replace_raw_source(tmp_path: Path) -> None:
    if not _REPORT.is_dir():
        pytest.skip("private teaching same-candidate report is unavailable")
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics = copied / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["metrics"]["diagnostic_ip1db_dbm"] += 2.0
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: item["path"] for key, item in saved["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from its raw sources"):
        audit_teaching_three_stage_agent_fullchain(
            copied, _AGENT, _CANDIDATES, _SWEEP, _HB_ROOT, _spec(),
        )
