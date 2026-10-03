from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.summarize_teaching_bias import audit_teaching_bias_summary


_REPORT = _PRIVATE_ROOT / "teaching_bias_summaries" / "20260927T044111Z_72630a31"


def _private() -> Path:
    if not _REPORT.is_dir():
        pytest.skip("private matched MOS1 bias summary is unavailable")
    return _REPORT


def _rehash(report: Path) -> None:
    manifest = build_evidence_manifest(report, {"metrics": "metrics.json", "csv": "bias_sweep.csv"})
    (report / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_real_same_netlist_bias_summary_reaudits() -> None:
    result = audit_teaching_bias_summary(_private())
    assert result == {"status": "verified", "runs": 3, "not_lna_result": True}


@pytest.mark.parametrize("mutation", (
    "csv_rehashed", "cost_rehashed", "source_ids_rehashed", "unsafe_ids_rehashed", "false_lna_rehashed",
))
def test_bias_summary_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_bias_audit_", dir=_PRIVATE_ROOT.resolve()) as root:
        report = Path(root) / source.name
        shutil.copytree(source, report)
        if mutation == "csv_rehashed":
            path = report / "bias_sweep.csv"
            path.write_bytes(path.read_bytes().replace(b"3.355486132655942", b"9.355486132655942"))
        else:
            path = report / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "cost_rehashed":
                payload["rows"][0]["nf_db"] += 1.0
            elif mutation == "source_ids_rehashed":
                payload["run_ids"][0] = payload["run_ids"][1]
            elif mutation == "unsafe_ids_rehashed":
                payload["run_ids"][0] = {"unexpected": "object"}
            else:
                payload["not_lna_result"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
        _rehash(report)
        with pytest.raises(ValueError):
            audit_teaching_bias_summary(report)
