from __future__ import annotations

import subprocess
from pathlib import Path

from ..schemas import RunConfig


def run_ocean_script(config: RunConfig, script_path: Path, run_dir: Path) -> dict:
    if config.dry_run:
        return {"status": "dry_run", "script": str(script_path), "run_dir": str(run_dir)}
    if not script_path.exists():
        raise FileNotFoundError(script_path)
    cmd = [config.ocean_bin, "-nograph", "-restore", str(script_path)]
    completed = subprocess.run(
        cmd,
        cwd=run_dir,
        check=False,
        text=True,
        capture_output=True,
        timeout=config.timeout_seconds,
    )
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }

