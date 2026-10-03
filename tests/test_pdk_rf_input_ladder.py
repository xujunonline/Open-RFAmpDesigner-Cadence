from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_pdk_rf_input_ladder import _ARTIFACTS, audit_pdk_rf_input_ladder
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_rf_input_ladder import render_ladder_netlist, render_ladder_wrapper


_RUN = _PRIVATE_ROOT / "pdk_rf_input_ladder" / "20260927T051926Z_93744611"
_PARAMS = {"c_outer_ff": 181.0, "c_inner_ff": 10.0, "l_middle_nh": 1.65, "l_inner_nh": 5.6}


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private authorized RF input ladder run is unavailable")
    return _RUN


def test_real_input_ladder_is_audited_but_not_a_qualified_lna() -> None:
    assert audit_pdk_rf_input_ladder(_private()) == {
        "status": "verified", "points": 161,
        "not_lna_result": True, "physical_qualification": False,
    }
    payload = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert payload["spec_pass"] is None
    assert -7 < payload["metrics"]["s11_db"] < -6
    assert payload["metrics"]["s21_db"] < 0
    assert payload["metrics"]["nf_db"] > 10
    assert payload["maximum_predicted_to_spectre_complex_s11_delta"] < 1e-6


@pytest.mark.parametrize("mutation", (
    "netlist", "raw_sp", "metrics", "false_physical", "false_lna", "source_id", "status",
))
def test_ladder_audit_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_ladder_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        if mutation == "netlist":
            path = run / "netlist.scs"
            original = path.read_bytes()
            assert original.count(b"C_MATCH_OUT (") == 1
            path.write_bytes(original.replace(b"C_MATCH_OUT (", b"C_FALSE_OUT ("))
        elif mutation == "raw_sp":
            path = run / "sp.sp"
            original = path.read_bytes()
            sample = b"-3.601431960828911e-01"
            assert original.count(sample) == 1
            path.write_bytes(original.replace(sample, b"-1.601431960828911e-01"))
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
            audit_pdk_rf_input_ladder(run)


def test_false_spec_pass_cannot_build_a_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_rf_ladder_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        path = run / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(run, _ARTIFACTS)


def test_ladder_render_is_bounded_to_one_input_port() -> None:
    source = b"PORT1 (in 0) port r=50 num=1 type=sine\nCIN (in rf_in) capacitor c=5p\n"
    rendered = render_ladder_netlist(source, _PARAMS)
    assert b"PORT1 (match_out 0)" in rendered
    assert b"C_MATCH_OUT (match_out match_mid)" in rendered
    assert b"L_MATCH_MID (match_mid 0)" in rendered
    assert b"L_MATCH_IN (match_mid in)" in rendered
    assert b"C_MATCH_IN (in 0)" in rendered
    assert b"CIN (in rf_in) capacitor c=5p" in rendered
    assert b"sp sp start=8G stop=12G lin=160" in render_ladder_wrapper()
    with pytest.raises(ValueError):
        render_ladder_netlist(rendered, _PARAMS)
    with pytest.raises(ValueError):
        render_ladder_netlist(b"PORT1 (other 0) port r=50 num=1 type=sine\n", _PARAMS)
