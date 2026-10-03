from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.agents import recover_pending_failure as module
from orfadc.agents.journal import inspect_journal
from orfadc.agents.reconcile_pending import reconcile_pending_diagnostic
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.config_loader import load_specs
from orfadc.experiments import run_agent_diagnostic as agent_module
from orfadc.experiments.audit_failed_active_diagnostic import (
    FAILURE_ARTIFACTS, terminal_spectre_error_count,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_SOURCE = _PRIVATE_ROOT / "S1/seed0/S1_seed0_oa_diag/20260927T081306Z_57cfbd7e"
_TEMPLATE = _PRIVATE_ROOT / "lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"
_TEMPLATE_SHA = "9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814"
_FAILED_LOG = b"spectre completes with 1 error, 0 warnings, and 0 notices.\n"


class FailureRunner:
    def __init__(self, log: bytes = _FAILED_LOG) -> None:
        self.config = RemoteCadenceConfig(host="example.org", user="student")
        self.log = log
        self.commands: list[list[str]] = []
        self.downloads: list[str] = []

    def run_remote(self, command: list[str], **_: object) -> CommandResult:
        self.commands.append(command)
        if command[0] != "bash":
            pytest.fail("failure recovery attempted an unexpected remote command")
        return CommandResult("ssh", (), 0, "", "")

    def download(self, source: str, destination: Path) -> CommandResult:
        name = source.rsplit("/", 1)[-1]
        self.downloads.append(name)
        if name == "spectre.log":
            destination.write_bytes(self.log)
        else:
            shutil.copyfile(_SOURCE / name, destination)
        return CommandResult("download", (), 0, "", "")


def _hashes(log: bytes = _FAILED_LOG) -> dict[str, str]:
    return {
        "netlist.scs": hashlib.sha256((_SOURCE / "netlist.scs").read_bytes()).hexdigest(),
        "ade_e.scs": hashlib.sha256((_SOURCE / "ade_e.scs").read_bytes()).hexdigest(),
        "spectre.log": hashlib.sha256(log).hexdigest(),
    }


def _pending_agent(monkeypatch: pytest.MonkeyPatch, root: Path, runner: FailureRunner) -> tuple[Path, Path]:
    runs = root / "runs"
    runs.mkdir()
    monkeypatch.setattr(agent_module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(agent_module, "load_remote_config", lambda _: runner.config)

    def uncertain_backend(config_path, runs_root, spec, candidate, **kwargs):
        assert kwargs["preserve_uncertain_dispatch"] is True
        run_dir = runs_root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / kwargs["run_id"]
        run_dir.mkdir(parents=True)
        for name in ("netlist.scs", "ade_e.scs", "candidate.json"):
            shutil.copyfile(_SOURCE / name, run_dir / name)
        control = run_dir / "control_attempt"
        control.mkdir()
        (control / "spectre.stderr.log").write_text("SSH lost\n", encoding="ascii")
        raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain")

    monkeypatch.setattr(agent_module, "run_active_diagnostic_candidate", uncertain_backend)
    trace, index = agent_module.run_diagnostic_agent(
        root / "unused_config", Path("config/specs_table_iii.yaml"), runs, root / "agent",
        template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        spec_id="S1", seed=0, rd_ohm=210, vbias_v=0.67,
    )
    assert index["execution_status"] == "pending_remote_evaluation"
    return trace, runs


def test_terminal_failure_log_requires_one_nonzero_error_summary() -> None:
    assert terminal_spectre_error_count(_FAILED_LOG) == 1
    for bad in (
        b"waiting for license\n", b"spectre completes with 0 errors, 0 warnings\n",
        _FAILED_LOG + _FAILED_LOG,
        _FAILED_LOG + b"spectre completes with 0 errors, 0 warnings\n",
    ):
        with pytest.raises(ValueError, match="terminal error summary"):
            terminal_spectre_error_count(bad)


def test_failure_snapshot_checks_two_idle_observations_and_three_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "directory=present\nactive=0\nlog=1\nsp=0\nnoise=0\n"
    hashes = "".join(f"{'a' * 64}  {name}\n" for name in ("netlist.scs", "ade_e.scs", "spectre.log"))

    class SequenceRunner:
        def __init__(self) -> None:
            self.replies = [remote, hashes, remote, hashes]
            self.commands: list[str] = []

        def run_remote(self, command, **kwargs):
            self.commands.append(command[0])
            return CommandResult("ssh", (), 0, self.replies.pop(0), "")

    runner = SequenceRunner()
    observed_waits: list[float] = []
    monkeypatch.setattr(module.time, "sleep", observed_waits.append)
    snapshot = module.snapshot_remote_failure_artifacts(runner, "/tmp/planned_run")
    assert snapshot["status"] == "stable_unverified_failure"
    assert snapshot["safe_to_adopt"] is False
    assert set(snapshot["artifacts_sha256"]) == {"netlist.scs", "ade_e.scs", "spectre.log"}
    assert runner.commands == ["bash", "sha256sum", "bash", "sha256sum"]
    assert observed_waits == [3.0]


def test_failure_recovery_reconciles_evidenced_failure_without_spectre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SOURCE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private OA source archive is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="terminal_failure_recovery_", dir=_PRIVATE_ROOT.resolve())
    with temporary:
        root = Path(temporary.name)
        runner = FailureRunner()
        trace, runs = _pending_agent(monkeypatch, root, runner)
        monkeypatch.setattr(module, "snapshot_remote_failure_artifacts", lambda *_: {
            "status": "stable_unverified_failure", "artifacts_sha256": _hashes(),
        })
        archive, report = module.recover_pending_diagnostic_failure(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert report["status"] == "recovered_terminal_failure_audited"
        assert report["terminal_error_count"] == 1
        assert report["spectre_dispatched_by_recovery"] is False
        assert runner.downloads == ["netlist.scs", "ade_e.scs", "spectre.log"]
        assert [command[0] for command in runner.commands] == ["bash"]
        assert (archive / "control_attempt/spectre.stderr.log").read_text() == "SSH lost\n"
        assert read_evidenced_metrics(archive)["spec_pass"] is None
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        reconciled = reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert reconciled["status"] == "reconciled_terminal_diagnostic_failure"
        assert reconciled["simulation_status"] == "failed"
        assert reconciled["refiner_status"] == "needs_evaluation"
        assert reconciled["spectre_dispatched_by_reconciliation"] is False
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"
        with pytest.raises(ValueError):
            reconcile_pending_diagnostic(
                trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )


@pytest.mark.parametrize("obstacle", ["active", "missing_marker", "wrong_identity", "changed_hash"])
def test_failure_recovery_rejects_unsafe_remote_and_keeps_pending(
    monkeypatch: pytest.MonkeyPatch, obstacle: str,
) -> None:
    if not _SOURCE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private OA source archive is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="terminal_failure_reject_", dir=_PRIVATE_ROOT.resolve())
    with temporary:
        root = Path(temporary.name)
        runner = FailureRunner(b"waiting for license\n" if obstacle == "missing_marker" else _FAILED_LOG)
        trace, runs = _pending_agent(monkeypatch, root, runner)
        before = (trace / "agent_events.jsonl").read_bytes()
        if obstacle == "wrong_identity":
            runner.config = RemoteCadenceConfig(host="different.example.org", user="student")
        elif obstacle == "active":
            monkeypatch.setattr(module, "snapshot_remote_failure_artifacts", lambda *_: {
                "status": "spectre_in_flight", "safe_to_adopt": False,
            })
        elif obstacle == "missing_marker":
            monkeypatch.setattr(module, "snapshot_remote_failure_artifacts", lambda *_: {
                "status": "stable_unverified_failure", "artifacts_sha256": _hashes(runner.log),
            })
        else:
            monkeypatch.setattr(module, "snapshot_remote_failure_artifacts", lambda *_: {
                "status": "stable_unverified_failure",
                "artifacts_sha256": {**_hashes(), "spectre.log": "0" * 64},
            })
        with pytest.raises(ValueError):
            module.recover_pending_diagnostic_failure(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert (trace / "agent_events.jsonl").read_bytes() == before
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


def test_failure_auditor_rejects_rehashed_modified_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SOURCE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private OA source archive is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="terminal_failure_tamper_", dir=_PRIVATE_ROOT.resolve())
    with temporary:
        root = Path(temporary.name)
        runner = FailureRunner()
        trace, runs = _pending_agent(monkeypatch, root, runner)
        monkeypatch.setattr(module, "snapshot_remote_failure_artifacts", lambda *_: {
            "status": "stable_unverified_failure", "artifacts_sha256": _hashes(),
        })
        archive, _ = module.recover_pending_diagnostic_failure(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        (archive / "spectre.log").write_bytes(_FAILED_LOG.replace(b"1 error", b"0 errors"))
        manifest = build_evidence_manifest(archive, FAILURE_ARTIFACTS)
        (archive / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        with pytest.raises(ValueError, match="terminal error summary"):
            reconcile_pending_diagnostic(
                trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
