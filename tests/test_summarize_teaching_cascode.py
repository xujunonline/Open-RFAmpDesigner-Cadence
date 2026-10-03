import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.experiments import summarize_teaching_cascode as module


def _sources():
    root = Path("results/runs/teaching_lna")
    common = root / "20260926T154709Z_0b5d75fe"
    cascode = root / "20260926T164104Z_62c9f88f"
    if not common.is_dir() or not cascode.is_dir():
        pytest.skip("private Cadence archives are not part of the public test fixture")
    return common, cascode


def test_real_cascode_comparison_is_evidenced():
    common, cascode = _sources()
    report = module.build_cascode_comparison(common, cascode, "read_only_test")
    assert report["points"] == 161
    assert report["metric_delta_cascode_minus_common"]["s21_db"] < 0
    assert report["metric_delta_cascode_minus_common"]["nf_db"] > 0
    assert report["cascode_device_op"]["m1_vds_minus_vdsat_v"] > 0
    assert report["cascode_device_op"]["m2_vds_minus_vdsat_v"] > 0
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_cascode_comparison_rejects_mismatched_design(monkeypatch):
    common, cascode = _sources()
    original = module.read_evidenced_metrics

    def wrong_design(path):
        payload = original(path)
        if path == cascode:
            payload["design_parameters"] = {**payload["design_parameters"], "rdamp_ohm": 250.0}
        return payload

    monkeypatch.setattr(module, "read_evidenced_metrics", wrong_design)
    with pytest.raises(ValueError, match="matched 161-point"):
        module.build_cascode_comparison(common, cascode, "read_only_test")


def test_cascode_comparison_rejects_changed_frequency_grid(monkeypatch):
    common, cascode = _sources()
    original = module.parse_complex_trace

    def shifted_grid(path, signal):
        frequencies, values = original(path, signal)
        if path == cascode / "sp.sp" and signal == "s21":
            frequencies = list(frequencies)
            frequencies[80] += 1e6
        return frequencies, values

    monkeypatch.setattr(module, "parse_complex_trace", shifted_grid)
    with pytest.raises(ValueError, match="frequency grids differ"):
        module.build_cascode_comparison(common, cascode, "read_only_test")


def test_cascode_rehashed_report_change_is_rejected(tmp_path):
    common, cascode = _sources()
    report_dir = tmp_path / "tampered_report"
    report_dir.mkdir()
    report = module.build_cascode_comparison(common, cascode, report_dir.name)
    report["metric_delta_cascode_minus_common"]["nf_db"] = -1.0
    (report_dir / "metrics.json").write_text(json.dumps(report), encoding="utf-8")
    write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
    with pytest.raises(ValueError, match="differs from source archives"):
        module.audit_cascode_comparison_report(report_dir, common.parent)
