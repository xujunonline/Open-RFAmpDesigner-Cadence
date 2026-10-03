from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_capture_probe import (
    audit_virtuoso_form_capture_probe,
)
from orfadc.experiments.run_virtuoso_form_focus_probe import run_virtuoso_form_focus_probe


_FORM = Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a")
_CAPTURE = Path("results/runs/virtuoso_form_focus_probe/20260927T094712Z_fc44a02c")


def _private() -> tuple[Path, Path]:
    if not _FORM.is_dir() or not _CAPTURE.is_dir():
        pytest.skip("private authorized form-capture archive is unavailable")
    return _FORM, _CAPTURE


def test_click_requires_capture_before_remote_execution() -> None:
    with pytest.raises(ValueError, match="requires capture_screen"):
        run_virtuoso_form_focus_probe(
            Path("config/remote_cadence.local.yaml"),
            Path("results/runs/invalid_capture_mode"),
            form_run=Path("unused"), click_wfg=True,
        )


def test_real_click_does_not_prove_field_focus() -> None:
    form, capture = _private()
    result = audit_virtuoso_form_capture_probe(form, capture)
    assert result["status"] == "click_emitted_focus_not_proven"
    assert result["source_oa_unchanged"] is True
    assert result["form_field_edited"] is False
    assert result["cdf_callback_validated"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("false_focus", "source_oa", "screen", "click_report"))
def test_capture_audit_rejects_tampered_evidence(mutation: str) -> None:
    form, capture = _private()
    with tempfile.TemporaryDirectory(prefix="test_form_capture_", dir=Path("results/runs").resolve()) as root:
        copied = Path(root) / capture.name
        shutil.copytree(capture, copied)
        if mutation == "false_focus":
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["focus_delayed_wfg"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "source_oa":
            path = copied / "source_after.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "screen":
            path = copied / "screen.xwd"
            path.write_bytes(path.read_bytes() + b"tampered")
        else:
            (copied / "click_report.txt").write_text(
                "click_complete=t target_x=0 target_y=0\n", encoding="utf-8",
            )
        with pytest.raises(ValueError):
            audit_virtuoso_form_capture_probe(form, copied)
