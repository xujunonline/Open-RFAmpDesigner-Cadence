from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import (
    _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path,
)


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "circuit/skill/run_window_manager_probe.sh"
_FILES = (
    "xvfb.stdout", "xvfb.stderr", "mutter.stdout", "mutter.stderr",
    "wm_property.txt", "wm_property.stderr", "probe_report.txt",
)


def run_window_manager_probe(config_path: Path, output_dir: Path) -> dict:
    _require_private_path(output_dir)
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before window-manager probe")
    if not _SCRIPT.is_file() or _SCRIPT.is_symlink():
        raise ValueError("checked-in window-manager probe script is missing")
    runner = RemoteRunner(load_remote_config(config_path))
    if not runner.config.xvfb_path:
        raise ValueError("configured Xvfb is required")
    xvfb = runner.config.xvfb_path
    if runner.run_remote(["test", "-d", xvfb]).ok:
        xvfb = f"{xvfb.rstrip('/')}/Xvfb"
    if not runner.run_remote(["test", "-x", xvfb]).ok:
        raise ValueError("configured Xvfb executable is unavailable")
    for binary in ("mutter", "xprop"):
        if not runner.run_remote(["which", binary]).ok:
            raise ValueError(f"{binary} is unavailable")
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_SCRIPT, output_dir / _SCRIPT.name)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"wm_probe_{uuid4().hex[:12]}")
    if not runner.ensure_remote_dir(remote_dir).ok:
        raise RuntimeError("remote probe directory could not be created")
    if not runner.upload(output_dir / _SCRIPT.name, f"{remote_dir}/{_SCRIPT.name}").ok:
        raise RuntimeError("window-manager probe upload failed")
    display_number = 1000 + int(uuid4().hex[:4], 16) % 50000
    result = runner.run_remote(
        ["env", f"ORFADC_XVFB={xvfb}", f"ORFADC_DISPLAY_NUMBER={display_number}",
         "bash", _SCRIPT.name],
        cwd=remote_dir, timeout_seconds=45,
    )
    (output_dir / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    downloaded = {name: runner.download(f"{remote_dir}/{name}", output_dir / name).ok
                  for name in _FILES}
    report = (output_dir / "probe_report.txt").read_text(encoding="utf-8") if downloaded["probe_report.txt"] else ""
    registered = bool(re.search(r"(?m)^wm_registered=t$", report))
    payload = {
        "schema_version": 1, "status": "registered" if result.ok and all(downloaded.values()) and registered else "unavailable",
        "simulation_status": "unknown", "circuit_class": "window_manager_probe",
        "run_id": output_dir.name, "returncode": result.returncode,
        "host_available_gib_before": available,
        "script_sha256": hashlib.sha256(_SCRIPT.read_bytes()).hexdigest(),
        "xvfb_alive_at_probe": bool(re.search(r"(?m)^xvfb_alive=t$", report)),
        "mutter_alive_at_probe": bool(re.search(r"(?m)^mutter_alive=t$", report)),
        "wm_registered_at_probe": registered,
        "downloads": downloaded, "pdk_access": False, "cadence_launched": False,
        "not_lna_result": True, "spec_pass": None,
    }
    write_json(output_dir / "metrics.json", payload)
    manifest_files = {"script": _SCRIPT.name, "metrics": "metrics.json",
                      "launcher_stdout": "launcher.stdout", "launcher_stderr": "launcher.stderr"}
    manifest_files.update({name.replace(".", "_"): name
                           for name, ok in downloaded.items() if ok})
    write_evidence_manifest(output_dir, manifest_files)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe isolated Xvfb/Mutter without Cadence")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "window_manager_probe")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_window_manager_probe(args.config, output_dir)
    print(f"status={result['status']} output={output_dir.resolve()}")
    return 0 if result["status"] == "registered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
