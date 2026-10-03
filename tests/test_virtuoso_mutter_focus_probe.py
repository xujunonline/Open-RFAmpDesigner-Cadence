from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_capture_probe import audit_virtuoso_form_capture_probe
from orfadc.experiments.audit_virtuoso_form_focus_probe import audit_virtuoso_form_focus_probe
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_virtuoso_form_focus_probe import run_virtuoso_form_focus_probe


_FORM = _PRIVATE_ROOT / "virtuoso_cdf_form_variant" / "20260927T025834Z_c26b554a"
_XFOCUS = _PRIVATE_ROOT / "virtuoso_form_focus_probe" / "20260927T132124Z_317a4d09"
_CLICK = _PRIVATE_ROOT / "virtuoso_form_focus_probe" / "20260927T131307Z_a097cdbe"
_FULL_GUI = _PRIVATE_ROOT / "virtuoso_form_focus_probe" / "20260927T134424Z_5064d4f4"


def _private(path: Path) -> Path:
    if not _FORM.is_dir() or not path.is_dir():
        pytest.skip("private authorized Mutter focus probe is unavailable")
    return path


def test_x11_window_focus_does_not_prove_cadence_field_focus() -> None:
    result = audit_virtuoso_form_focus_probe(_FORM, _private(_XFOCUS))
    assert result["status"] == "focus_not_proven"
    assert result["window_manager_registered"] is True
    assert result["x11_focus_request_sent"] is True
    assert result["focus_delayed_wfg"] is False
    assert result["fatal_x_io"] is True
    assert result["source_oa_unchanged"] is True
    assert result["form_field_edited"] is False


def test_mutter_pointer_click_has_unverified_target_and_no_field_focus() -> None:
    result = audit_virtuoso_form_capture_probe(_FORM, _private(_CLICK))
    assert result["status"] == "click_target_unverified_focus_not_proven"
    assert result["window_manager_registered"] is True
    assert result["click_target_verified"] is False
    assert result["focus_delayed_wfg"] is False
    assert result["source_oa_unchanged"] is True


def test_full_gui_still_does_not_prove_cadence_field_focus() -> None:
    result = audit_virtuoso_form_focus_probe(_FORM, _private(_FULL_GUI))
    assert result["status"] == "focus_not_proven"
    assert result["window_manager_registered"] is True
    assert result["focus_delayed_wfg"] is False
    assert result["fatal_x_io"] is True
    assert result["source_oa_unchanged"] is True


@pytest.mark.parametrize("mutation", ("memory", "false_focus"))
def test_full_gui_archive_rejects_tampering(mutation: str) -> None:
    source = _private(_FULL_GUI)
    with tempfile.TemporaryDirectory(prefix="test_full_gui_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "memory":
            path = copied / "remote_memory_before.txt"
            path.write_text(path.read_text(encoding="utf-8").replace("2615", "1024"), encoding="utf-8")
        else:
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["focus_delayed_wfg"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_form_focus_probe(_FORM, copied)


@pytest.mark.parametrize("mutation", ("false_focus", "x11_report", "source_oa"))
def test_x11_focus_archive_rejects_tampering(mutation: str) -> None:
    source = _private(_XFOCUS)
    with tempfile.TemporaryDirectory(prefix="test_xfocus_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "false_focus":
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["focus_delayed_wfg"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "x11_report":
            (copied / "window_focus_report.txt").write_text(
                "focus_request_sent=t target=0x1 observed=0x1\n", encoding="utf-8",
            )
        else:
            path = copied / "source_after.oa"
            path.write_bytes(path.read_bytes() + b"changed")
        with pytest.raises(ValueError):
            audit_virtuoso_form_focus_probe(_FORM, copied)


def test_window_focus_mode_rejects_invalid_combinations() -> None:
    for kwargs in ({"focus_window": True},
                   {"focus_window": True, "window_manager": True, "capture_screen": True}):
        with pytest.raises(ValueError, match="X11 window focus"):
            run_virtuoso_form_focus_probe(Path("unused"), _PRIVATE_ROOT / "unused",
                                          form_run=Path("unused"), **kwargs)


def test_full_gui_mode_requires_isolated_window_manager() -> None:
    for kwargs in ({"full_gui": True},
                   {"full_gui": True, "window_manager": True, "click_wfg": True,
                    "capture_screen": True}):
        with pytest.raises(ValueError, match="full GUI"):
            run_virtuoso_form_focus_probe(Path("unused"), _PRIVATE_ROOT / "unused",
                                          form_run=Path("unused"), **kwargs)
