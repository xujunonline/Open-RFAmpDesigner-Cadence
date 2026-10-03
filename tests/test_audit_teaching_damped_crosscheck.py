import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.experiments import audit_teaching_damped_crosscheck as module


def _sources():
    root = Path("results/runs")
    oa = root / "teaching_oa" / "20260926T162244Z_bf1bf86c"
    direct = root / "teaching_lna" / "20260926T154709Z_0b5d75fe"
    if not oa.is_dir() or not direct.is_dir():
        pytest.skip("private Cadence archives are not part of the public test fixture")
    return oa, direct


def _cascode_sources():
    root = Path("results/runs")
    oa = root / "teaching_oa" / "20260926T165347Z_36f2fb06"
    direct = root / "teaching_lna" / "20260926T164104Z_62c9f88f"
    if not oa.is_dir() or not direct.is_dir():
        pytest.skip("private Cadence cascode archives are not part of the public test fixture")
    return oa, direct


def test_real_damped_oa_and_standalone_spectre_agree():
    oa, direct = _sources()
    report = module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")
    assert report["points"] == 161
    assert max(report["maximum_complex_s_delta"].values()) < 1e-8
    assert max(report["maximum_noise_delta"].values()) < 1e-8
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_real_cascode_oa_and_standalone_spectre_agree():
    oa, direct = _cascode_sources()
    report = module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")
    assert report["status"] == "verified_teaching_cascode_crosscheck"
    assert report["circuit_class"] == "teaching_mos1_cascode"
    assert report["points"] == 161
    assert max(report["maximum_complex_s_delta"].values()) < 1e-8
    assert max(report["maximum_noise_delta"].values()) < 1e-8
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_cascode_crosscheck_rejects_damped_direct_source():
    oa, _ = _cascode_sources()
    _, damped_direct = _sources()
    with pytest.raises(ValueError, match="not the same 161-point teaching candidate"):
        module.build_teaching_damped_crosscheck(oa, damped_direct, "read_only_test")


def test_real_vcas_1p05_oa_matches_direct_and_rejects_wrong_bias():
    oa = Path("results/runs/teaching_oa/20260926T174324Z_476a26f3")
    direct = Path("results/runs/teaching_lna/20260926T173228Z_7ad352b4")
    _, old_direct = _cascode_sources()
    if not oa.is_dir() or not direct.is_dir():
        pytest.skip("private VCAS 1.05 V Cadence archives are unavailable")
    report = module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")
    assert max(report["maximum_complex_s_delta"].values()) < 1e-8
    assert max(delta for fields in report["maximum_device_op_delta"].values()
               for delta in fields.values()) < 1e-12
    with pytest.raises(ValueError, match="not the same 161-point teaching candidate"):
        module.build_teaching_damped_crosscheck(oa, old_direct, "read_only_test")


def test_cascode_crosscheck_compares_exported_device_op():
    _, direct = _cascode_sources()
    oa = Path("results/runs/teaching_oa/20260926T172320Z_0661fd2f")
    if not oa.is_dir():
        pytest.skip("private OA cascode operating-point archive is unavailable")
    report = module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")
    assert max(delta for fields in report["maximum_device_op_delta"].values()
               for delta in fields.values()) < 1e-12


def test_cascode_crosscheck_rejects_device_op_mismatch(monkeypatch):
    _, direct = _cascode_sources()
    oa = Path("results/runs/teaching_oa/20260926T172320Z_0661fd2f")
    if not oa.is_dir():
        pytest.skip("private OA cascode operating-point archive is unavailable")
    original = module.audit_teaching_oa

    def changed_op(path):
        result = original(path)
        result["device_op"]["M2"]["gm"] += 0.01
        return result

    monkeypatch.setattr(module, "audit_teaching_oa", changed_op)
    with pytest.raises(ValueError, match="device operating points differ"):
        module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")


def test_crosscheck_rejects_changed_raw_s21(monkeypatch):
    oa, direct = _sources()
    original = module.parse_complex_trace

    def shifted_s21(path, signal):
        frequencies, values = original(path, signal)
        if signal == "s21":
            values = list(values)
            values[80] += 0.01
        return frequencies, values

    monkeypatch.setattr(module, "parse_complex_trace", shifted_s21)
    with pytest.raises(ValueError, match="PSFASCII and high-precision OCEAN"):
        module.build_teaching_damped_crosscheck(oa, direct, "read_only_test")


def test_rehashed_report_change_is_rejected(tmp_path):
    oa, direct = _sources()
    report_dir = tmp_path / "tampered_report"
    report_dir.mkdir()
    report = module.build_teaching_damped_crosscheck(oa, direct, report_dir.name)
    report["maximum_frequency_delta_hz"] = 100.0
    (report_dir / "metrics.json").write_text(json.dumps(report), encoding="utf-8")
    write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
    with pytest.raises(ValueError, match="differs from source archives"):
        module.audit_teaching_damped_crosscheck_report(report_dir, oa.parent, direct.parent)


def test_rehashed_cascode_report_change_is_rejected(tmp_path):
    oa, direct = _cascode_sources()
    report_dir = tmp_path / "tampered_cascode_report"
    report_dir.mkdir()
    report = module.build_teaching_damped_crosscheck(oa, direct, report_dir.name)
    report["maximum_noise_delta"]["NF"] = 1e-5
    (report_dir / "metrics.json").write_text(json.dumps(report), encoding="utf-8")
    write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
    with pytest.raises(ValueError, match="differs from source archives"):
        module.audit_teaching_damped_crosscheck_report(report_dir, oa.parent, direct.parent)
