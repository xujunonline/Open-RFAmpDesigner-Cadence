from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_focus_probe import audit_virtuoso_form_focus_probe


_FORM = Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a")
_FOCUS = Path("results/runs/virtuoso_form_focus_probe/20260927T042345Z_1d332734")


def _private() -> tuple[Path, Path]:
    if not _FORM.is_dir() or not _FOCUS.is_dir():
        pytest.skip("private authorized form-focus archives are unavailable")
    return _FORM, _FOCUS


def test_real_focus_failure_remains_unverified() -> None:
    form, focus = _private()
    result = audit_virtuoso_form_focus_probe(form, focus)
    assert result["status"] == "focus_not_proven"
    assert result["report_complete"] is True
    assert result["fatal_x_io"] is True
    assert result["focus_after_wfg"] is False
    assert result["focus_delayed_wfg"] is False
    assert result["source_oa_unchanged"] is True
    assert result["form_field_edited"] is False
    assert result["cdf_callback_validated"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("false_success", "source_oa", "report", "script", "false_focus"))
def test_focus_audit_rejects_tampered_evidence(mutation: str) -> None:
    form, focus = _private()
    with tempfile.TemporaryDirectory(prefix="test_form_focus_", dir=Path("results/runs").resolve()) as root:
        copied = Path(root) / focus.name
        shutil.copytree(focus, copied)
        if mutation in {"false_success", "false_focus"}:
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "false_success":
                payload["status"] = "focus_probe_recorded"
                payload["returncode"] = 0
            else:
                payload["focus_delayed_wfg"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "source_oa":
            path = copied / "source_after.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "report":
            path = copied / "focus_report.txt"
            path.write_bytes(path.read_bytes().replace(b"focus_after=InfoAll", b"focus_after=Wfg"))
            status_path = copied / "run_status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            payload["focus_after_wfg"] = False
            status_path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = copied / "virtuoso_gui_smoke.il"
            path.write_bytes(path.read_bytes() + b"\n; tampered\n")
        with pytest.raises(ValueError):
            audit_virtuoso_form_focus_probe(form, copied)
