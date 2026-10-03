from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.agents import recover_pending_remote as module
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.diagnostic_feedback import DiagnosticFeedbackRefiner, DiagnosticFeedbackSearcher
from orfadc.agents.reconcile_pending_feedback import reconcile_pending_feedback
from orfadc.agents.finalize_feedback_trace import finalize_feedback_trace
from orfadc.agents.reconcile_pending import reconcile_pending_diagnostic
from orfadc.agents.remote_identity import write_remote_identity_snapshot
from orfadc.agents.spec_snapshots import write_spec_snapshot
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.config_loader import load_specs
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_agent_diagnostic import DiagnosticSearcher
from orfadc.experiments import run_agent_diagnostic as agent_module
from orfadc.schemas import Candidate


_SOURCE = _PRIVATE_ROOT / "S1/seed0/S1_seed0_oa_diag/20260927T081306Z_57cfbd7e"
_TEMPLATE = _PRIVATE_ROOT / "lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"
_TEMPLATE_SHA = "9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814"
_FEEDBACK_FIRST = _PRIVATE_ROOT / "S1/seed0/S1_seed0_oa_feedback0/20260927T165301Z_0be1bd66"
_FEEDBACK_SECOND = _PRIVATE_ROOT / "S1/seed0/S1_seed0_oa_feedback1/20260927T165307Z_f9d006ba"


class ArchiveRunner:
    def __init__(self, *, corrupt: bool = False, marker: bool = True, source: Path = _SOURCE) -> None:
        self.config = RemoteCadenceConfig(host="example.org", user="student")
        self.corrupt = corrupt
        self.marker = marker
        self.source = source
        self.commands: list[list[str]] = []
        self.downloads: list[str] = []

    def run_remote(self, command: list[str], **_: object) -> CommandResult:
        self.commands.append(command)
        if command[0] not in {"bash", "grep"}:
            pytest.fail("recovery attempted an unexpected remote command")
        return CommandResult("ssh", (), 0 if command[0] == "bash" or self.marker else 1, "", "")

    def download(self, source: str, destination: Path) -> CommandResult:
        name = source.rsplit("/", 1)[-1]
        relative = "psf/" + name if "/psf/" in source else name
        self.downloads.append(relative)
        shutil.copyfile(self.source / relative, destination)
        if self.corrupt and relative == "psf/sp.sp":
            destination.write_bytes(destination.read_bytes() + b"changed")
        return CommandResult("download", (), 0, "", "")


def _pending(trace_dir: Path, config: RemoteCadenceConfig) -> None:
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    manager = Manager(searcher=DiagnosticSearcher(210, 0.67))
    manager.enable_journal(trace_dir)
    try:
        manager.context = (spec.id, 0)
        spec_digest = write_spec_snapshot(trace_dir, spec)
        remote_digest = write_remote_identity_snapshot(trace_dir, config)
        manager._record(
            "RunStarted", spec_id=spec.id, seed=0, max_searches=1, max_evaluations=1,
            spec_sha256=spec_digest, dispatch_mode="planned",
            remote_identity_sha256=remote_digest,
        )
        manager.search_candidates(spec)
        manager.pop_candidate(run_id=_SOURCE.name)
    finally:
        manager.close_journal()


def _setup() -> tuple[tempfile.TemporaryDirectory[str], Path, Path, ArchiveRunner]:
    if not _SOURCE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private source archive for recovery test is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="recovery_test_", dir=_PRIVATE_ROOT.resolve())
    root = Path(temporary.name)
    trace = root / "trace"
    runs = root / "runs"
    trace.mkdir()
    runs.mkdir()
    runner = ArchiveRunner()
    _pending(trace, runner.config)
    return temporary, trace, runs, runner


def _hashes() -> dict[str, str]:
    return {name: hashlib.sha256((_SOURCE / name).read_bytes()).hexdigest()
            for name in module._RECOVERY_FILES}


def _feedback_pending() -> tuple[tempfile.TemporaryDirectory[str], Path, Path, ArchiveRunner]:
    if any(not source.is_dir() for source in (_FEEDBACK_FIRST, _FEEDBACK_SECOND)) or not _TEMPLATE.is_file():
        pytest.skip("private two-round Cadence feedback source archives are unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="feedback_recovery_", dir=_PRIVATE_ROOT.resolve())
    root = Path(temporary.name)
    trace = root / "trace"
    runs = root / "runs"
    trace.mkdir()
    runs.mkdir()
    first_archive = runs / "S1" / "seed0" / "S1_seed0_oa_feedback0" / _FEEDBACK_FIRST.name
    shutil.copytree(_FEEDBACK_FIRST, first_archive)
    runner = ArchiveRunner(source=_FEEDBACK_SECOND)
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    refiner = DiagnosticFeedbackRefiner(template=_TEMPLATE, template_sha256=_TEMPLATE_SHA)
    manager = Manager(
        searcher=DiagnosticFeedbackSearcher(refiner, rd_ohm=250, vbias_v=0.67),
        refiner=refiner, max_searches=2, max_evaluations=2,
    )
    manager.enable_journal(trace)
    try:
        manager.context = (spec.id, 0)
        spec_digest = write_spec_snapshot(trace, spec)
        remote_digest = write_remote_identity_snapshot(trace, runner.config)
        manager._record(
            "RunStarted", spec_id=spec.id, seed=0,
            max_searches=2, max_evaluations=2,
            spec_sha256=spec_digest, dispatch_mode="planned",
            remote_identity_sha256=remote_digest,
        )
        manager.search_candidates(spec)
        first = manager.pop_candidate(run_id=_FEEDBACK_FIRST.name)
        assert manager.record_result(first, first_archive, spec).status == "diagnostic_refinement_proposed"
        manager.search_candidates(spec)
        manager.pop_candidate(run_id=_FEEDBACK_SECOND.name)
    finally:
        manager.close_journal()
    assert inspect_journal(trace, candidate_runs_root=runs).disposition == "reconcile_pending_evaluation"
    return temporary, trace, runs, runner


def test_feedback_second_remote_recovery_and_local_reconciliation_without_spectre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _feedback_pending()
    with temporary:
        hashes = {name: hashlib.sha256((_FEEDBACK_SECOND / name).read_bytes()).hexdigest()
                  for name in module._RECOVERY_FILES}
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": hashes,
        })
        archive, recovered = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            feedback_second=True,
        )
        assert recovered["status"] == "recovered_raw_audited"
        assert recovered["spectre_dispatched_by_recovery"] is False
        assert archive.name == _FEEDBACK_SECOND.name
        assert len(runner.downloads) == len(module._RECOVERY_FILES)
        assert [command[0] for command in runner.commands] == ["bash", "grep"]
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "reconcile_pending_evaluation"
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        report = reconcile_pending_feedback(
            trace, runs, spec, seed=0, template=_TEMPLATE,
            template_sha256=_TEMPLATE_SHA, specs_path=Path("config/specs_table_iii.yaml"),
        )
        assert report["status"] == "reconciled_existing_second_feedback_archive"
        assert report["spectre_dispatched_by_reconciliation"] is False
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"
        assert not (archive / "spectre.stdout.log").exists()


def test_feedback_remote_recovery_rejects_changed_first_source_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _feedback_pending()
    with temporary:
        first = runs / "S1" / "seed0" / "S1_seed0_oa_feedback0" / _FEEDBACK_FIRST.name
        with (first / "metrics.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        before = (trace / "agent_events.jsonl").read_bytes()
        with pytest.raises(ValueError, match="hash or size mismatch"):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
                feedback_second=True,
            )
        assert runner.commands == [] and runner.downloads == []
        assert (trace / "agent_events.jsonl").read_bytes() == before


def test_feedback_remote_recovery_rejects_missing_clean_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _feedback_pending()
    with temporary:
        runner.marker = False
        hashes = {name: hashlib.sha256((_FEEDBACK_SECOND / name).read_bytes()).hexdigest()
                  for name in module._RECOVERY_FILES}
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": hashes,
        })
        before = (trace / "agent_events.jsonl").read_bytes()
        with pytest.raises(ValueError, match="completion marker"):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
                feedback_second=True,
            )
        assert runner.downloads == []
        assert (trace / "agent_events.jsonl").read_bytes() == before
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "reconcile_pending_evaluation"


def test_real_feedback_sources_finalize_second_refinement_without_spectre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _feedback_pending()
    with temporary:
        hashes = {name: hashlib.sha256((_FEEDBACK_SECOND / name).read_bytes()).hexdigest()
                  for name in module._RECOVERY_FILES}
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": hashes,
        })
        archive, _ = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            feedback_second=True,
        )
        events = [json.loads(line) for line in (trace / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        candidate = Candidate(**json.loads((trace / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()[1])["candidates"][0])
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        manager = Manager(max_searches=2, max_evaluations=2)
        manager.context = (spec.id, 0)
        manager.searches_used = manager.evaluations_used = 2
        manager.seen_ids = {"S1_seed0_oa_feedback0", candidate.candidate_id}
        manager.pending = {candidate.candidate_id: candidate}
        manager.pending_run_ids = {candidate.candidate_id: archive.name}
        manager.trace = events
        manager.attach_journal_for_resume(trace)
        try:
            assert manager.record_result(candidate, archive, spec).status == "needs_evaluation"
        finally:
            manager.close_journal()
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "interrupted"
        report = finalize_feedback_trace(
            trace, runs, spec, seed=0, template=_TEMPLATE,
            template_sha256=_TEMPLATE_SHA, specs_path=Path("config/specs_table_iii.yaml"),
        )
        assert report["spectre_dispatched_by_recovery"] is False
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"
        assert len(runner.downloads) == len(module._RECOVERY_FILES)


def test_recovery_downloads_raw_and_reconciles_without_spectre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        archive, report = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert report["status"] == "recovered_raw_audited"
        assert report["points"] == 47 and report["spec_pass"] is None
        assert len(runner.downloads) == 6
        assert [item[0] for item in runner.commands] == ["bash", "grep"]
        assert not (archive / "spectre.stdout.log").exists()
        assert not (archive / "spectre.stderr.log").exists()
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        reconciled = reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert reconciled["recovery_mode"] == "remote_quiescent_download_v1"
        assert reconciled["spectre_dispatched_by_reconciliation"] is False
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"


def test_recovery_accepts_planned_uncertain_control_attempt_without_redispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        candidate_run = runs / "S1" / "seed0" / "S1_seed0_oa_diag" / _SOURCE.name
        candidate_run.mkdir(parents=True)
        for name in ("netlist.scs", "ade_e.scs", "candidate.json"):
            shutil.copyfile(_SOURCE / name, candidate_run / name)
        control = candidate_run / "control_attempt"
        control.mkdir()
        (control / "spectre.stderr.log").write_text("controller timed out\n", encoding="ascii")
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        archive, report = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert archive == candidate_run
        assert report["spectre_dispatched_by_recovery"] is False
        assert (control / "spectre.stderr.log").read_text() == "controller timed out\n"
        assert not (archive / "spectre.stderr.log").exists()
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        reconciled = reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert reconciled["spectre_dispatched_by_reconciliation"] is False
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"


def test_real_agent_pending_index_recovers_and_reconciles_without_redispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SOURCE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private source archive for recovery test is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="agent_pending_recovery_", dir=_PRIVATE_ROOT.resolve())
    with temporary:
        root = Path(temporary.name)
        runs = root / "runs"
        runs.mkdir()
        runner = ArchiveRunner()
        monkeypatch.setattr(agent_module, "available_physical_memory_gb", lambda: 5.0)
        monkeypatch.setattr(agent_module, "load_remote_config", lambda _: runner.config)
        calls: list[str] = []

        def uncertain_backend(config_path, runs_root, spec, candidate, **kwargs):
            assert kwargs["preserve_uncertain_dispatch"] is True
            calls.append(kwargs["run_id"])
            run_dir = runs_root / spec.id / f"seed{candidate.seed}" / candidate.candidate_id / kwargs["run_id"]
            run_dir.mkdir(parents=True)
            for name in ("netlist.scs", "ade_e.scs", "candidate.json"):
                shutil.copyfile(_SOURCE / name, run_dir / name)
            control = run_dir / "control_attempt"
            control.mkdir()
            (control / "spectre.stderr.log").write_text("SSH timeout\n", encoding="ascii")
            raise RemoteEvaluationUncertain("remote dispatch outcome is uncertain")

        monkeypatch.setattr(agent_module, "run_active_diagnostic_candidate", uncertain_backend)
        trace, index = agent_module.run_diagnostic_agent(
            root / "unused_config", Path("config/specs_table_iii.yaml"), runs, root / "agent",
            template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            spec_id="S1", seed=0, rd_ohm=210, vbias_v=0.67,
        )
        assert index["execution_status"] == "pending_remote_evaluation"
        assert calls == [index["candidate_run_id"]]
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        archive, _ = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        pending_path = trace / "agent_evaluation.json"
        original = pending_path.read_bytes()
        tampered = json.loads(original)
        tampered["candidate_run_id"] = "different_run"
        pending_path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(ValueError, match="snapshot differs"):
            reconcile_pending_diagnostic(
                trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        pending_path.write_bytes(original)
        report = reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert report["spectre_dispatched_by_reconciliation"] is False
        assert report["refiner_status"] == "needs_evaluation"
        assert len(calls) == 1
        assert (archive / "control_attempt/spectre.stderr.log").read_text() == "SSH timeout\n"
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"


@pytest.mark.parametrize("failure", ["download_corrupt", "no_marker", "identity_changed"])
def test_recovery_rejects_uncertain_inputs_without_journal_changes(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        before = (trace / "agent_events.jsonl").read_bytes()
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        if failure == "download_corrupt":
            runner.corrupt = True
        elif failure == "no_marker":
            runner.marker = False
        else:
            runner.config = RemoteCadenceConfig(host="changed.example.org", user="student")
        with pytest.raises(ValueError):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert (trace / "agent_events.jsonl").read_bytes() == before
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        if failure == "identity_changed":
            assert runner.commands == [] and runner.downloads == []


def test_reconcile_rejects_rehashed_recovery_with_wrong_trace_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        archive, _ = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        provenance_path = archive / "recovery_provenance.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["trace_id"] = "other_trace"
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        metrics_path = archive / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["recovery_provenance_sha256"] = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        manifest_path = archive / "evidence_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = {key: entry["path"] for key, entry in manifest["artifacts"].items()}
        manifest_path.write_text(json.dumps(build_evidence_manifest(archive, artifacts)), encoding="utf-8")
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        with pytest.raises(ValueError, match="planned dispatch"):
            reconcile_pending_diagnostic(
                trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


@pytest.mark.parametrize("published_before_fault", [3, 10])
def test_recovery_resumes_atomic_partial_publication_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, published_before_fault: int,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        original = module._publish_without_replacing
        published = 0

        def interrupt(source: Path, target: Path, expected_sha256: str) -> None:
            nonlocal published
            if published == published_before_fault:
                raise KeyboardInterrupt()
            original(source, target, expected_sha256)
            published += 1

        monkeypatch.setattr(module, "_publish_without_replacing", interrupt)
        with pytest.raises(KeyboardInterrupt):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        archive = runs / "S1/seed0/S1_seed0_oa_diag" / _SOURCE.name
        assert not (archive / "evidence_manifest.json").exists()
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        existing = {name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
                    for name in module._EVIDENCE_ARTIFACTS.values()
                    if (archive / name).exists()}
        assert len(existing) == published_before_fault
        monkeypatch.setattr(module, "_publish_without_replacing", original)
        recovered, report = module.recover_pending_diagnostic_remote(
            trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert recovered == archive and report["points"] == 47
        assert all(hashlib.sha256((archive / name).read_bytes()).hexdigest() == digest
                   for name, digest in existing.items())
        assert len(runner.downloads) == 12
        assert [command[0] for command in runner.commands] == ["bash", "grep", "bash", "grep"]
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


def test_recovery_refuses_modified_partial_archive_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        original = module._publish_without_replacing
        published = 0

        def interrupt(source: Path, target: Path, expected_sha256: str) -> None:
            nonlocal published
            if published == 8:
                raise KeyboardInterrupt()
            original(source, target, expected_sha256)
            published += 1

        monkeypatch.setattr(module, "_publish_without_replacing", interrupt)
        with pytest.raises(KeyboardInterrupt):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        archive = runs / "S1/seed0/S1_seed0_oa_diag" / _SOURCE.name
        altered = archive / "psf/sp.sp"
        altered.write_bytes(altered.read_bytes() + b"\nmodified\n")
        before = altered.read_bytes()
        monkeypatch.setattr(module, "_publish_without_replacing", original)
        with pytest.raises(ValueError, match="existing recovery target differs"):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert altered.read_bytes() == before
        assert not (archive / "evidence_manifest.json").exists()
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"


def test_post_manifest_interruption_reconciles_existing_archive_without_redownload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        original = module.audit_active_diagnostic_candidate
        audits = 0

        def interrupt_final_audit(*args: object, **kwargs: object) -> dict:
            nonlocal audits
            audits += 1
            if audits == 2:
                raise KeyboardInterrupt()
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "audit_active_diagnostic_candidate", interrupt_final_audit)
        with pytest.raises(KeyboardInterrupt):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        archive = runs / "S1/seed0/S1_seed0_oa_diag" / _SOURCE.name
        assert (archive / "evidence_manifest.json").is_file()
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
        before_downloads = len(runner.downloads)
        spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
        report = reconcile_pending_diagnostic(
            trace, runs, spec, seed=0, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
        )
        assert report["recovery_mode"] == "remote_quiescent_download_v1"
        assert len(runner.downloads) == before_downloads == 6
        assert inspect_journal(trace, candidate_runs_root=runs).disposition == "complete"


def test_recovery_rejects_obstructed_psf_parent_before_any_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary, trace, runs, runner = _setup()
    with temporary:
        monkeypatch.setattr(module, "snapshot_remote_diagnostic_artifacts", lambda *_: {
            "status": "stable_unverified", "artifacts_sha256": _hashes(),
        })
        archive = runs / "S1/seed0/S1_seed0_oa_diag" / _SOURCE.name
        archive.mkdir(parents=True)
        (archive / "psf").write_text("occupied", encoding="ascii")
        with pytest.raises(ValueError, match="parent is not a directory"):
            module.recover_pending_diagnostic_remote(
                trace, runs, runner, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA,
            )
        assert not (archive / "metrics.json").exists()
        assert not (archive / "netlist.scs").exists()
        assert inspect_journal(trace).disposition == "reconcile_pending_evaluation"
