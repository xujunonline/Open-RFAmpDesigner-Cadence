from __future__ import annotations

import argparse
import json
from pathlib import Path

from .remote_runner import RemoteRunner, load_remote_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the remote Cadence host over SSH.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/remote_cadence.local.yaml"),
        help="Private remote configuration file.",
    )
    parser.add_argument(
        "--round-trip",
        type=Path,
        help="Optional local file to upload and download for an SCP round-trip check.",
    )
    parser.add_argument(
        "--download-to",
        type=Path,
        default=Path("results/logs/remote_transfer_probe.downloaded"),
    )
    args = parser.parse_args()

    try:
        runner = RemoteRunner(load_remote_config(args.config))
        probe = runner.probe()
        payload: dict[str, object] = {"probe": probe}
        if args.round_trip is not None and probe["status"] == "ok":
            payload["transfer"] = runner.verify_transfer(args.round_trip, args.download_to)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    probe_ok = probe["status"] == "ok"
    transfer = payload.get("transfer")
    transfer_ok = transfer is None or (isinstance(transfer, dict) and transfer.get("status") == "ok")
    return 0 if probe_ok and transfer_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
