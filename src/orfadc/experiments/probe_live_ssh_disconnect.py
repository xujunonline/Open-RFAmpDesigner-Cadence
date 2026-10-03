from __future__ import annotations

import argparse
import hashlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from orfadc.agents.inspect_pending_remote import probe_remote_diagnostic_directory
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.probe_inflight_lost_reply import RecordingProbeRunner
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_agent_diagnostic import run_diagnostic_agent


class DisconnectObservedSpectreSSHRunner(RemoteRunner):
    """Disconnect only this runner's SSH subprocess after a separate live observation."""

    def __init__(self, config) -> None:
        super().__init__(config, executor=self._controlled_executor)
        self.spectre_calls = 0
        self.spectre_remote_dir: str | None = None
        self.ssh_started = Event()
        self.disconnect_requested = Event()
        self.local_ssh_terminated = False
        self.local_ssh_exitcode: int | None = None
        self.local_ssh_pid: int | None = None
        self._spectre_executor_consumed = False

    def run_remote(self, command, *, cwd=None, timeout_seconds=None):
        is_spectre = (
            len(command) == 10 and command[0] == self.config.spectre_bin
            and tuple(command[1:]) == (
                "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
                "+log", "spectre.log", "netlist.scs",
            )
        )
        if is_spectre:
            if self.spectre_calls or cwd is None:
                raise ValueError("disconnect probe permits one bounded Spectre dispatch")
            self.spectre_calls += 1
            self.spectre_remote_dir = cwd
        return super().run_remote(command, cwd=cwd, timeout_seconds=timeout_seconds)

    def _controlled_executor(self, argv, **kwargs):
        if self.spectre_calls != 1 or self._spectre_executor_consumed:
            return subprocess.run(argv, **kwargs)
        self._spectre_executor_consumed = True
        timeout = kwargs["timeout"]
        process = subprocess.Popen(
            argv, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.local_ssh_pid = process.pid
        self.ssh_started.set()
        deadline = time.monotonic() + timeout
        while True:
            if self.disconnect_requested.is_set() and process.poll() is None:
                process.terminate()
                self.local_ssh_terminated = True
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                self.local_ssh_exitcode = process.returncode
                return subprocess.CompletedProcess(
                    argv, 255, "", "controlled local SSH termination after a live Spectre observation",
                )
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.local_ssh_exitcode = process.returncode
                return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
            if time.monotonic() >= deadline:
                process.kill()
                process.communicate()
                self.local_ssh_exitcode = process.returncode
                raise subprocess.TimeoutExpired(argv, timeout)
            time.sleep(0.02)


def probe_live_ssh_disconnect(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path, *,
    template: Path, template_sha256: str, spec_id: str, seed: int,
    rd_ohm: float, vbias_v: float,
) -> tuple[Path, dict]:
    for path in (runs_root, trace_root, template):
        _require_private_path(path)
    config = load_remote_config(config_path)
    dispatch = DisconnectObservedSpectreSSHRunner(config)
    observer = RecordingProbeRunner(config)
    samples = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_diagnostic_agent,
            config_path, specs_path, runs_root, trace_root,
            template=template, template_sha256=template_sha256,
            spec_id=spec_id, seed=seed, rd_ohm=rd_ohm, vbias_v=vbias_v,
            runner=dispatch,
        )
        start_deadline = time.monotonic() + 45
        while not dispatch.ssh_started.wait(timeout=0.1):
            if future.done():
                future.result()
                raise RuntimeError("Spectre SSH ended before a live observation could begin")
            if time.monotonic() >= start_deadline:
                raise RuntimeError("Spectre SSH did not begin within the bounded preflight window")
        remote_dir = dispatch.spectre_remote_dir
        if remote_dir is None:
            raise RuntimeError("Spectre SSH lacks a unique remote run directory")
        observation_deadline = time.monotonic() + 20
        observed_active = False
        while time.monotonic() < observation_deadline:
            parsed = probe_remote_diagnostic_directory(observer, remote_dir)
            raw = observer.last_result
            samples.append({
                "observed_at_utc": datetime.now(UTC).isoformat(),
                "parsed": parsed,
                "raw_returncode": raw.returncode if raw else None,
                "raw_stdout": raw.stdout if raw else None,
                "raw_stderr": raw.stderr if raw else None,
            })
            if parsed.get("spectre_active") is True:
                observed_active = True
                dispatch.disconnect_requested.set()
                break
            if future.done():
                break
            time.sleep(0.2)
        trace_dir, index = future.result()
    report = {
        "schema_version": 1,
        "mode": "real_spectre_live_observation_then_local_ssh_termination",
        "trace_id": trace_dir.name,
        "candidate_run_id": index.get("candidate_run_id"),
        "remote_dir_sha256": hashlib.sha256(remote_dir.encode("utf-8")).hexdigest(),
        "samples": samples,
        "spectre_in_flight_observed": observed_active,
        "local_ssh_pid": dispatch.local_ssh_pid,
        "local_ssh_terminated": dispatch.local_ssh_terminated,
        "local_ssh_exitcode": dispatch.local_ssh_exitcode,
        "spectre_calls": dispatch.spectre_calls,
        "execution_status": index["execution_status"],
        "spectre_dispatched_by_observer": False,
        "not_lna_result": True,
        "spec_pass": None,
    }
    write_json(trace_dir / "live_disconnect_probe.json", report)
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Disconnect one SSH controller after live Spectre observation")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "agent_live_disconnect_probe")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    try:
        trace_dir, report = probe_live_ssh_disconnect(
            args.config, args.specs, args.runs_root, args.trace_root,
            template=args.template, template_sha256=args.template_sha256,
            spec_id=args.spec, seed=args.seed, rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(
        f"trace_dir={trace_dir.resolve()} samples={len(report['samples'])} "
        f"active={report['spectre_in_flight_observed']} "
        f"local_ssh_terminated={report['local_ssh_terminated']} "
        f"agent_status={report['execution_status']}"
    )
    return 0 if report["local_ssh_terminated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
