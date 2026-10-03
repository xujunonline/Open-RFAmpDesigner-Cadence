from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from orfadc.agents import quarantine_pending as module
from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.reconcile_pending import reconcile_pending_diagnostic
from orfadc.agents.recover_pending_failure import recover_pending_diagnostic_failure
from orfadc.agents.recover_pending_remote import recover_pending_diagnostic_remote
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_agent_diagnostic import DiagnosticSearcher


_REMOTE_FILES = {
    "netlist.scs": b"planned test netlist\n",
    "ade_e.scs": b"planned test companion\n",
    "spectre.log": b"Spectre started, then controller lost its reply.\n",
}


class FenceStore:
    def __init__(self) -> None:
        self.fences: dict[str, bytes] = {}
        self.created_count = 0
        self.lock = threading.Lock()


class IncompleteRunner:
    def __init__(self, *, mode: str = "incomplete", store: FenceStore | None = None,
                 publish_barrier: threading.Barrier | None = None) -> None:
        self.config = RemoteCadenceConfig(host="example.org", user="student")
        self.mode = mode
        self.store = store or FenceStore()
        self.publish_barrier = publish_barrier
        self.commands: list[str] = []
        self.downloads: list[str] = []
        self.hash_calls = 0
        self.lost_fence_reply = False
        self.files = dict(_REMOTE_FILES)
        if mode == "terminal_log":
            self.files["spectre.log"] = b"spectre completes with 1 error, 0 warnings.\n"

    def run_remote(self, command: list[str], **kwargs: object) -> CommandResult:
        self.commands.append(command[0])
        if command[0] == "sha256sum":
            self.hash_calls += 1
            suffix = b"changed" if self.mode == "changed" and self.hash_calls > 1 else b""
            output = "".join(
                f"{hashlib.sha256(self.files[name] + suffix).hexdigest()}  {name}\n"
                for name in _REMOTE_FILES
            )
            return CommandResult("ssh", (), 0, output, "")
        if command[0] != "bash":
            pytest.fail("quarantine issued an unexpected remote command")
        if "ORFADC_QUARANTINE_FENCE_PUBLISH_V1" in command[2]:
            if self.mode == "fence_unknown":
                return CommandResult("ssh", (), 255, "", "connection unavailable")
            if self.mode == "fence_malformed_reply":
                return CommandResult("ssh", (), 0, "created with extra text\n", "")
            if self.publish_barrier is not None:
                self.publish_barrier.wait(timeout=10)
            directory = str(kwargs["cwd"])
            proposed = base64.b64decode(command[-1], validate=True)
            with self.store.lock:
                old = self.store.fences.get(directory)
                if old is None:
                    self.store.fences[directory] = proposed
                    self.store.created_count += 1
                    outcome = "created\n"
                elif old == proposed:
                    outcome = "existing_same\n"
                else:
                    outcome = "conflict\n"
            if self.mode == "after_fence_source_change" and outcome == "created\n":
                self.files["spectre.log"] += b"changed after remote decision\n"
            if self.mode == "fence_lost_reply" and not self.lost_fence_reply:
                self.lost_fence_reply = True
                return CommandResult("ssh", (), 255, "", "reply lost after commit")
            return CommandResult("ssh", (), 0, outcome, "")
        if "ORFADC_QUARANTINE_FENCE_READ_V1" in command[2]:
            if self.mode == "fence_read_unknown":
                return CommandResult("ssh", (), 255, "", "connection unavailable")
            raw = self.store.fences.get(str(kwargs["cwd"]))
            if raw is None:
                return CommandResult("ssh", (), 7, "", "fence absent")
            if self.mode == "identity_drifts_after_fence":
                self.config = RemoteCadenceConfig(host="other.example.org", user="student")
            return CommandResult(
                "ssh", (), 0,
                f"{hashlib.sha256(raw).hexdigest()}  {module.FENCE_FILE}\n", "",
            )
        if 'target="$1"' in command[2]:
            if self.mode == "unknown":
                return CommandResult("ssh", (), 255, "", "connection unavailable")
            active = 1 if self.mode == "active" else 0
            return CommandResult(
                "ssh", (), 0,
                f"directory=present\nactive={active}\nlog=1\nsp=0\nnoise=0\n", "",
            )
        return CommandResult("ssh", (), 0, "", "")

    def download(self, source: str, destination: Path) -> CommandResult:
        name = source.rsplit("/", 1)[-1]
        self.downloads.append(name)
        if name == module.FENCE_FILE:
            destination.write_bytes(self.store.fences[source.rsplit("/", 1)[0]])
            return CommandResult("download", (), 0, "", "")
        destination.write_bytes(self.files[name])
        if self.mode == "identity_drifts_before_fence" and name == "spectre.log":
            self.config = RemoteCadenceConfig(host="other.example.org", user="student")
        if self.mode == "during_download" and name == "spectre.log":
            self.files[name] += b"remote changed\n"
        return CommandResult("download", (), 0, "", "")


def _pending(root: Path) -> tuple[Path, Path, Path]:
    runs = root / "runs"
    trace = root / "trace"
    runs.mkdir()
    trace.mkdir()
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    searcher = DiagnosticSearcher(210, 0.67)
    run_dir = None

    def dispatch(candidate, run_id):
        nonlocal run_dir
        run_dir = reserve_candidate_run(runs, spec, candidate, run_id=run_id)
        for name in ("netlist.scs", "ade_e.scs"):
            (run_dir / name).write_bytes(_REMOTE_FILES[name])
        write_json(run_dir / "candidate.json", candidate.to_dict())
        write_json(run_dir / "control_attempt" / "dispatch.json", {
            "run_id": run_id, "status": "uncertain", "returncode": 255,
        })
        raise RemoteEvaluationUncertain("lost controller reply")

    with pytest.raises(RemoteEvaluationUncertain):
        execute_manager_planned(
            Manager(searcher=searcher, max_searches=1, max_evaluations=1),
            spec, dispatch, trace, seed=0,
            remote_config=RemoteCadenceConfig(host="example.org", user="student"),
        )
    assert run_dir is not None
    audit = inspect_journal(trace)
    write_json(trace / "agent_evaluation.json", {
        "execution_status": "pending_remote_evaluation", "spec_id": "S1", "seed": 0,
        "candidate_id": audit.pending_candidate_id, "candidate_run_id": audit.pending_run_id,
        "candidate_run_relative": f"S1/seed0/{audit.pending_candidate_id}/{audit.pending_run_id}",
        "not_lna_result": True, "spec_pass": None,
    })
    return trace, runs, run_dir


@pytest.fixture
def private_root():
    with tempfile.TemporaryDirectory(prefix="quarantine_test_", dir=_PRIVATE_ROOT.resolve()) as name:
        yield Path(name)


@pytest.fixture(autouse=True)
def no_observation_wait(monkeypatch: pytest.MonkeyPatch):
    from orfadc.agents import recover_pending_failure
    monkeypatch.setattr(recover_pending_failure.time, "sleep", lambda _: None)


def test_quarantine_is_durable_idempotent_and_keeps_original_pending(private_root: Path) -> None:
    trace, runs, run_dir = _pending(private_root)
    runner = IncompleteRunner()
    journal_before = (trace / "agent_events.jsonl").read_bytes()
    report = module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert report["status"] == "quarantined_pending_incomplete"
    assert report["budget_disposition"] == "dispatched_outcome_unknown"
    assert report["safe_to_dispatch"] is False and report["safe_to_reconcile"] is False
    assert report["new_run_authorized"] is False and report["spec_pass"] is None
    assert len(report["remote_hash_snapshots"]) == 2
    assert report["remote_probe_before"]["spectre_active"] is False
    assert runner.downloads == [*list(_REMOTE_FILES), module.FENCE_FILE]
    assert "spectre" not in runner.commands
    assert module.audit_pending_quarantine(trace, runs) == report
    assert module.quarantine_incomplete_diagnostic(trace, runs, runner) == report
    assert runner.downloads == [*list(_REMOTE_FILES), module.FENCE_FILE]  # Local retry only.
    assert runner.store.created_count == 1
    assert module.verify_remote_pending_quarantine(trace, runs, runner) == report
    assert runner.downloads == [*list(_REMOTE_FILES), module.FENCE_FILE]
    changed_endpoint = IncompleteRunner()
    changed_endpoint.config = RemoteCadenceConfig(host="other.example.org", user="student")
    with pytest.raises(ValueError, match="endpoint differs"):
        module.quarantine_incomplete_diagnostic(trace, runs, changed_endpoint)
    assert (trace / "agent_events.jsonl").read_bytes() == journal_before
    assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
    assert not (run_dir / "metrics.json").exists()
    assert not (run_dir / "evidence_manifest.json").exists()
    assert not (trace / "agent_trace.json").exists()
    assert not (trace / "agent_reconciliation.json").exists()
    with pytest.raises(ValueError, match="quarantined"):
        module.require_not_quarantined(trace)


@pytest.mark.parametrize("mode", [
    "unknown", "active", "changed", "during_download", "terminal_log", "wrong_identity",
    "fence_unknown", "fence_malformed_reply", "fence_read_unknown",
    "after_fence_source_change",
    "identity_drifts_before_fence", "identity_drifts_after_fence",
])
def test_quarantine_rejects_unverified_remote(private_root: Path, mode: str) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner(mode=mode)
    if mode == "wrong_identity":
        runner.config = RemoteCadenceConfig(host="other.example.org", user="student")
    with pytest.raises(ValueError):
        module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert not (trace / module.QUARANTINE_FILE).exists()
    assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


def test_two_independent_controller_roots_share_one_remote_decision(private_root: Path) -> None:
    first_root = private_root / "host_a"
    first_root.mkdir()
    first_trace, first_runs, _ = _pending(first_root)
    second_root = private_root / "host_b"
    shutil.copytree(first_root, second_root)
    second_trace, second_runs = second_root / "trace", second_root / "runs"
    store = FenceStore()
    barrier = threading.Barrier(2)
    first_runner = IncompleteRunner(store=store, publish_barrier=barrier)
    second_runner = IncompleteRunner(store=store, publish_barrier=barrier)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(module.quarantine_incomplete_diagnostic,
                            first_trace, first_runs, first_runner)
        second = pool.submit(module.quarantine_incomplete_diagnostic,
                             second_trace, second_runs, second_runner)
        reports = [first.result(timeout=20), second.result(timeout=20)]
    assert store.created_count == 1
    assert {report["remote_fence_publish_status"] for report in reports} == {
        "created", "existing_same",
    }
    assert reports[0]["remote_fence_sha256"] == reports[1]["remote_fence_sha256"]
    assert module.verify_remote_pending_quarantine(first_trace, first_runs, first_runner) == reports[0]
    assert module.verify_remote_pending_quarantine(second_trace, second_runs, second_runner) == reports[1]
    assert inspect_journal(first_trace).disposition == "reconcile_pending_evaluation"
    assert inspect_journal(second_trace).disposition == "reconcile_pending_evaluation"


def test_competing_trace_identity_cannot_replace_remote_decision(private_root: Path) -> None:
    first_root = private_root / "host_a"
    first_root.mkdir()
    first_trace, first_runs, _ = _pending(first_root)
    second_root = private_root / "host_b"
    shutil.copytree(first_root, second_root)
    second_trace = second_root / "different_trace"
    (second_root / "trace").rename(second_trace)
    store = FenceStore()
    module.quarantine_incomplete_diagnostic(first_trace, first_runs, IncompleteRunner(store=store))
    with pytest.raises(ValueError, match="fence is unknown or conflicts"):
        module.quarantine_incomplete_diagnostic(
            second_trace, second_root / "runs", IncompleteRunner(store=store),
        )
    assert store.created_count == 1
    assert not (second_trace / module.QUARANTINE_FILE).exists()
    assert inspect_journal(second_trace).disposition == "reconcile_pending_evaluation"


def test_two_hosts_racing_different_decisions_only_one_wins(private_root: Path) -> None:
    first_root = private_root / "host_a"
    first_root.mkdir()
    first_trace, first_runs, _ = _pending(first_root)
    second_root = private_root / "host_b"
    shutil.copytree(first_root, second_root)
    second_trace = second_root / "different_trace"
    (second_root / "trace").rename(second_trace)
    store = FenceStore()
    barrier = threading.Barrier(2)
    runners = [
        IncompleteRunner(store=store, publish_barrier=barrier),
        IncompleteRunner(store=store, publish_barrier=barrier),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(module.quarantine_incomplete_diagnostic, first_trace, first_runs, runners[0]),
            pool.submit(module.quarantine_incomplete_diagnostic,
                        second_trace, second_root / "runs", runners[1]),
        ]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=20))
            except ValueError as exc:
                outcomes.append(str(exc))
    assert store.created_count == 1
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum("fence is unknown or conflicts" in item for item in outcomes if isinstance(item, str)) == 1
    assert sum((path / module.QUARANTINE_FILE).exists()
               for path in (first_trace, second_trace)) == 1
    assert inspect_journal(first_trace).disposition == "reconcile_pending_evaluation"
    assert inspect_journal(second_trace).disposition == "reconcile_pending_evaluation"


def test_lost_fence_reply_restarts_from_same_remote_decision(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner(mode="fence_lost_reply")
    with pytest.raises(ValueError, match="fence is unknown"):
        module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert runner.store.created_count == 1
    assert not (trace / module.QUARANTINE_FILE).exists()
    report = module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert report["remote_fence_publish_status"] == "existing_same"
    assert runner.store.created_count == 1
    assert module.verify_remote_pending_quarantine(trace, runs, runner) == report


def test_remote_fence_tamper_rejected_by_online_audit(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner()
    report = module.quarantine_incomplete_diagnostic(trace, runs, runner)
    directory = next(iter(runner.store.fences))
    runner.store.fences[directory] = b"changed remote decision\n"
    assert module.audit_pending_quarantine(trace, runs) == report
    with pytest.raises(ValueError, match="remote quarantine fence changed"):
        module.verify_remote_pending_quarantine(trace, runs, runner)


def test_changed_source_after_remote_commit_stays_pending(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner(mode="after_fence_source_change")
    with pytest.raises(ValueError, match="changed after fence publication"):
        module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert runner.store.created_count == 1
    assert not (trace / module.QUARANTINE_FILE).exists()
    with pytest.raises(ValueError, match="fence is unknown or conflicts"):
        module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


@pytest.mark.parametrize("mutation", [
    "journal", "index", "candidate", "staged_log", "staged_fence", "source", "report",
    "fence_hash",
    "observations",
])
def test_quarantine_audit_rejects_changed_evidence(private_root: Path, mutation: str) -> None:
    trace, runs, run_dir = _pending(private_root)
    report = module.quarantine_incomplete_diagnostic(trace, runs, IncompleteRunner())
    stage = run_dir / report["staging_dir"] / report["run_id"]
    targets = {
        "journal": trace / "agent_events.jsonl",
        "index": trace / "agent_evaluation.json",
        "candidate": run_dir / "candidate.json",
        "staged_log": stage / "spectre.log",
        "staged_fence": stage / module.FENCE_FILE,
        "source": run_dir / "netlist.scs",
        "report": trace / module.QUARANTINE_FILE,
        "fence_hash": trace / module.QUARANTINE_FILE,
        "observations": trace / module.QUARANTINE_FILE,
    }
    target = targets[mutation]
    if mutation in {"report", "observations", "fence_hash"}:
        saved = json.loads(target.read_text(encoding="ascii"))
        if mutation == "report":
            saved["safe_to_dispatch"] = True
        else:
            if mutation == "observations":
                saved["remote_probe_after"]["spectre_active"] = True
            else:
                saved["remote_fence_sha256"] = "0" * 64
        target.write_text(json.dumps(saved), encoding="ascii")
    else:
        target.write_bytes(target.read_bytes() + b"changed\n")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        module.audit_pending_quarantine(trace, runs)


def test_quarantine_rejects_local_lock_contention(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    with agent_run_lock(trace):
        with pytest.raises(RuntimeError, match="already owned"):
            module.quarantine_incomplete_diagnostic(trace, runs, IncompleteRunner())
    assert not (trace / module.QUARANTINE_FILE).exists()


def test_cli_requires_explicit_remote_metadata_write(
    private_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, _, _ = _pending(private_root)
    monkeypatch.setattr(sys, "argv", ["quarantine_pending", "--trace-dir", str(trace)])
    with pytest.raises(SystemExit) as stopped:
        module.main()
    assert stopped.value.code == 2
    assert not (trace / module.QUARANTINE_FILE).exists()


def test_quarantine_rejects_other_local_controller_process(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    marker = private_root / "other_controller_holds_lock"
    script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from orfadc.agents.run_lock import agent_run_lock\n"
        "with agent_run_lock(Path(sys.argv[1])):\n"
        "    Path(sys.argv[2]).write_text('held', encoding='ascii')\n"
        "    time.sleep(10)\n"
    )
    environment = dict(os.environ, PYTHONPATH="src")
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(trace), str(marker)],
        cwd=Path.cwd(), env=environment, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.is_file(), child.stderr.read() if child.poll() is not None else "lock timeout"
        with pytest.raises(RuntimeError, match="already owned"):
            module.quarantine_incomplete_diagnostic(trace, runs, IncompleteRunner())
        assert not (trace / module.QUARANTINE_FILE).exists()
    finally:
        child.terminate()
        child.communicate(timeout=5)


def test_quarantine_restart_before_and_after_publication(
    private_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner()
    original_commit = module._commit_new
    with monkeypatch.context() as context:
        context.setattr(module, "_commit_new", lambda *_: (_ for _ in ()).throw(OSError("injected")))
        with pytest.raises(OSError, match="injected"):
            module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert not (trace / module.QUARANTINE_FILE).exists()
    assert module._commit_new is original_commit
    original_audit = module.audit_pending_quarantine
    with monkeypatch.context() as context:
        context.setattr(module, "audit_pending_quarantine", lambda *_: (_ for _ in ()).throw(OSError("after publish")))
        with pytest.raises(OSError, match="after publish"):
            module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert (trace / module.QUARANTINE_FILE).is_file()
    assert module.audit_pending_quarantine is original_audit
    report = module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert report["status"] == "quarantined_pending_incomplete"


def test_quarantine_preserves_untrusted_local_source(private_root: Path) -> None:
    trace, runs, run_dir = _pending(private_root)
    (run_dir / "netlist.scs").write_bytes(b"different input\n")
    with pytest.raises(ValueError, match="differs from planned local inputs"):
        module.quarantine_incomplete_diagnostic(trace, runs, IncompleteRunner())
    assert not (trace / module.QUARANTINE_FILE).exists()


def test_quarantine_rejects_local_evidence_changed_mid_observation(private_root: Path) -> None:
    trace, runs, _ = _pending(private_root)
    runner = IncompleteRunner()
    original_download = runner.download

    def changed_download(source: str, destination: Path) -> CommandResult:
        result = original_download(source, destination)
        if source.endswith("spectre.log"):
            pending = trace / "agent_evaluation.json"
            pending.write_bytes(pending.read_bytes() + b" \n")
        return result

    runner.download = changed_download
    with pytest.raises(ValueError, match="local pending evidence changed"):
        module.quarantine_incomplete_diagnostic(trace, runs, runner)
    assert not (trace / module.QUARANTINE_FILE).exists()


def test_existing_recovery_entrypoints_refuse_quarantine(private_root: Path) -> None:
    trace, runs, run_dir = _pending(private_root)
    runner = IncompleteRunner()
    module.quarantine_incomplete_diagnostic(trace, runs, runner)
    template = run_dir / "netlist.scs"
    template_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    with pytest.raises(ValueError, match="quarantined"):
        recover_pending_diagnostic_failure(
            trace, runs, runner, template=template, template_sha256=template_hash,
        )
    with pytest.raises(ValueError, match="quarantined"):
        recover_pending_diagnostic_remote(
            trace, runs, runner, template=template, template_sha256=template_hash,
        )
    with pytest.raises(ValueError, match="quarantined"):
        reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=template, template_sha256=template_hash,
        )
    assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
    assert runner.downloads == [*list(_REMOTE_FILES), module.FENCE_FILE]
