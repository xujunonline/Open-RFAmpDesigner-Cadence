from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_virtuoso_cdf_readonly import _LOGS
from orfadc.experiments.run_virtuoso_form_readback import _context


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "circuit/skill/virtuoso_form_focus_probe.il"
_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_hold.sh"
_CAPTURE_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_capture.sh"
_WM_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_mutter_focus.sh"
_WM_CAPTURE_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_mutter_capture.sh"
_WM_XFOCUS_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_mutter_xfocus.sh"
_WM_FULL_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_mutter_full.sh"
_WM_FULL_CAPTURE_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_mutter_full_capture.sh"
_CLICK_HELPER = _ROOT / "circuit/skill/x11_click_form_field.py"
_ABS_CLICK_HELPER = _ROOT / "circuit/skill/x11_click_form_field_absolute.py"
_XFOCUS_HELPER = _ROOT / "circuit/skill/x11_focus_form_window.py"


def run_virtuoso_form_focus_probe(
    config_path: Path, output_dir: Path, *, form_run: Path,
    runner: RemoteRunner | None = None, capture_screen: bool = False,
    click_wfg: bool = False, window_manager: bool = False,
    focus_window: bool = False, full_gui: bool = False,
    absolute_click: bool = False,
) -> dict:
    _require_private_path(output_dir)
    if click_wfg and not capture_screen:
        raise ValueError("click_wfg requires capture_screen")
    if absolute_click and not (click_wfg and capture_screen and window_manager):
        raise ValueError("absolute_click requires window-manager capture and click mode")
    if focus_window and (not window_manager or capture_screen or click_wfg):
        raise ValueError("X11 window focus requires window-manager mode without screen/click")
    if full_gui and (
        not window_manager or focus_window
        or (capture_screen or click_wfg) and not (capture_screen and click_wfg and absolute_click)
    ):
        raise ValueError("full GUI requires window-manager mode or an absolute read-only click")
    if window_manager and capture_screen != click_wfg:
        raise ValueError("window-manager capture requires one bounded pointer click")
    lib_name, lib_path, cell, mos = _context(form_run)
    launcher = (
        _WM_FULL_CAPTURE_LAUNCHER if full_gui and capture_screen else
        _WM_CAPTURE_LAUNCHER if window_manager and capture_screen else
        _WM_XFOCUS_LAUNCHER if focus_window else
        _WM_FULL_LAUNCHER if full_gui else
        _WM_LAUNCHER if window_manager else
        _CAPTURE_LAUNCHER if capture_screen else _LAUNCHER
    )
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink() or not launcher.is_file():
        raise ValueError("checked-in focus probe source or launcher is missing")
    click_helper = _ABS_CLICK_HELPER if absolute_click else _CLICK_HELPER
    if click_wfg and not click_helper.is_file():
        raise ValueError("checked-in X11 click helper is missing")
    if focus_window and not _XFOCUS_HELPER.is_file():
        raise ValueError("checked-in X11 focus helper is missing")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before form focus probe")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("configured Xvfb is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-f", xvfb]).ok or not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    remote_available_mib = None
    remote_memory_stdout = None
    if full_gui:
        memory = runner.run_remote(["free", "-m"], timeout_seconds=20)
        rows = [row.split() for row in memory.stdout.splitlines() if row.startswith("Mem:")]
        if not memory.ok or len(rows) != 1 or len(rows[0]) < 7:
            raise RuntimeError("remote physical memory could not be checked")
        remote_available_mib = int(rows[0][6])
        remote_memory_stdout = memory.stdout
        if remote_available_mib < 2048:
            raise RuntimeError("remote physical-memory gate failed before full GUI")
    owned = runner.run_shell(
        f"test -d {shlex.quote(lib_path)} && test -w {shlex.quote(lib_path)} "
        f"&& test ! -L {shlex.quote(lib_path)} "
        f"&& test \"$(stat -c %U {shlex.quote(lib_path)})\" = \"$(id -un)\"",
        timeout_seconds=30,
    )
    if not owned.ok:
        raise ValueError("focus probe library is not an owned user library")
    output_dir.mkdir(parents=True, exist_ok=False)
    if full_gui:
        (output_dir / "remote_memory_before.txt").write_text(remote_memory_stdout, encoding="utf-8")
    shutil.copy2(_SCRIPT, output_dir / "virtuoso_gui_smoke.il")
    shutil.copy2(launcher, output_dir / launcher.name)
    if click_wfg:
        shutil.copy2(click_helper, output_dir / _CLICK_HELPER.name)
    if focus_window:
        shutil.copy2(_XFOCUS_HELPER, output_dir / _XFOCUS_HELPER.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"form_focus_{uuid4().hex[:12]}")
    source_sha = hashlib.sha256((form_run / "sch.oa").read_bytes()).hexdigest()
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "source_form_run": form_run.name, "source_cell": cell,
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
        "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "capture_screen": capture_screen,
        "pointer_click_only": click_wfg,
        "absolute_click": absolute_click,
        "window_manager": window_manager,
        "full_gui": full_gui,
        "remote_available_mib_before": remote_available_mib,
        "focus_window": focus_window,
        "focus_helper_sha256": hashlib.sha256(_XFOCUS_HELPER.read_bytes()).hexdigest() if focus_window else None,
        "click_helper_sha256": hashlib.sha256(click_helper.read_bytes()).hexdigest() if click_wfg else None,
        "source_oa_sha256": source_sha,
        "pdk_write": False, "user_oa_write": False,
        "form_field_edited": False, "cdf_callback_invoked": False,
        "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    oa_remote = f"{lib_path}/{cell}/schematic/sch.oa"
    if not runner.download(oa_remote, output_dir / "source_before.oa").ok:
        return finish("source_oa_missing")
    if hashlib.sha256((output_dir / "source_before.oa").read_bytes()).hexdigest() != source_sha:
        return finish("source_oa_changed")
    uploads = ["virtuoso_gui_smoke.il", launcher.name]
    if click_wfg:
        uploads.append(_CLICK_HELPER.name)
    if focus_window:
        uploads.append(_XFOCUS_HELPER.name)
    for name in uploads:
        if not runner.upload(output_dir / name, f"{remote_dir}/{name}").ok:
            return finish("upload_failed")
    display_number = 1000 + int(uuid4().hex[:4], 16) % 50000
    env = [
        "env", f"ORFADC_XVFB={xvfb}", f"ORFADC_DISPLAY_NUMBER={display_number}",
        f"ORFADC_REPORT={remote_dir}/focus_report.txt", f"ORFADC_USER_LIB={lib_name}",
        f"ORFADC_USER_LIB_PATH={lib_path}", f"ORFADC_USER_CELL={cell}",
        f"ORFADC_USER_MOS={mos}",
    ]
    if click_wfg:
        env.append("ORFADC_CLICK_FIELD=1")
    result = runner.run_remote(
        [*env, "bash", launcher.name], cwd=remote_dir, timeout_seconds=150,
    )
    (output_dir / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    paths = {
        **{name: f"{remote_dir}/{name}" for name in (*_LOGS, "focus_report.txt")},
        "source_after.oa": oa_remote,
    }
    if capture_screen:
        paths.update({name: f"{remote_dir}/{name}" for name in (
            "screen.xwd", "window_tree.txt", "capture_report.txt",
        )})
    if click_wfg:
        paths.update({name: f"{remote_dir}/{name}" for name in (
            "click_report.txt", "click.stderr", "screen_after.xwd",
        )})
        if absolute_click:
            paths["window_details_at_click.txt"] = f"{remote_dir}/window_details_at_click.txt"
    if window_manager:
        paths.update({name: f"{remote_dir}/{name}" for name in (
            "wm_property.txt", "wm_property.stderr", "mutter.stdout", "mutter.stderr",
        )})
    if focus_window:
        paths.update({name: f"{remote_dir}/{name}" for name in (
            "window_tree_at_focus.txt", "window_focus_report.txt", "window_focus.stderr",
        )})
    downloads = {name: runner.download(remote, output_dir / name).ok for name, remote in paths.items()}
    status["downloads"] = downloads
    if downloads.get("screen.xwd"):
        screen = output_dir / "screen.xwd"
        status["screen_sha256"] = hashlib.sha256(screen.read_bytes()).hexdigest()
        status["screen_bytes"] = screen.stat().st_size
    if absolute_click and downloads.get("screen_after.xwd"):
        status["screen_after_sha256"] = hashlib.sha256(
            (output_dir / "screen_after.xwd").read_bytes()
        ).hexdigest()
    if downloads.get("click_report.txt"):
        status["pointer_click_emitted"] = "click_complete=t" in (
            output_dir / "click_report.txt"
        ).read_text(encoding="utf-8", errors="replace")
    if downloads["source_after.oa"]:
        status["source_oa_unchanged"] = (
            (output_dir / "source_before.oa").read_bytes()
            == (output_dir / "source_after.oa").read_bytes()
        )
    if downloads["focus_report.txt"]:
        report = (output_dir / "focus_report.txt").read_text(encoding="utf-8", errors="replace")
        status["report_complete"] = "form_focus_probe_end=t" in report
        status["focus_after_wfg"] = bool(re.search(r"(?m)^focus_after=('?Wfg|\"Wfg\")$", report))
        status["focus_delayed_wfg"] = bool(re.search(r"(?m)^focus_later_after=('?Wfg|\"Wfg\")$", report))
    if downloads["virtuoso.stderr"]:
        status["fatal_x_io"] = bool(re.search(
            r"fatal X IO error|IO Error 0 \(Success\) on Display",
            (output_dir / "virtuoso.stderr").read_text(encoding="utf-8", errors="replace"),
        ))
    if window_manager and downloads.get("wm_property.txt"):
        status["wm_registered"] = bool(re.fullmatch(
            r"_NET_SUPPORTING_WM_CHECK\(WINDOW\): window id # 0x[0-9a-fA-F]+\n",
            (output_dir / "wm_property.txt").read_text(encoding="utf-8"),
        ))
    if focus_window and downloads.get("window_focus_report.txt"):
        status["x11_focus_request_sent"] = "focus_request_sent=t" in (
            output_dir / "window_focus_report.txt"
        ).read_text(encoding="utf-8", errors="replace")
    if status.get("source_oa_unchanged") is False:
        return finish("source_oa_changed", result.returncode)
    if result.returncode == 124:
        return finish("timeout", result.returncode)
    if status.get("fatal_x_io"):
        return finish("gui_x_io_failure", result.returncode)
    if window_manager and status.get("wm_registered") is not True:
        return finish("window_manager_unavailable", result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("focus_archive_incomplete", result.returncode)
    log = (output_dir / "virtuoso.log").read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or not status.get("report_complete"):
        return finish("focus_probe_error", result.returncode)
    if "set_focus_available=t" not in report or "get_focus_available=t" not in report:
        return finish("focus_api_unavailable", result.returncode)
    return finish("focus_probe_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GUI property-form Wfg focus probe")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_form_focus_probe")
    parser.add_argument("--form-run", type=Path, required=True)
    parser.add_argument("--capture-screen", action="store_true")
    parser.add_argument("--click-wfg", action="store_true")
    parser.add_argument("--absolute-click", action="store_true")
    parser.add_argument("--window-manager", action="store_true")
    parser.add_argument("--focus-window", action="store_true")
    parser.add_argument("--full-gui", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_form_focus_probe(
        args.config, output_dir, form_run=args.form_run,
        capture_screen=args.capture_screen, click_wfg=args.click_wfg,
        window_manager=args.window_manager, focus_window=args.focus_window,
        full_gui=args.full_gui, absolute_click=args.absolute_click,
    )
    print(f"run_id={result['run_id']} status={result['status']} focus_after_wfg={result.get('focus_after_wfg')}")
    return 0 if result["status"] == "focus_probe_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
