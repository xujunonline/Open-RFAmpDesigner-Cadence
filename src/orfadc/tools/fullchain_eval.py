from __future__ import annotations

from pathlib import Path

from ..schemas import RunConfig


def fullchain_eval(active_dict: dict, passive_dict: dict, run_dir: Path, run_config: RunConfig) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_config.dry_run:
        return {
            "status": "dry_run",
            "backend_status": "unavailable",
            "active_dict": active_dict,
            "passive_dict": passive_dict,
            "not_lna_result": True,
            "spec_pass": None,
            "note": "Cadence was not invoked. This result must not be reported as a simulation pass.",
        }
    return {
        "status": "backend_unavailable",
        "backend_status": "unavailable",
        "pass": False,
        "not_lna_result": True,
        "spec_pass": None,
        "reason": "The fullchain OCEAN script is a template and has no verified metric extraction yet.",
    }
