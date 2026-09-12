from __future__ import annotations

import subprocess
from pathlib import Path

from ..schemas import RunConfig


def run_spectre(config: RunConfig, netlist_path: Path, run_dir: Path) -> dict:
    if config.dry_run:
        return {"status": "dry_run", "netlist": str(netlist_path), "run_dir": str(run_dir)}
    if not netlist_path.exists():
        raise FileNotFoundError(netlist_path)
    completed = subprocess.run(
        [config.spectre_bin, str(netlist_path)],
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

