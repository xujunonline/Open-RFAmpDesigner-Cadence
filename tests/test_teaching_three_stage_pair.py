import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.teaching_three_stage_netlist import (
    render_teaching_three_stage, render_teaching_three_stage_hb,
)
from orfadc.experiments.audit_teaching_three_stage_pair import (
    _same_circuit, audit_three_stage_pair_report,
)


_OA = Path("results/runs/teaching_three_stage_oa/20260926T184521Z_4561f7d5")
_HB = Path("results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b")
_DIRECT = Path("results/runs/teaching_three_stage/probe_7eecbf34a74a")
_REPORT = Path("results/runs/teaching_three_stage_pairs/20260926T192301Z_64f6b886")


def test_three_stage_pair_only_allows_stimulus_difference() -> None:
    small = render_teaching_three_stage().decode("ascii")
    hb = render_teaching_three_stage_hb(-70).decode("ascii")
    _same_circuit(small, hb)
    with pytest.raises(ValueError, match="L3S"):
        _same_circuit(small, render_teaching_three_stage_hb(-70, output_secondary_nh=4.1).decode("ascii"))
    with pytest.raises(ValueError, match="port references"):
        _same_circuit(small, hb.replace("PORT2 (outp outn) port r=1787", "PORT2 (outp outn) port r=50"))


def test_real_three_stage_pair_is_rebuildable() -> None:
    if not all(path.is_dir() for path in (_OA, _HB, _DIRECT, _REPORT)):
        pytest.skip("private three-stage pair archives are unavailable")
    result = audit_three_stage_pair_report(_REPORT, _OA, _HB, _DIRECT)
    assert result["status"] == "verified"
    assert result["compression_status"] == "not_measured"


def test_rehashed_pair_claim_of_compression_is_rejected(tmp_path: Path) -> None:
    if not all(path.is_dir() for path in (_OA, _HB, _DIRECT, _REPORT)):
        pytest.skip("private three-stage pair archives are unavailable")
    copied = tmp_path / _REPORT.name
    shutil.copytree(_REPORT, copied)
    metrics_path = copied / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["compression_status"] = "measured"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    manifest_path = copied / "evidence_manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest_path.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from source"):
        audit_three_stage_pair_report(copied, _OA, _HB, _DIRECT)
