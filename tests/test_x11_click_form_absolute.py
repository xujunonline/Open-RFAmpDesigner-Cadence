from __future__ import annotations

import runpy
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.run_virtuoso_form_focus_probe import run_virtuoso_form_focus_probe
from orfadc.experiments.run_virtuoso_form_focus_probe import _WM_FULL_CAPTURE_LAUNCHER
from orfadc.experiments.audit_virtuoso_form_capture_probe import audit_virtuoso_form_capture_probe
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_HELPER = Path("circuit/skill/x11_click_form_field_absolute.py")
_TREE = (
    '  0x40003c (has no name): ()  1169x1080+700+88  +700+88\n'
    '    0x8004a7 "Edit Object Properties": ("virtuoso" "virtuoso") '
    '1169x1080+10+29  +700+88\n'
)
_DETAILS = (
    'xwininfo: Window id: 0x8004a7 "Edit Object Properties"\n'
    '  Absolute upper-left X:  700\n'
    '  Absolute upper-left Y:  88\n'
    '  Relative upper-left X:  10\n'
    '  Relative upper-left Y:  29\n'
    '  Width: 1169\n'
    '  Height: 1080\n'
)
_FORM = _PRIVATE_ROOT / "virtuoso_cdf_form_variant" / "20260927T025834Z_c26b554a"
_REAL = _PRIVATE_ROOT / "virtuoso_form_focus_probe" / "20260927T150359Z_7987493d"
_FULL_REAL = _PRIVATE_ROOT / "virtuoso_form_focus_probe" / "20260927T151028Z_26cc4b54"


def test_absolute_helper_uses_screen_coordinates_not_reparent_offsets() -> None:
    module = runpy.run_path(str(_HELPER))
    window_id = module["property_window_id"](_TREE)
    assert window_id == "0x8004a7"
    left, top, width, height = module["absolute_geometry"](_DETAILS, window_id)
    assert (left, top, width, height) == (700, 88, 1169, 1080)
    assert (left + 700, top + 497) == (1400, 585)


@pytest.mark.parametrize("tree", ["", _TREE + _TREE])
def test_absolute_helper_requires_unique_property_window(tree: str) -> None:
    module = runpy.run_path(str(_HELPER))
    with pytest.raises(ValueError, match="exactly one"):
        module["property_window_id"](tree)


@pytest.mark.parametrize("details", [
    _DETAILS.replace("0x8004a7", "0x8004a8"),
    _DETAILS.replace("Absolute upper-left X:  700", "Relative upper-left X:  700"),
    _DETAILS.replace("Width: 1169", "Width: 400"),
])
def test_absolute_helper_rejects_wrong_or_unusable_geometry(details: str) -> None:
    module = runpy.run_path(str(_HELPER))
    with pytest.raises(ValueError):
        module["absolute_geometry"](details, "0x8004a7")


def test_absolute_click_requires_read_only_window_manager_capture() -> None:
    with pytest.raises(ValueError, match="absolute_click requires"):
        run_virtuoso_form_focus_probe(
            Path("unused"), Path("results/runs/unused"),
            form_run=Path("unused"), absolute_click=True,
        )


def test_full_gui_capture_launcher_uses_graphical_virtuoso_without_typing() -> None:
    source = _WM_FULL_CAPTURE_LAUNCHER.read_text(encoding="utf-8")
    assert "virtuoso -nocdsinit -restore" in source
    assert "-nographE" not in source
    assert "python3 x11_click_form_field.py" in source
    assert "Xvfb_screen0 screen_after.xwd" in source
    assert "xdotool type" not in source


def test_real_absolute_click_hits_field_but_does_not_prove_cadence_focus() -> None:
    if not _FORM.is_dir() or not _REAL.is_dir():
        pytest.skip("private absolute click probe is unavailable")
    report = audit_virtuoso_form_capture_probe(_FORM, _REAL)
    assert report["status"] == "click_emitted_focus_not_proven"
    assert report["click_target_verified"] is True
    assert report["focus_delayed_wfg"] is False
    assert report["screen_after_hash_verified"] is False  # First run predates this optional field.
    assert report["source_oa_unchanged"] is True
    assert report["form_field_edited"] is False
    assert report["spec_pass"] is None


@pytest.mark.parametrize("mutation", ["details", "click", "helper", "oa", "false_focus"])
def test_absolute_click_audit_rejects_tampered_source(
    mutation: str,
) -> None:
    if not _FORM.is_dir() or not _REAL.is_dir():
        pytest.skip("private absolute click probe is unavailable")
    with tempfile.TemporaryDirectory(prefix="absolute_click_audit_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / _REAL.name
        shutil.copytree(_REAL, copied, ignore=shutil.ignore_patterns("*.png"))
        if mutation == "details":
            path = copied / "window_details_at_click.txt"
            path.write_text(path.read_text(encoding="utf-8").replace(
                "Absolute upper-left X:  700", "Absolute upper-left X:  701",
            ), encoding="utf-8")
        elif mutation == "click":
            path = copied / "click_report.txt"
            path.write_text(path.read_text(encoding="utf-8").replace(
                "target_x=1400", "target_x=1401",
            ), encoding="utf-8")
        elif mutation == "helper":
            path = copied / "x11_click_form_field.py"
            path.write_bytes(path.read_bytes() + b"changed")
        elif mutation == "oa":
            path = copied / "source_after.oa"
            path.write_bytes(path.read_bytes() + b"changed")
        else:
            path = copied / "run_status.json"
            status = json.loads(path.read_text(encoding="utf-8"))
            status["focus_delayed_wfg"] = True
            path.write_text(json.dumps(status), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_form_capture_probe(_FORM, copied)


def test_full_gui_absolute_click_still_has_no_cadence_field_focus() -> None:
    if not _FORM.is_dir() or not _FULL_REAL.is_dir():
        pytest.skip("private full GUI absolute click probe is unavailable")
    report = audit_virtuoso_form_capture_probe(_FORM, _FULL_REAL)
    assert report["status"] == "click_emitted_focus_not_proven"
    assert report["click_target_verified"] is True
    assert report["focus_delayed_wfg"] is False
    assert report["screen_after_hash_verified"] is True
    assert report["source_oa_unchanged"] is True
    assert report["spec_pass"] is None


@pytest.mark.parametrize("mutation", ["memory", "screen_after", "details"])
def test_full_gui_absolute_click_rejects_tampered_evidence(mutation: str) -> None:
    if not _FORM.is_dir() or not _FULL_REAL.is_dir():
        pytest.skip("private full GUI absolute click probe is unavailable")
    with tempfile.TemporaryDirectory(prefix="full_absolute_click_audit_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / _FULL_REAL.name
        shutil.copytree(_FULL_REAL, copied, ignore=shutil.ignore_patterns("*.png"))
        if mutation == "memory":
            path = copied / "remote_memory_before.txt"
            rows = path.read_text(encoding="utf-8").splitlines()
            changed = []
            for row in rows:
                if row.startswith("Mem:"):
                    parts = row.split()
                    parts[6] = "1024"
                    row = " ".join(parts)
                changed.append(row)
            path.write_text("\n".join(changed) + "\n", encoding="utf-8")
        elif mutation == "screen_after":
            path = copied / "screen_after.xwd"
            content = bytearray(path.read_bytes())
            content[-1] ^= 1
            path.write_bytes(content)
        else:
            path = copied / "window_details_at_click.txt"
            path.write_text(path.read_text(encoding="utf-8").replace(
                "Absolute upper-left Y:  23", "Absolute upper-left Y:  24",
            ), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_form_capture_probe(_FORM, copied)
