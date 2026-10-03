from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_pdk_rf_input_lmatch import _ARTIFACTS, audit_pdk_rf_input_lmatch
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_rf_input_lmatch import render_input_lmatch, render_lmatch_wrapper


_RUN = _PRIVATE_ROOT / "pdk_rf_input_lmatch" / "20260927T050226Z_8ebc767d"


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private authorized RF input L-match run is unavailable")
    return _RUN


def test_real_input_lmatch_is_audited_but_not_a_qualified_lna() -> None:
    result = audit_pdk_rf_input_lmatch(_private())
    assert result == {
        "status": "verified", "points": 161,
        "not_lna_result": True, "physical_qualification": False,
    }
    metrics = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["spec_pass"] is None
    assert metrics["metrics"]["s11_db"] > -1
    assert metrics["metrics"]["s21_db"] < 0
    assert metrics["metrics"]["nf_db"] > 10
    assert metrics["maximum_predicted_to_spectre_complex_s11_delta"] < 1e-6


@pytest.mark.parametrize("mutation", (
    "netlist", "raw_sp", "metrics", "false_physical", "false_lna", "source_id", "status",
))
def test_lmatch_audit_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_lmatch_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        if mutation == "netlist":
            path = run / "netlist.scs"
            path.write_bytes(path.read_bytes().replace(b"C_MATCH (", b"C_FALSE ("))
        elif mutation == "raw_sp":
            path = run / "sp.sp"
            original = path.read_bytes()
            assert original.count(b"7.921661852184749e-01") == 1
            path.write_bytes(original.replace(b"7.921661852184749e-01", b"5.921661852184749e-01"))
        elif mutation in {"metrics", "false_physical", "false_lna"}:
            path = run / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "metrics":
                payload["metrics"]["s11_db"] = -30.0
            elif mutation == "false_physical":
                payload["physical_qualification"] = True
            else:
                payload["not_lna_result"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = run / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "source_id":
                payload["source_active_run_id"] = "../../unrelated"
            else:
                payload["status"] = "simulation_failed"
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(run, _ARTIFACTS)
        (run / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            audit_pdk_rf_input_lmatch(run)


def test_false_spec_pass_cannot_build_a_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_lmatch_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        path = run / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(run, _ARTIFACTS)


def test_lmatch_render_is_bounded_to_one_input_port() -> None:
    source = b"PORT1 (in 0) port r=50 num=1 type=sine\nCIN (in rf_in) capacitor c=5p\n"
    rendered = render_input_lmatch(source, 3e-9, 47e-15)
    assert b"PORT1 (match_in 0)" in rendered
    assert b"C_MATCH (match_in in)" in rendered
    assert b"L_MATCH (in 0)" in rendered
    assert b"CIN (in rf_in) capacitor c=5p" in rendered
    assert b"sp sp start=8G stop=12G lin=160" in render_lmatch_wrapper()
    with pytest.raises(ValueError):
        render_input_lmatch(rendered, 3e-9, 47e-15)
    with pytest.raises(ValueError):
        render_input_lmatch(b"PORT1 (other 0) port r=50 num=1 type=sine\n", 3e-9, 47e-15)
