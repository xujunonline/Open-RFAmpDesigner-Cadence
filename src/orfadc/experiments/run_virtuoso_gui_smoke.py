from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_BY_KIND = {
    "startup": _ROOT / "circuit/skill/virtuoso_gui_smoke.il",
    "form_api": _ROOT / "circuit/skill/virtuoso_form_api_probe.il",
}
_LAUNCHER = _ROOT / "circuit/skill/run_virtuoso_gui_smoke.sh"
_SOURCES = (_SCRIPT_BY_KIND["startup"], _LAUNCHER)
_LOGS = ("virtuoso.log", "virtuoso.stdout", "virtuoso.stderr", "xvfb.stdout", "xvfb.stderr")


def run_virtuoso_gui_smoke(
    config_path: Path, output_dir: Path, *, probe_kind: str = "startup",
    runner: RemoteRunner | None = None,
) -> dict:
    """Probe full Virtuoso/Xvfb initialization without opening or writing a design cell."""
    _require_private_path(output_dir)
    if probe_kind not in _SCRIPT_BY_KIND:
        raise ValueError("unsupported Virtuoso read-only probe")
    script_source = _SCRIPT_BY_KIND[probe_kind]
    for source in (script_source, _LAUNCHER):
        if not source.is_file() or source.is_symlink():
            raise ValueError("GUI smoke source is missing or symlinked")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before GUI smoke")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("a configured Xvfb executable is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-f", xvfb]).ok or not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(script_source, output_dir / "virtuoso_gui_smoke.il")
    shutil.copy2(_LAUNCHER, output_dir / _LAUNCHER.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"gui_smoke_{uuid4().hex[:12]}")
    display_number = 1000 + int(uuid4().hex[:4], 16) % 50000
    status = {
        "schema_version": 1,
        "status": "unknown",
        "host_available_gib_before": available,
        "run_id": output_dir.name,
        "probe_kind": probe_kind,
        "source_sha256": {
            "virtuoso_gui_smoke.il": hashlib.sha256(script_source.read_bytes()).hexdigest(),
            _LAUNCHER.name: hashlib.sha256(_LAUNCHER.read_bytes()).hexdigest(),
        },
        "design_cell_opened": False,
        "pdk_write": False,
        "user_oa_write": False,
        "cdf_callback_invoked": False,
        "not_lna_result": True,
        "spec_pass": None,
    }

    def finish(kind: str, *, returncode: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = returncode
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    for name in ("virtuoso_gui_smoke.il", _LAUNCHER.name):
        if not runner.upload(output_dir / name, f"{remote_dir}/{name}").ok:
            return finish("upload_failed")
    result = runner.run_remote(
        ["env", f"ORFADC_XVFB={xvfb}",
         f"ORFADC_DISPLAY_NUMBER={display_number}", "bash", "run_virtuoso_gui_smoke.sh"],
        cwd=remote_dir, timeout_seconds=150,
    )
    (output_dir / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    downloads = {
        name: runner.download(f"{remote_dir}/{name}", output_dir / name).ok for name in _LOGS
    }
    status["downloads"] = downloads
    if result.returncode == 124:
        return finish("timeout", returncode=result.returncode)
    if not result.ok or not all(downloads.values()):
        return finish("gui_smoke_failed", returncode=result.returncode)
    log = (output_dir / "virtuoso.log").read_text(encoding="utf-8", errors="replace")
    markers = (
        ("ORFADC_GUI_REPLAY_BEGIN", "ORFADC_GUI_REPLAY_END")
        if probe_kind == "startup" else ("ORFADC_FORM_API_BEGIN", "ORFADC_FORM_API_END")
    )
    if any(len(re.findall(rf"(?m)^\\o {marker}\s*$", log)) != 1 for marker in markers):
        return finish("replay_incomplete", returncode=result.returncode)
    if probe_kind == "form_api":
        names = ("schHiObjectProperty", "leHiEditProp", "hiGetCurrentForm",
                 "geiPlSetPropValue", "geiPlInvokePlistAction")
        api = {}
        for name in names:
            matches = re.findall(rf"(?m)^\\o {name}=(t|nil)\s*$", log)
            if len(matches) != 1:
                return finish("form_api_report_incomplete", returncode=result.returncode)
            api[name] = matches[0] == "t"
        status["form_api_available"] = api
    return finish("gui_replay_completed", returncode=result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded Virtuoso graphical-runtime smoke via Xvfb")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "virtuoso_gui_smoke")
    parser.add_argument("--probe-kind", choices=tuple(_SCRIPT_BY_KIND), default="startup")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_virtuoso_gui_smoke(args.config, output_dir, probe_kind=args.probe_kind)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "gui_replay_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
