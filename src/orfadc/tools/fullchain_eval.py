from __future__ import annotations

from pathlib import Path

from ..cadence.run_ocean import run_ocean_script
from ..schemas import RunConfig


def fullchain_eval(active_dict: dict, passive_dict: dict, run_dir: Path, run_config: RunConfig) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_config.dry_run:
        return {
            "status": "dry_run",
            "active_dict": active_dict,
            "passive_dict": passive_dict,
            "note": "Cadence was not invoked. This result must not be reported as a simulation pass.",
        }
    return run_ocean_script(run_config, run_dir / "run_fullchain.ocn", run_dir)

