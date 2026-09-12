from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config_loader import write_json
from .remote_runner import RemoteRunner, load_remote_config


def verify_environment(
    config_path: Path,
    ocean_script: Path,
    output_dir: Path,
) -> dict[str, Any]:
    config = load_remote_config(config_path)
    runner = RemoteRunner(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    probe = runner.probe()
    payload: dict[str, Any] = {"status": "probe_failed", "probe": probe}
    if probe["status"] != "ok":
        write_json(output_dir / "cadence_environment_report.json", payload)
        return payload

    spectre = runner.run_remote([config.spectre_bin, "-W"])
    ocean = runner.run_ocean_script(
        ocean_script,
        run_name="environment_check",
        local_log=output_dir / "ocean_verify.log",
    )
    payload.update(
        {
            "spectre_version": spectre.to_dict(),
            "ocean_smoke": ocean,
        }
    )

    report_download: dict[str, Any] | None = None
    report_values: dict[str, str] = {}
    if ocean.get("status") == "ok":
        remote_report = f"{ocean['remote_dir']}/verify_design_report.txt"
        local_report = output_dir / "verify_design_report.txt"
        download = runner.download(remote_report, local_report)
        report_download = download.to_dict()
        if download.ok:
            report_values = _parse_key_values(local_report)

    payload["ocean_report_download"] = report_download
    payload["ocean_report"] = report_values
    payload["status"] = (
        "ok"
        if spectre.ok
        and ocean.get("status") == "ok"
        and report_download is not None
        and report_download.get("ok")
        and report_values.get("status") == "ok"
        else "failed"
    )
    write_json(output_dir / "cadence_environment_report.json", payload)
    return payload


def _parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in raw_line:
            key, value = raw_line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify SSH, Spectre, and the OCEAN/SKILL interpreter."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/remote_cadence.local.yaml"),
    )
    parser.add_argument(
        "--ocean-script",
        type=Path,
        default=Path("circuit/ocean/verify_design.ocn"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/logs/cadence_environment"),
    )
    args = parser.parse_args()

    try:
        payload = verify_environment(args.config, args.ocean_script, args.output_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
