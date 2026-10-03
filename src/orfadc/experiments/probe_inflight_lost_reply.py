from __future__ import annotations

import argparse
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory
from orfadc.cadence.remote_runner import CommandResult, RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.probe_lost_reply_recovery import (
    LostReplyAfterSpectreRunner, probe_lost_reply_recovery,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


class RecordingProbeRunner(RemoteRunner):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.last_result: CommandResult | None = None

    def run_remote(self, command, *, cwd=None, timeout_seconds=None):
        result = super().run_remote(command, cwd=cwd, timeout_seconds=timeout_seconds)
        self.last_result = result
        return result


def probe_inflight_lost_reply(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path, *,
    template: Path, template_sha256: str, spec_id: str, seed: int,
    rd_ohm: float, vbias_v: float,
) -> tuple[Path, dict]:
    _require_private_path(runs_root)
    _require_private_path(trace_root)
    _require_private_path(template)
    config = load_remote_config(config_path)
    dispatch = LostReplyAfterSpectreRunner(config)
    observer = RecordingProbeRunner(config)
    samples = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            probe_lost_reply_recovery,
            config_path, specs_path, runs_root, trace_root,
            template=template, template_sha256=template_sha256,
            spec_id=spec_id, seed=seed, rd_ohm=rd_ohm, vbias_v=vbias_v,
            runner=dispatch,
        )
        start_deadline = time.monotonic() + 45
        while not dispatch.dispatch_starting.wait(timeout=0.1):
            if future.done():
                future.result()
                raise RuntimeError("Spectre dispatch ended before the observation window")
            if time.monotonic() >= start_deadline:
                raise RuntimeError("Spectre dispatch did not begin within the bounded preflight window")
        remote_dir = dispatch.spectre_remote_dir
        if remote_dir is None:
            raise RuntimeError("Spectre dispatch did not expose its unique run directory")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            parsed = probe_remote_diagnostic_directory(observer, remote_dir)
            raw = observer.last_result
            samples.append({
                "observed_at_utc": datetime.now(UTC).isoformat(),
                "parsed": parsed,
                "raw_returncode": raw.returncode if raw else None,
                "raw_stdout": raw.stdout if raw else None,
                "raw_stderr": raw.stderr if raw else None,
            })
            if parsed.get("spectre_active") is True or future.done():
                break
            time.sleep(0.2)
        trace_dir, dispatch_report = future.result()
    observed_active = any(sample["parsed"].get("spectre_active") is True for sample in samples)
    report = {
        "schema_version": 1,
        "mode": "real_spectre_concurrent_readonly_observation_then_lost_reply",
        "trace_id": trace_dir.name,
        "candidate_run_id": dispatch_report["candidate_run_id"],
        "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
        "samples": samples,
        "spectre_in_flight_observed": observed_active,
        "real_spectre_returncode": dispatch_report["actual_remote_returncode"],
        "reply_suppressed": dispatch_report["reply_suppressed"],
        "pending_execution_status": dispatch_report["pending_execution_status"],
        "spectre_dispatched_by_observer": False,
        "not_lna_result": True,
        "spec_pass": None,
    }
    write_json(trace_dir / "inflight_probe.json", report)
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe a real in-flight Spectre job without restarting it")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "agent_inflight_probe")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    try:
        trace_dir, report = probe_inflight_lost_reply(
            args.config, args.specs, args.runs_root, args.trace_root,
            template=args.template, template_sha256=args.template_sha256,
            spec_id=args.spec, seed=args.seed, rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(
        f"trace_dir={trace_dir.resolve()} samples={len(report['samples'])} "
        f"spectre_in_flight_observed={report['spectre_in_flight_observed']} "
        f"pending={report['pending_execution_status']}"
    )
    return 0 if report["spectre_in_flight_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
