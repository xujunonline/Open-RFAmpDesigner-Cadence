from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments import audit_pdk_spiral_pcell as pcell_module
from orfadc.experiments import audit_pdk_spiral_stream as stream_module
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_SUMMARY = _PRIVATE_ROOT / "pdk_spiral_stream" / "summary_20260927_01"


def _private() -> Path:
    if not _SUMMARY.is_dir():
        pytest.skip("private authorized spiral stream evidence is unavailable")
    return _SUMMARY


def test_real_spiral_gds_pair_is_audited_but_not_drc_ready() -> None:
    assert stream_module.audit_pdk_spiral_stream_report(_private()) == {
        "status": "verified", "drc_ready": False, "physical_qualification": False,
    }
    report = json.loads((_SUMMARY / "metrics.json").read_text(encoding="utf-8"))
    assert report["gds_files_distinct"] is True
    assert report["gds_geometry_present"] is True
    assert report["stream_warning_count_each"] == 2
    assert report["drc_validated"] is False and report["spec_pass"] is None


@pytest.mark.parametrize("mutation", (
    "gds", "via_report", "log", "status", "false_drc_ready", "false_physical",
))
def test_spiral_stream_audit_rejects_rehashed_tampering(
    mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private()
    with tempfile.TemporaryDirectory(prefix="test_spiral_stream_", dir=_PRIVATE_ROOT.resolve()) as root:
        parent = Path(root)
        layout_root = parent / "pdk_spiral_layout"
        stream_root = parent / "pdk_spiral_stream"
        for name, _, _ in pcell_module._SOURCES.values():
            shutil.copytree(_PRIVATE_ROOT / "pdk_spiral_layout" / name, layout_root / name)
        shutil.copytree(_PRIVATE_ROOT / "pdk_spiral_layout" / "summary_20260927_01",
                        layout_root / "summary_20260927_01")
        shutil.copytree(_PRIVATE_ROOT / "pdk_spiral_layout" / stream_module._VIA_RUN,
                        layout_root / stream_module._VIA_RUN)
        for run_name in stream_module._RUNS.values():
            shutil.copytree(_PRIVATE_ROOT / "pdk_spiral_stream" / run_name, stream_root / run_name)
        summary = stream_root / _SUMMARY.name
        shutil.copytree(_SUMMARY, summary)
        monkeypatch.setattr(pcell_module, "_ROOT", layout_root)
        monkeypatch.setattr(stream_module, "_LAYOUT_ROOT", layout_root)
        monkeypatch.setattr(stream_module, "_STREAM_ROOT", stream_root)
        default = stream_root / stream_module._RUNS["default"]
        if mutation == "gds":
            path = default / "layout.gds"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "via_report":
            path = layout_root / stream_module._VIA_RUN / "report.txt"
            original = path.read_bytes()
            assert b"via_master_count=91" in original
            path.write_bytes(original.replace(b"via_master_count=91", b"via_master_count=90"))
        elif mutation == "log":
            path = default / "strmout.log"
            original = path.read_bytes()
            assert b"'2' warning(s)" in original
            path.write_bytes(original.replace(b"'2' warning(s)", b"'0' warning(s)"))
        elif mutation == "status":
            path = default / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_cell"] = "different_cell"
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = summary / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["drc_ready" if mutation == "false_drc_ready"
                    else "physical_qualification"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(summary, {"metrics": "metrics.json"})
        (summary / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            stream_module.audit_pdk_spiral_stream_report(summary)


def test_false_spiral_gds_spec_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_spiral_stream_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        summary = Path(root) / source.name
        shutil.copytree(source, summary)
        path = summary / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(summary, {"metrics": "metrics.json"})
