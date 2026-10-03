from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents.inspect_pending_remote import (
    inspect_pending_diagnostic_remote, probe_remote_diagnostic_directory,
    snapshot_remote_diagnostic_artifacts,
)
from orfadc.agents.manager import Manager
from orfadc.agents.remote_identity import write_remote_identity_snapshot
from orfadc.agents.spec_snapshots import write_spec_snapshot
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.schemas import Candidate, Spec


class DiagnosticSearcher:
    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        return [Candidate(
            candidate_id=f"{spec.id}_seed{seed}_oa_diag", spec_id=spec.id, seed=seed,
            power_ratio_list=[], active_params={"rd_ohm": 190.0, "vbias_v": 0.67},
            status="active_common_source_diagnostic",
        )]


class FakeRunner:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.config = RemoteCadenceConfig(host="example.org", user="student")
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], int]] = []

    def run_remote(self, command: list[str], *, timeout_seconds: int) -> CommandResult:
        self.calls.append((command, timeout_seconds))
        return CommandResult("ssh", (), self.returncode, self.stdout, "")


class SequenceRunner(FakeRunner):
    def __init__(self, replies: list[tuple[str, int]]) -> None:
        super().__init__("")
        self.replies = list(replies)

    def run_remote(self, command: list[str], *, timeout_seconds: int, cwd: str | None = None) -> CommandResult:
        self.calls.append((command, timeout_seconds))
        stdout, returncode = self.replies.pop(0)
        return CommandResult("ssh", (), returncode, stdout, "")


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _pending(trace_dir: Path, *, bound: bool = True) -> Candidate:
    spec = _spec()
    manager = Manager(searcher=DiagnosticSearcher(), max_searches=1, max_evaluations=1)
    manager.enable_journal(trace_dir)
    try:
        manager.context = (spec.id, 0)
        remote_digest = (
            write_remote_identity_snapshot(trace_dir, FakeRunner("").config) if bound else None
        )
        manager._record(
            "RunStarted", spec_id=spec.id, seed=0, max_searches=1, max_evaluations=1,
            spec_sha256=write_spec_snapshot(trace_dir, spec), dispatch_mode="planned",
            **({"remote_identity_sha256": remote_digest} if remote_digest else {}),
        )
        candidate = manager.search_candidates(spec)[0]
        manager.pop_candidate(run_id="planned001")
    finally:
        manager.close_journal()
    return candidate


def _remote(directory: str, active: int = 0, log: int = 0, sp: int = 0, noise: int = 0) -> str:
    return (f"directory={directory}\nactive={active}\nlog={log}\n"
            f"sp={sp}\nnoise={noise}\n")


def _hash_output(*, changed: bool = False) -> str:
    files = ("netlist.scs", "ade_e.scs", "spectre.log", "psf/dcOp.dc",
             "psf/sp.sp", "psf/sp.noise.sp")
    return "".join(
        f"{('b' if changed and index == 0 else 'a') * 64}  {name}\n"
        for index, name in enumerate(files)
    )


@pytest.mark.parametrize(("raw", "expected"), [
    (_remote("missing"), "dispatch_not_observed"),
    (_remote("present", active=1, log=1), "spectre_in_flight"),
    (_remote("present", log=1, sp=1, noise=1), "remote_quiescent_unverified"),
    (_remote("symlink"), "remote_unsafe"),
    ("login banner\n", "remote_unknown"),
])
def test_pending_probe_classifies_without_dispatch(raw: str, expected: str) -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        runner = FakeRunner(raw)
        report = inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert report["status"] == expected
        assert report["candidate_run_id"] == "planned001"
        assert report["local_archive"] == "absent"
        assert report["safe_to_dispatch"] is False
        assert report["spectre_dispatched_by_probe"] is False
        assert len(runner.calls) == 1
        command, timeout = runner.calls[0]
        assert command[:2] == ["bash", "-c"] and timeout == 30
        assert command[-1].endswith("_planned001")


def test_hash_only_local_archive_still_requires_raw_audit() -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        candidate = _pending(trace_dir)
        # Use a separate private temporary archive; do not collide with a real run.
        runs_root = Path(root) / "runs"
        run_dir = runs_root / "S1" / "seed0" / candidate.candidate_id / "planned001"
        run_dir.mkdir(parents=True)
        payload = {
            "schema_version": 1, "status": "backend_error", "simulation_status": "unknown",
            "circuit_class": "active_common_source_smoke", "not_lna_result": True,
            "spec_pass": None, "run_id": run_dir.name, "candidate": candidate.to_dict(),
            "spec": asdict(_spec()), "seed": 0, "timeout_seconds": 300,
        }
        (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
        (run_dir / "candidate.json").write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
        write_evidence_manifest(run_dir, {"metrics": "metrics.json", "candidate": "candidate.json"})
        report = inspect_pending_diagnostic_remote(
            trace_dir, runs_root, FakeRunner(_remote("missing")),
        )
        assert report["local_archive"] == "hash_verified_raw_audit_pending"
        assert report["status"] == "local_raw_audit_required"
        assert report["safe_to_dispatch"] is False


def test_probe_uses_current_planned_id_but_rejects_changed_candidate_snapshot() -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        journal = trace_dir / "agent_events.jsonl"
        journal.write_text(journal.read_text(encoding="utf-8").replace(
            '"run_id": "planned001"', '"run_id": "other001"',
        ), encoding="utf-8")
        runner = FakeRunner(_remote("present", active=1))
        # A changed ID is syntactically valid; the journal is not a signed record.
        report = inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert report["candidate_run_id"] == "other001"
        assert runner.calls[0][0][-1].endswith("_other001")
        assert report["safe_to_dispatch"] is False

    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        snapshot = trace_dir / "agent_candidates.jsonl"
        snapshot.write_text(snapshot.read_text(encoding="ascii").replace("190.0", "200.0"), encoding="ascii")
        runner = FakeRunner(_remote("present", active=1))
        with pytest.raises(ValueError):
            inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert runner.calls == []


def test_remote_probe_rejects_unsafe_path_and_uncertain_ssh() -> None:
    runner = FakeRunner(_remote("missing"))
    for path in ("relative", "/tmp/../other", "/tmp//other", "/tmp/$(whoami)"):
        with pytest.raises(ValueError):
            probe_remote_diagnostic_directory(runner, path)
    assert runner.calls == []
    runner = FakeRunner("", returncode=124)
    assert probe_remote_diagnostic_directory(runner, "/tmp/safe") == {
        "state": "unknown", "reason": "remote_probe_failed",
    }


def test_pending_probe_rejects_changed_remote_config_before_ssh() -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        runner = FakeRunner(_remote("present"))
        runner.config = RemoteCadenceConfig(host="another.example.org", user="student")
        with pytest.raises(ValueError, match="remote config differs"):
            inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert runner.calls == []


def test_pending_probe_rejects_unbound_legacy_trace_and_tampered_snapshot() -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir, bound=False)
        runner = FakeRunner(_remote("present"))
        with pytest.raises(ValueError, match="planned pending diagnostic"):
            inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert runner.calls == []

    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        path = trace_dir / "agent_remote.json"
        path.write_bytes(path.read_bytes().replace(b"example.org", b"another.example.org"))
        runner = FakeRunner(_remote("present"))
        with pytest.raises(ValueError, match="digest differs"):
            inspect_pending_diagnostic_remote(trace_dir, _PRIVATE_ROOT, runner)
        assert runner.calls == []


def test_stable_remote_artifact_snapshot_is_not_adoption_permission() -> None:
    runner = SequenceRunner([
        (_remote("present", log=1, sp=1, noise=1), 0), (_hash_output(), 0),
        (_remote("present", log=1, sp=1, noise=1), 0), (_hash_output(), 0),
    ])
    observed_waits = []
    result = snapshot_remote_diagnostic_artifacts(
        runner, "/tmp/known_run", waiter=observed_waits.append,
    )
    assert result["status"] == "stable_unverified"
    assert result["safe_to_adopt"] is False
    assert len(result["artifacts_sha256"]) == 6
    assert observed_waits == [3.0] and len(runner.calls) == 4


@pytest.mark.parametrize(("replies", "expected"), [
    ([(_remote("present", active=1), 0)], "spectre_in_flight"),
    ([(_remote("missing"), 0)], "remote_missing"),
    ([(_remote("present"), 0), (_hash_output(), 1)], "remote_artifacts_unavailable"),
    ([(_remote("present"), 0), (_hash_output(), 0),
      (_remote("present", active=1), 0)], "spectre_in_flight"),
    ([(_remote("present"), 0), (_hash_output(), 0),
      (_remote("present"), 0), (_hash_output(changed=True), 0)], "remote_artifacts_changed"),
])
def test_remote_artifact_snapshot_rejects_unsafe_or_changing_observation(
    replies: list[tuple[str, int]], expected: str,
) -> None:
    runner = SequenceRunner(replies)
    result = snapshot_remote_diagnostic_artifacts(
        runner, "/tmp/known_run", waiter=lambda seconds: None,
    )
    assert result["status"] == expected
    assert result["safe_to_adopt"] is False


def test_bound_pending_probe_can_include_stable_artifact_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        runner = SequenceRunner([
            (_remote("present", log=1, sp=1, noise=1), 0),
            (_remote("present", log=1, sp=1, noise=1), 0), (_hash_output(), 0),
            (_remote("present", log=1, sp=1, noise=1), 0), (_hash_output(), 0),
        ])
        monkeypatch.setattr("orfadc.agents.inspect_pending_remote.time.sleep", lambda _: None)
        report = inspect_pending_diagnostic_remote(
            trace_dir, _PRIVATE_ROOT, runner, stable_artifacts=True,
        )
        assert report["status"] == "remote_quiescent_raw_audit_required"
        assert report["artifact_snapshot"]["status"] == "stable_unverified"
        assert report["artifact_snapshot"]["safe_to_adopt"] is False
        assert report["safe_to_dispatch"] is False
        assert len(runner.calls) == 5


@pytest.mark.parametrize(("snapshot_status", "expected"), [
    ("remote_artifacts_unavailable", "remote_quiescent_incomplete"),
    ("remote_artifacts_changed", "remote_artifacts_changing"),
    ("remote_unknown", "remote_unknown"),
])
def test_pending_probe_does_not_offer_recovery_for_incomplete_or_changing_remote(
    monkeypatch: pytest.MonkeyPatch, snapshot_status: str, expected: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="pending_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        trace_dir = Path(root) / "trace"
        trace_dir.mkdir()
        _pending(trace_dir)
        monkeypatch.setattr(
            "orfadc.agents.inspect_pending_remote.snapshot_remote_diagnostic_artifacts",
            lambda *_: {"status": snapshot_status, "safe_to_adopt": False},
        )
        report = inspect_pending_diagnostic_remote(
            trace_dir, _PRIVATE_ROOT, FakeRunner(_remote("present", log=1)),
            stable_artifacts=True,
        )
        assert report["status"] == expected
        assert report["safe_to_dispatch"] is False
