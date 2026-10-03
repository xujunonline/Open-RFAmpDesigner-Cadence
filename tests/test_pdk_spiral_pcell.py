from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments import audit_pdk_spiral_pcell as module
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_SUMMARY = _PRIVATE_ROOT / "pdk_spiral_layout" / "summary_20260927_01"


def _private() -> Path:
    if not _SUMMARY.is_dir():
        pytest.skip("private authorized spiral PCell evidence is unavailable")
    return _SUMMARY


def test_real_spiral_pcell_geometry_is_audited_but_not_qualified() -> None:
    assert module.audit_pdk_spiral_pcell_report(_private()) == {
        "status": "verified", "physical_qualification": False,
        "cdf_callback_validated": False, "drc_validated": False,
    }
    payload = json.loads((_SUMMARY / "metrics.json").read_text(encoding="utf-8"))
    assert payload["two_new_user_layout_cells_saved"] is True
    assert payload["failed_read_excluded"] is True
    assert payload["core_bbox_changed"] is True
    assert payload["spec_pass"] is None


@pytest.mark.parametrize("mutation", (
    "false_physical", "false_cdf", "source_nr", "source_oa", "failed_read_promotion", "script",
))
def test_spiral_pcell_audit_rejects_rehashed_tampering(
    mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _private().parent
    with tempfile.TemporaryDirectory(prefix="test_spiral_pcell_", dir=_PRIVATE_ROOT.resolve()) as root:
        parent = Path(root)
        for name, _, _ in module._SOURCES.values():
            shutil.copytree(source / name, parent / name)
        summary = parent / _SUMMARY.name
        shutil.copytree(_SUMMARY, summary)
        monkeypatch.setattr(module, "_ROOT", parent)
        if mutation in {"false_physical", "false_cdf"}:
            path = summary / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["physical_qualification" if mutation == "false_physical"
                    else "cdf_callback_validated"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "source_nr":
            path = parent / "nr4_20260927_01" / "report.txt"
            original = path.read_bytes()
            assert original.count(b'name="nr" type="string" value="4"') == 1
            path.write_bytes(original.replace(b'name="nr" type="string" value="4"',
                                              b'name="nr" type="string" value="5"'))
        elif mutation == "source_oa":
            path = parent / "default_20260927_01" / "layout.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "failed_read_promotion":
            path = parent / "read_saved_20260927_01" / "report.txt"
            path.write_bytes(path.read_bytes().replace(b"opened=nil", b"opened=t"))
        else:
            path = parent / "nr4_20260927_01" / "create.ocn"
            path.write_bytes(path.read_bytes().replace(b"nr4 PCell complete", b"false PCell complete"))
        manifest = build_evidence_manifest(summary, {"metrics": "metrics.json"})
        (summary / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            module.audit_pdk_spiral_pcell_report(summary)


def test_false_spiral_pcell_spec_pass_cannot_build_a_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_spiral_pcell_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        summary = Path(root) / source.name
        shutil.copytree(source, summary)
        path = summary / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(summary, {"metrics": "metrics.json"})


def test_spiral_pcell_bbox_parser_rejects_malformed_geometry() -> None:
    with pytest.raises(ValueError):
        module._bbox("bbox=((0 0) (0 1))")
    with pytest.raises(ValueError):
        module._bbox("bbox=((0 0) (1))")
