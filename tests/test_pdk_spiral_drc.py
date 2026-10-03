from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments import audit_pdk_spiral_drc as drc_module
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_pdk_spiral_drc import render_spiral_drc_script


_SUMMARY = _PRIVATE_ROOT / "pdk_spiral_drc" / "summary_20260927_01"


def _private() -> Path:
    if not _SUMMARY.is_dir():
        pytest.skip("private authorized spiral DRC evidence is unavailable")
    return _SUMMARY


def test_real_spiral_drc_pair_has_violations_and_no_qualification() -> None:
    assert drc_module.audit_pdk_spiral_drc_report(_private()) == {
        "status": "verified", "drc_pass": False,
        "drc_input_qualified": False, "physical_qualification": False,
    }
    report = json.loads((_SUMMARY / "metrics.json").read_text(encoding="utf-8"))
    assert report["rulechecks_executed_each"] == 2319
    assert report["results"]["default"]["results"] == 83
    assert report["results"]["nr4"]["results"] == 85
    assert report["same_source_deck"] is True
    assert report["runtime_warnings_present"] is True
    assert report["spec_pass"] is None


@pytest.mark.parametrize("mutation", (
    "gds", "report", "script", "source_hashes", "status", "false_drc_pass",
    "false_input_qualified", "false_physical",
))
def test_spiral_drc_audit_rejects_rehashed_tampering(
    mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private()
    with tempfile.TemporaryDirectory(prefix="test_spiral_drc_", dir=_PRIVATE_ROOT.resolve()) as root:
        run_root = Path(root) / "pdk_spiral_drc"
        for name in drc_module._RUNS.values():
            shutil.copytree(_PRIVATE_ROOT / "pdk_spiral_drc" / name, run_root / name)
        summary = run_root / _SUMMARY.name
        shutil.copytree(_SUMMARY, summary)
        monkeypatch.setattr(drc_module, "_ROOT", run_root)
        default = run_root / drc_module._RUNS["default"]
        if mutation == "gds":
            path = default / "remote_input.gds"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "report":
            path = default / "DRC.rep"
            original = path.read_bytes()
            altered, count = re.subn(
                rb"TOTAL DRC Results Generated:\s+83 \(83\)",
                b"TOTAL DRC Results Generated: 0 (0)", original,
            )
            assert count == 1
            path.write_bytes(altered)
        elif mutation == "script":
            path = default / "remote_run_drc.sh"
            path.write_bytes(path.read_bytes() + b"\n# tampered\n")
        elif mutation == "source_hashes":
            path = default / "source_hashes.txt"
            original = path.read_bytes()
            path.write_bytes(b"0" + original[1:])
        elif mutation == "status":
            path = default / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_gds_sha256"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = summary / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            key = {
                "false_drc_pass": "drc_pass",
                "false_input_qualified": "drc_input_qualified",
                "false_physical": "physical_qualification",
            }[mutation]
            payload[key] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(summary, {"metrics": "metrics.json"})
        (summary / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            drc_module.audit_pdk_spiral_drc_report(summary)


def test_false_spiral_drc_spec_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_spiral_drc_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        summary = Path(root) / source.name
        shutil.copytree(source, summary)
        path = summary / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(summary, {"metrics": "metrics.json"})


def test_spiral_drc_renderer_rejects_unsafe_inputs() -> None:
    with pytest.raises(ValueError):
        render_spiral_drc_script("/tmp/a;rm", "/tmp/deck", "spiral")
    with pytest.raises(ValueError):
        render_spiral_drc_script("/tmp/a", "/tmp/deck", "spiral;rm")
