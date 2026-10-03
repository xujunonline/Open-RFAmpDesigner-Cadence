from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_form_focus_probe import (
    _ABS_CLICK_HELPER, _CAPTURE_LAUNCHER, _CLICK_HELPER, _SCRIPT,
    _WM_CAPTURE_LAUNCHER, _WM_FULL_CAPTURE_LAUNCHER,
)
from orfadc.experiments.run_virtuoso_form_readback import _context


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("capture artifact is missing or unsafe")
    return path.read_bytes()


def _xwd_size(data: bytes) -> tuple[int, int]:
    if len(data) < 100:
        raise ValueError("XWD header is missing")
    header = struct.unpack(">25I", data[:100])
    offset = header[0] + 12 * header[19]
    width, height, stride = header[4], header[5], header[12]
    if (
        header[1] != 7 or header[2] != 2 or header[11] != 32
        or width != 1920 or height != 1080 or stride != width * 4
        or len(data) != offset + height * stride
    ):
        raise ValueError("XWD geometry or byte count is inconsistent")
    return width, height


def audit_virtuoso_form_capture_probe(form_run: Path, capture_run: Path) -> dict:
    _, _, cell, _ = _context(form_run)
    _require_private_path(capture_run)
    if not capture_run.is_dir() or capture_run.is_symlink():
        raise ValueError("capture archive is missing or unsafe")
    status = json.loads(_read(capture_run / "run_status.json"))
    window_manager = status.get("window_manager", False)
    absolute_click = status.get("absolute_click", False)
    full_gui = status.get("full_gui", False)
    if (
        any(type(value) is not bool for value in (window_manager, absolute_click, full_gui))
        or (absolute_click and not window_manager)
        or (full_gui and not (window_manager and absolute_click))
    ):
        raise ValueError("capture window-manager mode is invalid")
    launcher = (
        _WM_FULL_CAPTURE_LAUNCHER if full_gui else
        _WM_CAPTURE_LAUNCHER if window_manager else _CAPTURE_LAUNCHER
    )
    allowed_status = (
        {"gui_x_io_failure", "focus_probe_recorded", "focus_archive_incomplete"}
        if window_manager else {"gui_x_io_failure"}
    )
    if (
        status.get("run_id") != capture_run.name
        or status.get("source_form_run") != form_run.name
        or status.get("source_cell") != cell
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("capture_screen") is not True
        or status.get("pointer_click_only") is not True
        or status.get("pointer_click_emitted") is not True
        or status.get("pdk_write") is not False
        or status.get("user_oa_write") is not False
        or status.get("form_field_edited") is not False
        or status.get("cdf_callback_invoked") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or status.get("status") not in allowed_status
    ):
        raise ValueError("capture status exceeds the read-only diagnostic boundary")
    for name, source, digest_key in (
        ("virtuoso_gui_smoke.il", _SCRIPT, "script_sha256"),
        (launcher.name, launcher, "launcher_sha256"),
        (_CLICK_HELPER.name, _ABS_CLICK_HELPER if absolute_click else _CLICK_HELPER, "click_helper_sha256"),
    ):
        data = _read(capture_run / name)
        if data != _read(source) or hashlib.sha256(data).hexdigest() != status.get(digest_key):
            raise ValueError("capture script provenance differs")
    if full_gui:
        memory = _read(capture_run / "remote_memory_before.txt").decode("utf-8", errors="replace")
        rows = [row.split() for row in memory.splitlines() if row.startswith("Mem:")]
        if (
            len(rows) != 1 or len(rows[0]) < 7
            or type(status.get("remote_available_mib_before")) is not int
            or int(rows[0][6]) != status["remote_available_mib_before"]
            or status["remote_available_mib_before"] < 2048
        ):
            raise ValueError("full GUI capture lacks a valid remote memory gate")
    before = _read(capture_run / "source_before.oa")
    if (
        before != _read(form_run / "sch.oa")
        or _read(capture_run / "source_after.oa") != before
        or hashlib.sha256(before).hexdigest() != status.get("source_oa_sha256")
        or status.get("source_oa_unchanged") is not True
    ):
        raise ValueError("capture source OA changed")
    downloads = status.get("downloads")
    required = (
        "screen.xwd", "screen_after.xwd", "window_tree.txt", "click_report.txt",
        "click.stderr", "capture_report.txt", "focus_report.txt", "virtuoso.stderr",
    )
    if absolute_click:
        required += ("window_details_at_click.txt",)
    if not isinstance(downloads, dict) or any(downloads.get(name) is not True for name in required):
        raise ValueError("capture archive has missing downloads")
    screen = _read(capture_run / "screen.xwd")
    screen_after = _read(capture_run / "screen_after.xwd")
    _xwd_size(screen)
    _xwd_size(screen_after)
    if (
        len(screen) != status.get("screen_bytes")
        or hashlib.sha256(screen).hexdigest() != status.get("screen_sha256")
        or (absolute_click and "screen_after_sha256" in status
            and hashlib.sha256(screen_after).hexdigest() != status["screen_after_sha256"])
    ):
        raise ValueError("capture screen hash differs")
    tree = _read(capture_run / "window_tree.txt").decode("utf-8", errors="replace")
    window = re.search(
        r'0x[0-9a-f]+ "Edit Object Properties":.*?\s+(\d+)x(\d+)\+(\d+)\+(\d+)\s',
        tree,
    )
    click = _read(capture_run / "click_report.txt").decode("utf-8", errors="replace")
    target = re.fullmatch(r"click_complete=t target_x=(\d+) target_y=(\d+)\s*", click) if not absolute_click else None
    if not window or _read(capture_run / "click.stderr"):
        raise ValueError("capture click has no reproducible window target")
    if absolute_click:
        report_match = re.fullmatch(
            r"click_complete=t window_id=(0x[0-9a-fA-F]+) window_left=(-?\d+) "
            r"window_top=(-?\d+) window_width=(\d+) window_height=(\d+) "
            r"target_x=(\d+) target_y=(\d+) geometry_stable=t\s*", click,
        )
        tree_id = re.findall(r'^\s*(0x[0-9a-fA-F]+) "Edit Object Properties":', tree, re.MULTILINE)
        details = _read(capture_run / "window_details_at_click.txt").decode("utf-8", errors="replace")
        heading = re.search(r"xwininfo: Window id: (0x[0-9a-fA-F]+)\b", details)
        geometry = [re.search(rf"(?m)^\s*{label}:\s*(-?\d+)\s*$", details) for label in (
            "Absolute upper-left X", "Absolute upper-left Y", "Width", "Height",
        )]
        if not report_match or len(tree_id) != 1 or not heading or any(match is None for match in geometry):
            raise ValueError("absolute click source geometry is incomplete")
        window_id, *recorded = report_match.groups()
        left, top, width, height, x, y = map(int, recorded)
        if (
            int(window_id, 16) != int(tree_id[0], 16)
            or int(window_id, 16) != int(heading[1], 16)
            or (left, top, width, height) != tuple(int(match[1]) for match in geometry)
        ):
            raise ValueError("absolute click does not match its X11 window evidence")
        target_verified = (x, y) == (left + 700, top + 497)
        if not target_verified:
            raise ValueError("absolute click did not target the observed Wfg field coordinate")
    else:
        if not target:
            raise ValueError("capture click report is malformed")
        width, height, left, top = map(int, window.groups())
        x, y = map(int, target.groups())
        target_verified = (x, y) == (left + 700, top + 497)
    if width < 1100 or height < 650 or not (0 <= x < 1920 and 0 <= y < 1080):
        raise ValueError("capture click target is outside the observed screen/form bounds")
    if not window_manager and not target_verified:
        raise ValueError("capture click target does not match the observed form geometry")
    report = _read(capture_run / "focus_report.txt").decode("utf-8", errors="replace")
    stderr = _read(capture_run / "virtuoso.stderr").decode("utf-8", errors="replace")
    capture = _read(capture_run / "capture_report.txt").decode("utf-8", errors="replace")
    focus_delayed = bool(re.search(r"(?m)^focus_later_after=('?Wfg|\"Wfg\")$", report))
    fatal_x_io = bool(re.search(r"fatal X IO error|IO Error 0 \(Success\) on Display", stderr))
    if window_manager:
        property_text = _read(capture_run / "wm_property.txt").decode("utf-8", errors="replace")
        if not re.fullmatch(
            r"_NET_SUPPORTING_WM_CHECK\(WINDOW\): window id # 0x[0-9a-fA-F]+\n",
            property_text,
        ) or status.get("wm_registered") is not True:
            raise ValueError("capture window manager was not registered")
        for name in ("wm_property.stderr", "mutter.stdout", "mutter.stderr"):
            _read(capture_run / name)
    if (
        "form_present=t" not in report or "form_focus_probe_end=t" not in report
        or not re.search(r"(?m)^focus_later_before=", report)
        or not re.search(r"(?m)^focus_later_after=", report)
        or "capture_complete=t" not in capture
        or status.get("report_complete") is not True
        or status.get("focus_delayed_wfg") is not focus_delayed
        or status.get("fatal_x_io") is not fatal_x_io
        or (not window_manager and (focus_delayed or not fatal_x_io))
        or (status.get("status") == "focus_probe_recorded" and fatal_x_io)
    ):
        raise ValueError("capture focus or failure report differs")
    verified = window_manager and target_verified and status["status"] == "focus_probe_recorded" and focus_delayed
    return {
        "status": (
            "focus_field_verified" if verified else
            "field_focus_observed_with_x_io" if absolute_click and target_verified and focus_delayed and fatal_x_io else
            "click_target_unverified_focus_not_proven" if window_manager and not target_verified
            else "click_emitted_focus_not_proven"
        ),
        "source_oa_unchanged": True,
        "screen_size": [1920, 1080],
        "window_manager_registered": window_manager,
        "focus_delayed_wfg": focus_delayed,
        "click_target_verified": target_verified,
        "screen_after_hash_verified": (
            absolute_click and "screen_after_sha256" in status
            and hashlib.sha256(screen_after).hexdigest() == status["screen_after_sha256"]
        ),
        "form_field_edited": False,
        "cdf_callback_validated": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a private Virtuoso form capture")
    parser.add_argument("form_run", type=Path)
    parser.add_argument("capture_run", type=Path)
    args = parser.parse_args()
    result = audit_virtuoso_form_capture_probe(args.form_run, args.capture_run)
    print(f"status={result['status']} source_oa_unchanged={result['source_oa_unchanged']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
