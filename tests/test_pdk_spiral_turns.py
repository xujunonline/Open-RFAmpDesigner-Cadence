from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_pdk_spiral_turns import _ARTIFACTS, audit_pdk_spiral_turns
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_spiral_turns import render_spiral_turns_netlist, render_spiral_turns_wrapper


_SOURCE = _PRIVATE_ROOT / "passive_quality_reference" / "20260926T205333Z_b96aea29"
_RUNS = {
    4: _PRIVATE_ROOT / "pdk_spiral_turns" / "20260927T053918Z_b08774a7",
    5: _PRIVATE_ROOT / "pdk_spiral_turns" / "20260927T053955Z_6aa2d00e",
}


def _private(turns: int) -> Path:
    run = _RUNS[turns]
    if not run.is_dir():
        pytest.skip("private authorized spiral turns run is unavailable")
    return run


@pytest.mark.parametrize("turns", (4, 5))
def test_real_spiral_turns_runs_are_audited_but_not_qualified(turns: int) -> None:
    run = _private(turns)
    assert audit_pdk_spiral_turns(run) == {
        "status": "verified", "run_id": run.name,
        "physical_qualification": False, "not_lna_result": True,
    }
    payload = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert payload["turns_property"] == turns
    assert payload["metrics"]["status"] == "response_screen_fail"
    assert payload["spec_pass"] is None
    assert payload["cdf_callback_validated"] is False
    assert payload["maximum_complex_s11_delta_from_default"] > 0.5


@pytest.mark.parametrize("mutation", (
    "netlist", "raw_sp", "metrics", "false_physical", "false_lna", "source_id", "status",
))
def test_spiral_turns_audit_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private(4)
    with tempfile.TemporaryDirectory(prefix="test_spiral_turns_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        if mutation == "netlist":
            path = run / "netlist.scs"
            original = path.read_bytes()
            assert original.count(b"nr=4 lay=10") == 1
            path.write_bytes(original.replace(b"nr=4 lay=10", b"nr=5 lay=10"))
        elif mutation == "raw_sp":
            path = run / "sp.sp"
            original = path.read_bytes()
            sample = b"-9.264205228784221e-01"
            assert original.count(sample) == 1
            path.write_bytes(original.replace(sample, b"-8.264205228784221e-01"))
        elif mutation in {"metrics", "false_physical", "false_lna"}:
            path = run / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "metrics":
                payload["metrics"]["minimum_q_in_band"] = 100.0
            elif mutation == "false_physical":
                payload["physical_qualification"] = True
            else:
                payload["not_lna_result"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = run / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "source_id":
                payload["source_run_id"] = "../../unrelated"
            else:
                payload["status"] = "simulation_failed"
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(run, _ARTIFACTS)
        (run / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            audit_pdk_spiral_turns(run)


def test_false_spec_pass_cannot_build_a_manifest() -> None:
    source = _private(4)
    with tempfile.TemporaryDirectory(prefix="test_spiral_turns_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        run = Path(root) / source.name
        shutil.copytree(source, run)
        path = run / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(run, _ARTIFACTS)


def test_turns_render_changes_only_the_expected_property() -> None:
    if not _SOURCE.is_dir():
        pytest.skip("private authorized default spiral source is unavailable")
    source = (_SOURCE / "netlist.scs").read_bytes()
    rendered = render_spiral_turns_netlist(source, 4)
    assert rendered == source.replace(b"nr=3 lay=10", b"nr=4 lay=10")
    assert b'sp sp ports=[PORT1] start=500M stop=30G lin=590' in render_spiral_turns_wrapper()
    with pytest.raises(ValueError):
        render_spiral_turns_netlist(source, 3)
    with pytest.raises(ValueError):
        render_spiral_turns_netlist(source, 10)
    with pytest.raises(ValueError):
        render_spiral_turns_netlist(rendered, 5)
