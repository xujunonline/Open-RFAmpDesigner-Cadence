from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig, RemoteRunner
from orfadc.experiments import run_agent_diagnostic
from orfadc.experiments import probe_inflight_lost_reply as inflight_module
from orfadc.experiments.probe_lost_reply_recovery import LostReplyAfterSpectreRunner
from orfadc.schemas import Spec


_SPECTRE = (
    "spectre", "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
    "+log", "spectre.log", "netlist.scs",
)


@pytest.mark.parametrize("actual_returncode", [0, 1])
def test_lost_reply_is_injected_only_after_one_real_spectre_return(
    monkeypatch: pytest.MonkeyPatch, actual_returncode: int,
) -> None:
    called: list[tuple[tuple[str, ...], str | None]] = []

    def fake_remote(self, command, *, cwd=None, timeout_seconds=None):
        called.append((tuple(command), cwd))
        return CommandResult("ssh", ("ssh",), actual_returncode, "actual-output", "actual-error")

    monkeypatch.setattr(RemoteRunner, "run_remote", fake_remote)
    runner = LostReplyAfterSpectreRunner(RemoteCadenceConfig(host="example.org", user="student"))
    ordinary = runner.run_remote(["true"], cwd="/tmp")
    assert ordinary.returncode == actual_returncode
    assert not runner.reply_suppressed
    result = runner.run_remote(_SPECTRE, cwd="/tmp/one")
    assert called[-1] == (_SPECTRE, "/tmp/one")
    assert runner.spectre_calls == 1
    assert runner.dispatch_starting.is_set()
    assert runner.spectre_remote_dir == "/tmp/one"
    assert runner.actual_returncode == actual_returncode
    assert result.returncode == (255 if actual_returncode == 0 else actual_returncode)
    assert runner.reply_suppressed is (actual_returncode == 0)
    if actual_returncode == 0:
        assert result.stdout == ""
        assert "controlled lost-reply" in result.stderr
    else:
        assert result.stdout == "actual-output"
    with pytest.raises(ValueError, match="exactly one"):
        runner.run_remote(_SPECTRE, cwd="/tmp/one")
    assert len(called) == 2


def test_lost_reply_runner_rejects_missing_remote_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RemoteRunner, "run_remote", lambda *a, **k: pytest.fail("must not dispatch"))
    runner = LostReplyAfterSpectreRunner(RemoteCadenceConfig(host="example.org", user="student"))
    with pytest.raises(ValueError, match="exactly one"):
        runner.run_remote(_SPECTRE)


def test_diagnostic_runner_must_match_bound_remote_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    expected = RemoteCadenceConfig(host="example.org", user="student")
    wrong = LostReplyAfterSpectreRunner(RemoteCadenceConfig(host="other.example.org", user="student"))
    monkeypatch.setattr(run_agent_diagnostic, "_require_private_path", lambda path: None)
    monkeypatch.setattr(run_agent_diagnostic, "load_specs", lambda path: [spec])
    monkeypatch.setattr(run_agent_diagnostic, "render_active_diagnostic_netlist", lambda *a: "validated")
    monkeypatch.setattr(run_agent_diagnostic, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(run_agent_diagnostic, "load_remote_config", lambda path: expected)
    with pytest.raises(ValueError, match="differs from the bound remote config"):
        run_agent_diagnostic.run_diagnostic_agent(
            tmp_path / "config", tmp_path / "specs", tmp_path / "runs", tmp_path / "trace",
            template=tmp_path / "template", template_sha256="0" * 64,
            spec_id="S1", seed=0, rd_ohm=220, vbias_v=0.67, runner=wrong,
        )
    assert not (tmp_path / "trace").exists()


@pytest.mark.parametrize("active", [False, True])
def test_inflight_probe_requires_observed_remote_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool,
) -> None:
    config = RemoteCadenceConfig(host="example.org", user="student")
    trace = tmp_path / "trace" / "run001"
    trace.mkdir(parents=True)
    monkeypatch.setattr(inflight_module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(inflight_module, "load_remote_config", lambda path: config)

    def fake_dispatch(*args, runner, **kwargs):
        runner.spectre_remote_dir = "/tmp/unique-run"
        runner.dispatch_starting.set()
        return trace, {
            "candidate_run_id": "candidate001", "actual_remote_returncode": 0,
            "reply_suppressed": True, "pending_execution_status": "pending_remote_evaluation",
        }

    monkeypatch.setattr(inflight_module, "probe_lost_reply_recovery", fake_dispatch)
    monkeypatch.setattr(
        inflight_module, "probe_remote_diagnostic_directory",
        lambda runner, remote_dir: {"state": "observed", "spectre_active": active},
    )
    trace_dir, report = inflight_module.probe_inflight_lost_reply(
        tmp_path / "config", tmp_path / "specs", tmp_path / "runs", tmp_path / "trace",
        template=tmp_path / "template", template_sha256="0" * 64,
        spec_id="S1", seed=0, rd_ohm=230, vbias_v=0.67,
    )
    assert trace_dir == trace
    assert report["spectre_in_flight_observed"] is active
    assert report["spectre_dispatched_by_observer"] is False
    assert (trace / "inflight_probe.json").is_file()
