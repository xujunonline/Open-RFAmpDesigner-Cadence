from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from orfadc.experiments.audit_pdk_rf_drc_probe import audit_pdk_rf_drc_probe


_ROOT = Path("results/runs")
_ARCHIVES = (
    _ROOT / "pdk_geometry_stream/rf_pcell_default_20260927_01",
    _ROOT / "pdk_geometry_stream/rf_pcell_default_20260927_02",
    _ROOT / "pdk_geometry_stream/rf_pcell_wr3_20260927_01",
    _ROOT / "pdk_drc_probe/rf_pcell_default_20260927_01",
    _ROOT / "pdk_drc_probe/rf_pcell_wr3_20260927_01",
)


def _private_runs() -> tuple[Path, ...]:
    if not all(path.is_dir() for path in _ARCHIVES):
        pytest.skip("private authorized RF GDS/DRC archives are unavailable")
    return _ARCHIVES


def test_real_drc_probe_reaudits_without_claiming_pass() -> None:
    result = audit_pdk_rf_drc_probe(*_private_runs())
    assert result["status"] == "drc_completed_with_violations"
    assert result["empty_stream_rejected"] is True
    assert result["nonempty_streams_verified"] is True
    assert result["same_source_deck"] is True
    assert result["rulechecks_executed"] > 0
    assert result["default_violation_groups"] > 0
    assert result["default_results"] >= result["default_violation_groups"]
    assert result["same_nonzero_rule_counts"] is True
    assert result["drc_pass"] is False
    assert result["drc_context_qualified"] is False
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize(
    "mutation",
    (
        "gds_bytes",
        "report_total",
        "false_pass",
        "source_binding",
        "script_bytes",
        "empty_shape_claim",
    ),
)
def test_drc_audit_rejects_tampered_archive(tmp_path: Path, mutation: str) -> None:
    runs = list(_private_runs())
    index = {
        "gds_bytes": 1,
        "report_total": 3,
        "false_pass": 3,
        "source_binding": 3,
        "script_bytes": 3,
        "empty_shape_claim": 0,
    }[mutation]
    copied = tmp_path / runs[index].name
    shutil.copytree(runs[index], copied)
    runs[index] = copied
    if mutation == "gds_bytes":
        path = copied / "layout.gds"
        path.write_bytes(path.read_bytes() + b"tamper")
    elif mutation == "report_total":
        path = copied / "DRC.rep"
        report = path.read_text(encoding="utf-8", errors="replace")
        modified, count = re.subn(
            r"(TOTAL DRC Results Generated:)\s+\d+\s+\(\d+\)",
            r"\g<1> 0 (0)", report, count=1,
        )
        assert count == 1
        path.write_text(modified, encoding="utf-8")
    elif mutation in ("false_pass", "source_binding"):
        path = copied / "run_status.json"
        status = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "false_pass":
            status["drc_pass"] = True
        else:
            status["source_gds_run"] = "unrelated_stream"
        path.write_text(json.dumps(status), encoding="utf-8")
    elif mutation == "script_bytes":
        path = copied / "remote_run_drc.sh"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    else:
        path = copied / "summary.txt"
        summary = path.read_text(encoding="utf-8", errors="replace")
        modified, count = re.subn(r"(?m)^(\s*Rectangles:\s*)0$", r"\g<1>1", summary, count=1)
        assert count == 1
        path.write_text(modified, encoding="utf-8")
    with pytest.raises(ValueError):
        audit_pdk_rf_drc_probe(*runs)
