from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_form_focus_probe import (
    _LAUNCHER, _SCRIPT, _WM_CAPTURE_LAUNCHER, _WM_LAUNCHER,
    _WM_XFOCUS_LAUNCHER, _WM_FULL_LAUNCHER, _XFOCUS_HELPER,
)
from orfadc.experiments.run_virtuoso_form_readback import _context


_ARTIFACTS = (
    "virtuoso_gui_smoke.il", "run_virtuoso_gui_hold.sh", "source_before.oa",
    "source_after.oa", "focus_report.txt", "virtuoso.log", "virtuoso.stderr",
)


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("focus-probe artifact is missing or unsafe")
    return path.read_bytes()


def audit_virtuoso_form_focus_probe(form_run: Path, focus_run: Path) -> dict:
    _, _, cell, _ = _context(form_run)
    _require_private_path(focus_run)
    if not focus_run.is_dir() or focus_run.is_symlink():
        raise ValueError("focus-probe archive is missing or unsafe")
    status = json.loads(_read(focus_run / "run_status.json"))
    if (
        status.get("run_id") != focus_run.name
        or status.get("source_form_run") != form_run.name
        or status.get("source_cell") != cell
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("pdk_write") is not False
        or status.get("user_oa_write") is not False
        or status.get("form_field_edited") is not False
        or status.get("cdf_callback_invoked") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
    ):
        raise ValueError("focus-probe status exceeds its read-only boundary")
    window_manager = status.get("window_manager", False)
    focus_window = status.get("focus_window", False)
    full_gui = status.get("full_gui", False)
    if (type(window_manager) is not bool or type(focus_window) is not bool
            or type(full_gui) is not bool or ((focus_window or full_gui) and not window_manager)):
        raise ValueError("focus-probe window-manager mode is invalid")
    if full_gui and (type(status.get("remote_available_mib_before")) is not int
                     or status["remote_available_mib_before"] < 2048):
        raise ValueError("full GUI lacks remote physical-memory evidence")
    if full_gui:
        rows = [row.split() for row in _read(focus_run / "remote_memory_before.txt").decode("utf-8").splitlines()
                if row.startswith("Mem:")]
        if len(rows) != 1 or len(rows[0]) < 7 or int(rows[0][6]) != status["remote_available_mib_before"]:
            raise ValueError("full GUI remote physical-memory record differs")
    launcher = (
        _WM_CAPTURE_LAUNCHER if window_manager and status.get("capture_screen") else
        _WM_XFOCUS_LAUNCHER if focus_window else
        _WM_FULL_LAUNCHER if full_gui else
        _WM_LAUNCHER if window_manager else _LAUNCHER
    )
    artifact_names = tuple(name for name in _ARTIFACTS if name != _LAUNCHER.name) + (launcher.name,)
    artifacts = {name: _read(focus_run / name) for name in artifact_names}
    if (
        artifacts["virtuoso_gui_smoke.il"] != _read(_SCRIPT)
        or artifacts[launcher.name] != _read(launcher)
        or hashlib.sha256(artifacts["virtuoso_gui_smoke.il"]).hexdigest() != status.get("script_sha256")
        or hashlib.sha256(artifacts[launcher.name]).hexdigest() != status.get("launcher_sha256")
        or artifacts["source_before.oa"] != _read(form_run / "sch.oa")
        or artifacts["source_after.oa"] != artifacts["source_before.oa"]
        or hashlib.sha256(artifacts["source_before.oa"]).hexdigest() != status.get("source_oa_sha256")
    ):
        raise ValueError("focus-probe source, launcher, or OA evidence differs")
    if status.get("source_oa_unchanged") not in (None, True):
        raise ValueError("focus-probe status contradicts the unchanged source OA")
    report = artifacts["focus_report.txt"].decode("utf-8", errors="replace")
    if window_manager:
        property_text = _read(focus_run / "wm_property.txt").decode("utf-8", errors="replace")
        registered = bool(re.fullmatch(
            r"_NET_SUPPORTING_WM_CHECK\(WINDOW\): window id # 0x[0-9a-fA-F]+\n",
            property_text,
        ))
        if status.get("wm_registered") is not registered:
            raise ValueError("focus-probe window-manager report differs")
        for name in ("wm_property.stderr", "mutter.stdout", "mutter.stderr"):
            _read(focus_run / name)
    if focus_window:
        helper = _read(focus_run / _XFOCUS_HELPER.name)
        if (helper != _read(_XFOCUS_HELPER)
                or hashlib.sha256(helper).hexdigest() != status.get("focus_helper_sha256")):
            raise ValueError("X11 focus helper provenance differs")
        tree = _read(focus_run / "window_tree_at_focus.txt").decode("utf-8", errors="replace")
        focus_report = _read(focus_run / "window_focus_report.txt").decode("utf-8", errors="replace")
        _read(focus_run / "window_focus.stderr")
        request = re.fullmatch(r"focus_request_sent=t target=(0x[0-9a-f]+) observed=(0x[0-9a-f]+)\n", focus_report)
        if (status.get("x11_focus_request_sent") is not bool(request)
                or (request is not None and request.group(1) not in tree)):
            raise ValueError("X11 focus request differs from archived window tree")
    stderr = artifacts["virtuoso.stderr"].decode("utf-8", errors="replace")
    log = artifacts["virtuoso.log"].decode("utf-8", errors="replace")
    complete = "form_focus_probe_end=t" in report
    immediate = bool(re.search(r"(?m)^focus_after=('?Wfg|\"Wfg\")$", report))
    delayed = bool(re.search(r"(?m)^focus_later_after=('?Wfg|\"Wfg\")$", report))
    fatal_x_io = bool(re.search(r"fatal X IO error|IO Error 0 \(Success\) on Display", stderr))
    legacy_io_classification = (
        window_manager and status.get("status") == "focus_archive_incomplete"
        and status.get("fatal_x_io") is False
        and "IO Error 0 (Success) on Display" in stderr
    )
    for field, observed in (
        ("report_complete", complete), ("focus_after_wfg", immediate),
        ("focus_delayed_wfg", delayed), ("fatal_x_io", fatal_x_io),
    ):
        if field in status and status[field] is not observed and not (
            field == "fatal_x_io" and legacy_io_classification
        ):
            raise ValueError("focus-probe status contradicts archived GUI evidence")
    if re.search(r"(?m)^\\e \*Error\*", log):
        raise ValueError("focus-probe SKILL log contains an error")
    if status.get("status") == "focus_probe_recorded":
        if status.get("returncode") != 0 or not complete or fatal_x_io:
            raise ValueError("focus probe claims a clean run without clean evidence")
    elif status.get("status") not in {"timeout", "gui_x_io_failure", "focus_archive_incomplete", "window_manager_unavailable"}:
        raise ValueError("focus-probe failure status is unsupported")
    verified = status.get("status") == "focus_probe_recorded" and immediate and delayed
    return {
        "status": "focus_field_verified" if verified else "focus_not_proven",
        "report_complete": complete,
        "focus_after_wfg": immediate,
        "focus_delayed_wfg": delayed,
        "fatal_x_io": fatal_x_io,
        "legacy_io_classification": legacy_io_classification,
        "source_oa_unchanged": True,
        "window_manager_registered": registered if window_manager else False,
        "x11_focus_request_sent": status.get("x11_focus_request_sent", False) if focus_window else False,
        "form_field_edited": False,
        "cdf_callback_validated": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a private read-only Virtuoso form-focus probe")
    parser.add_argument("form_run", type=Path)
    parser.add_argument("focus_run", type=Path)
    args = parser.parse_args()
    result = audit_virtuoso_form_focus_probe(args.form_run, args.focus_run)
    print(f"status={result['status']} report_complete={result['report_complete']} "
          f"fatal_x_io={result['fatal_x_io']}")
    return 0 if result["status"] == "focus_field_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
