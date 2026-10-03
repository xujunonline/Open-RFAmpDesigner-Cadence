import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments import summarize_teaching_cascode_bias as module


def _sources():
    root = Path("results/runs/teaching_lna")
    paths = [root / name for name in (
        "20260926T173201Z_e6afbeb0", "20260926T164104Z_62c9f88f", "20260926T173228Z_7ad352b4",
    )]
    if any(not path.is_dir() for path in paths):
        pytest.skip("private Cadence cascode bias archives are unavailable")
    return paths


def test_real_cascode_bias_summary_is_rebuilt_from_three_runs():
    report = module.build_cascode_bias_summary(_sources(), "read_only_test")
    assert [row["vcas_v"] for row in report["rows"]] == [0.85, 0.95, 1.05]
    assert report["rows"][0]["m1_vds_margin_v"] < 0.01
    assert report["rows"][2]["m1_vds_margin_v"] > 0.2
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_cascode_bias_summary_rejects_duplicate_and_noncascode_source():
    sources = _sources()
    with pytest.raises(ValueError, match="distinct source runs"):
        module.build_cascode_bias_summary([sources[0], sources[0]], "read_only_test")
    common = sources[0].parent / "20260926T154709Z_0b5d75fe"
    if not common.is_dir():
        pytest.skip("private common-source comparison archive is unavailable")
    with pytest.raises(ValueError, match="not a complete 161-point teaching run"):
        module.build_cascode_bias_summary([sources[0], common], "read_only_test")


def test_cascode_bias_summary_rejects_frequency_mismatch(monkeypatch):
    sources = _sources()
    original = module.parse_complex_trace

    def shifted_grid(path, signal):
        frequencies, values = original(path, signal)
        if sources[1].name in str(path):
            frequencies = list(frequencies)
            frequencies[80] += 1e6
        return frequencies, values

    monkeypatch.setattr(module, "parse_complex_trace", shifted_grid)
    with pytest.raises(ValueError, match="frequency grids differ"):
        module.build_cascode_bias_summary(sources, "read_only_test")


def _copied_report(tmp_path):
    original = Path("results/runs/teaching_cascode_bias_summaries/20260926T173523Z_c49cbb86")
    if not original.is_dir():
        pytest.skip("private Cadence bias report is unavailable")
    target = tmp_path / original.name
    shutil.copytree(original, target)
    return target


def _rehash(report_dir):
    path = report_dir / "evidence_manifest.json"
    previous = json.loads(path.read_text(encoding="utf-8"))
    paths = {key: entry["path"] for key, entry in previous["artifacts"].items()}
    path.write_text(json.dumps(build_evidence_manifest(report_dir, paths)), encoding="utf-8")


def test_real_cascode_bias_report_is_read_only_auditable(tmp_path):
    report = _copied_report(tmp_path)
    result = module.audit_cascode_bias_report(report, _sources()[0].parent)
    assert result["status"] == "verified" and result["source_runs"] == 3


def test_rehashed_cascode_bias_metric_tamper_is_rejected(tmp_path):
    report = _copied_report(tmp_path)
    path = report / "metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][1]["s21_db"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash(report)
    with pytest.raises(ValueError, match="differs from source archives"):
        module.audit_cascode_bias_report(report, _sources()[0].parent)


def test_rehashed_cascode_bias_csv_tamper_is_rejected(tmp_path):
    report = _copied_report(tmp_path)
    path = report / "bias_sweep.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("0.85", "0.86", 1), encoding="utf-8")
    _rehash(report)
    with pytest.raises(ValueError, match="CSV differs from source archives"):
        module.audit_cascode_bias_report(report, _sources()[0].parent)
