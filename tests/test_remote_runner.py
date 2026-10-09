from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orfadc.cadence.remote_runner import RemoteCadenceConfig, RemoteRunner, load_remote_config


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.uploaded = b""

    def __call__(self, argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[0] == "scp":
            if "@eda-host.example:" in argv[-1]:
                self.uploaded = Path(argv[-2]).read_bytes()
            else:
                Path(argv[-1]).write_bytes(self.uploaded)
        stdout = ""
        if argv[0] == "ssh" and "tool.ocean" in argv[-1]:
            stdout = (
                "user=edauser\n"
                "host=eda-host.example\n"
                "pwd=/home/edauser\n"
                "tool.ocean=/opt/cadence/bin/ocean\n"
                "tool.spectre=/opt/cadence/bin/spectre\n"
                "tool.virtuoso=\n"
            )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def test_remote_command_uses_batch_mode_and_redacts_identity(tmp_path: Path) -> None:
    identity = tmp_path / "key"
    identity.write_text("test-only", encoding="utf-8")
    executor = FakeExecutor()
    runner = RemoteRunner(
        RemoteCadenceConfig(
            host="eda-host.example",
            user="edauser",
            identity_file=identity,
            remote_root="/home/edauser/orfadc",
        ),
        executor=executor,
    )

    result = runner.run_remote(["pwd"], cwd="/home/edauser/orfadc")

    assert result.ok
    assert "BatchMode=yes" in result.argv
    assert "<identity-file>" in result.argv
    assert str(identity.resolve()) not in result.argv
    assert executor.calls[0][0] == "ssh"
    assert "cd /home/edauser/orfadc && pwd" in executor.calls[0][-1]
    assert "timeout --signal=TERM --kill-after=3s 290s" in executor.calls[0][-1]


def test_probe_returns_tool_availability() -> None:
    executor = FakeExecutor()
    runner = RemoteRunner(
        RemoteCadenceConfig(
            host="eda-host.example",
            user="edauser",
            remote_root="/home/edauser/orfadc",
        ),
        executor=executor,
    )

    payload = runner.probe()

    assert payload["status"] == "ok"
    assert payload["user"] == "edauser"
    assert payload["tools"]["ocean"]["found"] is True
    assert payload["tools"]["spectre"]["path"] == "/opt/cadence/bin/spectre"
    assert payload["tools"]["virtuoso"]["found"] is False


def test_transfer_round_trip_compares_hashes(tmp_path: Path) -> None:
    source = tmp_path / "probe.txt"
    source.write_text("Open-RFAmpDesigner-Cadence\n", encoding="utf-8")
    downloaded = tmp_path / "downloaded" / "probe.txt"
    executor = FakeExecutor()
    runner = RemoteRunner(
        RemoteCadenceConfig(
            host="eda-host.example",
            user="edauser",
            remote_root="/home/edauser/orfadc",
        ),
        executor=executor,
    )

    payload = runner.verify_transfer(source, downloaded)

    assert payload["status"] == "ok"
    assert payload["source_sha256"] == payload["downloaded_sha256"]
    assert downloaded.read_bytes() == source.read_bytes()


def test_config_loader_requires_private_host_and_user(tmp_path: Path) -> None:
    config_path = tmp_path / "remote.yaml"
    config_path.write_text(
        "remote:\n  host: null\n  user: null\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="remote.host"):
        load_remote_config(config_path)


def test_config_loader_reads_ocean_graph_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "remote.yaml"
    config_path.write_text(
        "remote:\n"
        "  host: eda-host.example\n"
        "  user: edauser\n"
        "  work_root: /home/edauser/orfadc\n"
        "cadence:\n"
        "  ocean_nograph: false\n",
        encoding="utf-8",
    )

    config = load_remote_config(config_path)

    assert config.ocean_nograph is False


def test_ocean_nograph_uses_configured_xvfb_path(tmp_path: Path) -> None:
    script = tmp_path / "smoke.ocn"
    script.write_text("exit()\n", encoding="utf-8")
    executor = FakeExecutor()
    runner = RemoteRunner(
        RemoteCadenceConfig(
            host="eda-host.example",
            user="edauser",
            remote_root="/home/edauser/orfadc",
            ocean_nograph=True,
            xvfb_path="/home/edauser/.local/xvfb/usr/bin",
        ),
        executor=executor,
    )

    payload = runner.run_ocean_script(script, run_name="smoke")

    assert payload["status"] == "ok"
    ocean_call = next(
        call for call in executor.calls if call[0] == "ssh" and "-restore" in call[-1]
    )
    assert "CDS_XVFB_PATH=/home/edauser/.local/xvfb/usr/bin" in ocean_call[-1]
    assert "-nograph" in ocean_call[-1]


def test_insecure_host_key_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="strict_host_key_checking"):
        RemoteCadenceConfig(
            host="eda-host.example",
            user="edauser",
            strict_host_key_checking="no",
        )


def test_remote_target_and_path_injection_are_rejected() -> None:
    with pytest.raises(ValueError, match="host or user"):
        RemoteCadenceConfig(host="-oProxyCommand=bad", user="edauser")

    runner = RemoteRunner(
        RemoteCadenceConfig(host="eda-host.example", user="edauser"),
        executor=FakeExecutor(),
    )
    with pytest.raises(ValueError, match="unsupported characters"):
        runner.download("/tmp/result;touch_bad", Path("unused"))
    with pytest.raises(ValueError, match="must not contain"):
        runner.download("/tmp/../private", Path("unused"))


def test_timeout_is_returned_as_structured_failure() -> None:
    def timeout_executor(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 5, output="partial")

    runner = RemoteRunner(
        RemoteCadenceConfig(host="eda-host.example", user="edauser"),
        executor=timeout_executor,
    )

    result = runner.run_remote(["sleep", "10"], timeout_seconds=5)

    assert result.returncode == 124
    assert result.ok is False
    assert result.stdout == "partial"
    assert "timed out" in result.stderr


def test_ocean_timeout_still_downloads_log(tmp_path: Path) -> None:
    script = tmp_path / "smoke.ocn"
    script.write_text("exit()\n", encoding="utf-8")
    executor = FakeExecutor()

    def timeout_ocean(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        result = executor(argv, **kwargs)
        if argv[0] == "ssh" and "-restore" in argv[-1]:
            return subprocess.CompletedProcess(argv, 124, stdout="", stderr="license wait")
        return result

    runner = RemoteRunner(
        RemoteCadenceConfig(host="eda-host.example", user="edauser"),
        executor=timeout_ocean,
    )
    payload = runner.run_ocean_script(script, run_name="timeout", local_log=tmp_path / "ocean.log")

    assert payload["status"] == "ocean_timeout"
    assert payload["log_download"]["ok"] is True


def _scripted_executor(results):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        rc, err = results[min(len(calls), len(results)) - 1]
        return subprocess.CompletedProcess(argv, rc, stdout="", stderr=err)
    return run, calls


def test_connect_phase_failures_are_retried_once_and_nothing_else():
    from orfadc.cadence.remote_runner import RemoteCadenceConfig, RemoteRunner
    cfg = RemoteCadenceConfig(host="eda-host.example", user="edauser")
    slept = []
    cases = [
        # (executor results, expected number of calls, expected final rc)
        ([(255, "ssh: connect to host eda-host.example port 22: Connection refused\n"), (0, "")], 2, 0),
        ([(255, "kex_exchange_identification: read: Connection reset by peer\n"), (255, "kex_exchange_identification: x\n")], 2, 255),
        ([(255, "Connection closed by 10.0.0.5 port 22\n"), (0, "")], 2, 0),
        ([(255, "client_loop: send disconnect: Broken pipe\n"), (0, "")], 1, 255),       # mid-session: never retried
        ([(255, "Read from remote host x: Connection reset by peer\n"), (0, "")], 1, 255),
        ([(1, "spectre failed\n"), (0, "")], 1, 1),                                        # remote command failed
        ([(0, "")], 1, 0),
    ]
    for results, n_calls, rc in cases:
        run, calls = _scripted_executor(results)
        r = RemoteRunner(cfg, executor=run, sleep=slept.append).run_shell("echo hi")
        assert (len(calls), r.returncode) == (n_calls, rc), results
    assert slept and all(s == 5.0 for s in slept)
    run, calls = _scripted_executor([(255, "ssh: connect to host h port 22: Connection timed out\n")] * 3)
    RemoteRunner(cfg, executor=run, sleep=slept.append, connect_retries=0).run_shell("echo hi")
    assert len(calls) == 1
