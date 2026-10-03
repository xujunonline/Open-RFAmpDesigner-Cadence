from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.hb_metrics import extract_hb_input_available_power
from orfadc.experiments.audit_pdk_rf_ladder_hb import _ARTIFACTS, audit_pdk_rf_ladder_hb
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_rf_ladder_hb import render_pdk_rf_ladder_hb


_SOURCE = (
    b'include "ade_e.scs"\n'
    b'PORT1 (match_out 0) port r=50 num=1 type=sine\n'
    b'PORT2 (outp outn) port r=1787 num=2 type=sine\n'
    b'C_MATCH_OUT (match_out match_mid) capacitor c=180f\n'
)
_RUN = _PRIVATE_ROOT / "pdk_rf_ladder_hb" / "20260927T104246Z_1b3b9a4b"
_LADDER = _PRIVATE_ROOT / "pdk_rf_input_ladder" / "20260927T051926Z_93744611"
_FILES = {**_ARTIFACTS, "metrics": "metrics.json", "hb_summary": "hb_fundamental.csv"}


def _private() -> tuple[Path, Path]:
    if not _RUN.is_dir() or not _LADDER.is_dir():
        pytest.skip("private RF ladder HB archives are unavailable")
    return _RUN, _LADDER


def test_ladder_hb_keeps_matching_network_in_drive_path() -> None:
    output = render_pdk_rf_ladder_hb(_SOURCE, -70)
    assert b"PORT1 (match_out 0) port r=50 num=1 type=sine dbm=-70 freq=10G" in output
    assert b"C_MATCH_OUT (match_out match_mid) capacitor c=180f" in output
    assert b"PORT2 (outp outn) port r=1787 num=2 type=dc" in output
    assert b"maxharms=[7]" in output
    assert b"ladder_hb.s2p" in output
    assert output.count(b"hb hb") == 1


@pytest.mark.parametrize("input_dbm,harmonics", ((True, 7), (-101, 7), (1, 7), (-70, 8)))
def test_ladder_hb_rejects_invalid_drive(input_dbm: int, harmonics: int) -> None:
    with pytest.raises(ValueError):
        render_pdk_rf_ladder_hb(_SOURCE, input_dbm, harmonics=harmonics)


@pytest.mark.parametrize("source", (
    _SOURCE.replace(b"match_out 0", b"in 0"),
    _SOURCE + b"PORT1 (match_out 0) port r=50 num=1 type=sine\n",
    _SOURCE + b"hb hb fundfreqs=[10G] maxharms=[7]\n",
    _SOURCE.replace(b'include "ade_e.scs"', b'include "other.scs"'),
))
def test_ladder_hb_rejects_wrong_or_ambiguous_source(source: bytes) -> None:
    with pytest.raises(ValueError):
        render_pdk_rf_ladder_hb(source, -70)


def test_real_ladder_hb_reaudits_and_binds_input_reference_plane() -> None:
    run, ladder = _private()
    result = audit_pdk_rf_ladder_hb(run, ladder)
    assert result["status"] == "verified_diagnostic_only"
    assert abs(result["hb_minus_s21_db"]) < 0.01
    assert result["not_lna_result"] is True and result["spec_pass"] is None
    at_port = extract_hb_input_available_power(
        run / "hb.fd.pss_hb", fundamental_hz=10e9, input_node="match_out",
    )
    at_inner_node = extract_hb_input_available_power(
        run / "hb.fd.pss_hb", fundamental_hz=10e9, input_node="in",
    )
    assert at_port == pytest.approx(-70.0, abs=0.01)
    assert abs(at_inner_node - at_port) > 5.0


@pytest.mark.parametrize("mutation", ("metrics", "drive", "port", "hb_raw"))
def test_ladder_hb_audit_rejects_rehashed_tampering(mutation: str) -> None:
    run, ladder = _private()
    with tempfile.TemporaryDirectory(prefix="test_ladder_hb_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / run.name
        shutil.copytree(run, copied)
        if mutation == "metrics":
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"]["power_gain_db"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "drive":
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["input_dbm"] = -60
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "port":
            path = copied / "netlist.scs"
            path.write_bytes(path.read_bytes().replace(b"PORT1 (match_out 0)", b"PORT1 (in 0)", 1))
        else:
            path = copied / "hb.fd.pss_hb"
            path.write_bytes(path.read_bytes().replace(
                b'"PORT1:r" 5.000000000000000e+01',
                b'"PORT1:r" 7.500000000000000e+01', 1,
            ))
        manifest = build_evidence_manifest(copied, _FILES)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            audit_pdk_rf_ladder_hb(copied, ladder)


def test_ladder_hb_false_pass_cannot_build_manifest() -> None:
    run, _ = _private()
    with tempfile.TemporaryDirectory(prefix="test_ladder_hb_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / run.name
        shutil.copytree(run, copied)
        path = copied / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["not_lna_result"] = False
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(copied, _FILES)
