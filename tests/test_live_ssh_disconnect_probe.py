from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.experiments import probe_live_ssh_disconnect as module


class _FakeSSHProcess:
    def __init__(self, *, completed: bool = False) -> None:
        self.pid = 12345
        self.returncode = 0 if completed else None
        self.terminate_called = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def communicate(self, timeout=None):
        return "controller-output", "controller-error"


def test_disconnect_runner_terminates_only_its_own_live_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeSSHProcess()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    runner = module.DisconnectObservedSpectreSSHRunner(
        RemoteCadenceConfig(host="example.org", user="student"),
    )
    runner.spectre_calls = 1
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner._controlled_executor, ["ssh"], timeout=5)
        assert runner.ssh_started.wait(timeout=1)
        assert not process.terminate_called
        runner.disconnect_requested.set()
        result = future.result(timeout=1)
    assert process.terminate_called
    assert runner.local_ssh_terminated is True
    assert runner.local_ssh_exitcode == -15
    assert result.returncode == 255
    assert result.stdout == ""


def test_disconnect_runner_does_not_claim_a_completed_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeSSHProcess(completed=True)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    runner = module.DisconnectObservedSpectreSSHRunner(
        RemoteCadenceConfig(host="example.org", user="student"),
    )
    runner.spectre_calls = 1
    runner.disconnect_requested.set()
    result = runner._controlled_executor(["ssh"], timeout=5)
    assert not process.terminate_called
    assert runner.local_ssh_terminated is False
    assert result.returncode == 0


@pytest.mark.parametrize("active", [False, True])
def test_probe_requests_disconnect_only_after_remote_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool,
) -> None:
    config = RemoteCadenceConfig(host="example.org", user="student")
    trace_dir = tmp_path / "trace" / "run001"
    trace_dir.mkdir(parents=True)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "load_remote_config", lambda path: config)

    def fake_agent(*args, runner, **kwargs):
        runner.spectre_remote_dir = "/tmp/unique-run"
        runner.local_ssh_pid = 42
        runner.ssh_started.set()
        if active:
            assert runner.disconnect_requested.wait(timeout=1)
            runner.local_ssh_terminated = True
        return trace_dir, {
            "candidate_run_id": "candidate001",
            "execution_status": "pending_remote_evaluation" if active else "budget_exhausted",
        }

    monkeypatch.setattr(module, "run_diagnostic_agent", fake_agent)
    monkeypatch.setattr(
        module, "probe_remote_diagnostic_directory",
        lambda runner, remote_dir: {"state": "observed", "spectre_active": active},
    )
    _, report = module.probe_live_ssh_disconnect(
        tmp_path / "config", tmp_path / "specs", tmp_path / "runs", tmp_path / "trace",
        template=tmp_path / "template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=240, vbias_v=0.67,
    )
    assert report["spectre_in_flight_observed"] is active
    assert report["local_ssh_terminated"] is active
    assert (trace_dir / "live_disconnect_probe.json").is_file()
