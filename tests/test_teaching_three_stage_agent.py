from pathlib import Path
import json
import shutil
from unittest.mock import Mock

import pytest

from orfadc.agents.journal import inspect_journal
from orfadc.agents.teaching_three_stage_feedback import (
    TeachingThreeStageRefiner, TeachingThreeStageSearcher,
)
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.cadence.remote_runner import CommandResult, RemoteRunner
from orfadc.config_loader import load_specs
from orfadc.config_loader import write_json
from orfadc.experiments import run_teaching_three_stage_feedback_agent as module
from orfadc.agents import reconcile_pending_teaching_three_stage as reconcile_module
from orfadc.experiments.probe_teaching_three_stage_agent_lost_reply import NthReplySuppressedRunner
from orfadc.schemas import Spec


_ROOT = Path("results/runs/teaching_three_stage_candidates")
_FIRST = _ROOT / "S1/seed0/S1_seed0_teach3_l3s2/20260927T180217Z_33e94f02"
_FULL = Path("results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba")
_RECOVERED_SECOND = (
    _ROOT / "S1/seed0/S1_seed0_teach3_resonance/20260927T184753Z_11f2efbe"
)


def _spec() -> Spec:
    return next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_specs", lambda path: [_spec()])
    monkeypatch.setattr(module, "load_remote_config", lambda path: RemoteCadenceConfig(
        host="example.invalid", user="test", remote_root="/tmp/three_stage_agent",
    ))
    root = tmp_path / "runs"
    root.mkdir()
    return root


def test_searcher_refiner_uses_real_raw_parent_for_one_bounded_proposal() -> None:
    if not _FIRST.is_dir():
        pytest.skip("private first three-stage Spectre source is unavailable")
    refiner = TeachingThreeStageRefiner(_ROOT)
    searcher = TeachingThreeStageSearcher(refiner)
    first = searcher.initial_candidate(_spec(), 0)
    assert searcher.search_calls == 0
    assert searcher.search(_spec(), 0)[0].to_dict() == first.to_dict()
    refined = refiner.refine_from_run(first, _FIRST, _spec())
    assert refined.status == "teaching_refinement_proposed"
    proposed = searcher.search(_spec(), 0)
    assert len(proposed) == 1
    assert proposed[0].passive_params == {
        "output_tune_ff": 0.0, "output_secondary_nh": 4.085532,
    }
    assert refiner.parent_manifest_sha256 is not None
    assert searcher.search(_spec(), 0) == []


def test_uncertain_first_dispatch_keeps_planned_journal_without_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _prepare(tmp_path, monkeypatch)
    calls = []

    def uncertain(config, runs_root, spec, candidate, **kwargs):
        calls.append((candidate.candidate_id, kwargs["run_id"]))
        raise RemoteEvaluationUncertain("controller response lost")

    monkeypatch.setattr(module, "run_teaching_three_stage_candidate", uncertain)
    trace_dir, report = module.run_teaching_three_stage_feedback_agent(
        tmp_path / "config", tmp_path / "specs", root, root / "traces",
    )
    assert len(calls) == 1
    assert report["status"] == "pending_remote_evaluation"
    assert report["pending_run_id"] == calls[0][1]
    assert report["safe_to_retry"] is False and report["spec_pass"] is None
    assert not (trace_dir / "agent_trace.json").exists()
    assert not (trace_dir / "feedback_summary.json").exists()
    journal = inspect_journal(trace_dir, candidate_runs_root=root)
    assert journal.disposition == "reconcile_pending_evaluation"
    assert journal.spec_verified and journal.candidate_snapshots_verified
    assert journal.remote_identity_verified


def test_definite_first_backend_error_stays_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _prepare(tmp_path, monkeypatch)
    calls = []

    def failed(config, runs_root, spec, candidate, **kwargs):
        calls.append(kwargs["run_id"])
        raise RuntimeError("definite backend failure")

    monkeypatch.setattr(module, "run_teaching_three_stage_candidate", failed)
    trace_dir, report = module.run_teaching_three_stage_feedback_agent(
        tmp_path / "config", tmp_path / "specs", root, root / "traces",
    )
    assert len(calls) == 1
    assert report["status"] == "teaching_agent_incomplete"
    assert report["evaluations_used"] == 1
    assert not (trace_dir / "feedback_summary.json").exists()
    assert inspect_journal(trace_dir, candidate_runs_root=root).disposition == "complete"


def _pending_copy(tmp_path: Path, rounds: int) -> tuple[Path, dict]:
    if not _FULL.is_dir():
        pytest.skip("private two-round three-stage Spectre trace is unavailable")
    trace = tmp_path / f"pending_round_{rounds}"
    shutil.copytree(_FULL, trace)
    (trace / "agent_trace.json").unlink()
    (trace / "feedback_summary.json").unlink()
    events = (trace / "agent_events.jsonl").read_text(encoding="utf-8").splitlines()
    (trace / "agent_events.jsonl").write_text(
        "\n".join(events[:3 if rounds == 1 else 6]) + "\n", encoding="utf-8",
    )
    if rounds == 1:
        snapshots = (trace / "agent_candidates.jsonl").read_bytes().splitlines(keepends=True)
        (trace / "agent_candidates.jsonl").write_bytes(snapshots[0])
    journal = inspect_journal(trace, candidate_runs_root=_ROOT)
    assert journal.disposition == "reconcile_pending_evaluation"
    pending = reconcile_module._pending_report(trace, journal, _spec(), 0)
    write_json(trace / "feedback_pending.json", pending)
    return trace, pending


def test_second_pending_adopts_real_archive_without_remote_dispatch(tmp_path: Path) -> None:
    trace, pending = _pending_copy(tmp_path, 2)
    config = Path("config/remote_cadence.local.yaml")
    if not config.is_file():
        pytest.skip("private Cadence connection config is unavailable")
    runner = Mock()
    runner.config = reconcile_module.load_remote_config(config)
    report = reconcile_module.reconcile_pending_teaching_three_stage(
        trace, _ROOT, _spec(), seed=0, config_path=config,
        specs_path=Path("config/specs_table_iii.yaml"), runner=runner,
    )
    assert report["status"] == "reconciled_existing_second_archive"
    assert report["adopted_run_id"] == pending["pending_run_id"]
    assert report["adopted_run_redispatched"] is False
    runner.run_remote.assert_not_called()
    assert reconcile_module.audit_teaching_three_stage_agent_feedback(trace, _ROOT, _spec())[
        "status"
    ] == "verified_two_run_teaching_agent_feedback"
    with pytest.raises(ValueError, match="not an eligible"):
        reconcile_module.reconcile_pending_teaching_three_stage(
            trace, _ROOT, _spec(), seed=0, config_path=config,
            specs_path=Path("config/specs_table_iii.yaml"), runner=runner,
        )


def test_second_pending_adopts_v4_remote_recovery_without_redispatch(tmp_path: Path) -> None:
    if not _RECOVERED_SECOND.is_dir():
        pytest.skip("private controlled recovered second archive is unavailable")
    trace, _ = _pending_copy(tmp_path, 2)
    lines = (trace / "agent_events.jsonl").read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    event["run_id"] = _RECOVERED_SECOND.name
    lines[-1] = json.dumps(event, ensure_ascii=False)
    (trace / "agent_events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    journal = inspect_journal(trace, candidate_runs_root=_ROOT)
    write_json(trace / "feedback_pending.json", reconcile_module._pending_report(trace, journal, _spec(), 0))
    config = Path("config/remote_cadence.local.yaml")
    runner = Mock()
    runner.config = reconcile_module.load_remote_config(config)
    report = reconcile_module.reconcile_pending_teaching_three_stage(
        trace, _ROOT, _spec(), seed=0, config_path=config,
        specs_path=Path("config/specs_table_iii.yaml"), runner=runner,
    )
    assert report["status"] == "reconciled_existing_second_archive"
    assert report["adopted_run_id"] == _RECOVERED_SECOND.name
    assert report["adopted_run_redispatched"] is False
    runner.run_remote.assert_not_called()
    assert reconcile_module.audit_teaching_three_stage_agent_feedback(trace, _ROOT, _spec())[
        "status"
    ] == "verified_two_run_teaching_agent_feedback"


def test_first_pending_adopts_real_archive_before_new_second_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, pending = _pending_copy(tmp_path, 1)
    config = Path("config/remote_cadence.local.yaml")
    if not config.is_file():
        pytest.skip("private Cadence connection config is unavailable")
    runner = Mock()
    runner.config = reconcile_module.load_remote_config(config)
    calls = []

    def uncertain_second(config_path, runs_root, spec, candidate, **kwargs):
        calls.append((candidate.candidate_id, kwargs["run_id"]))
        raise RemoteEvaluationUncertain("controlled second reply loss")

    monkeypatch.setattr(reconcile_module, "run_teaching_three_stage_candidate", uncertain_second)
    report = reconcile_module.reconcile_pending_teaching_three_stage(
        trace, _ROOT, _spec(), seed=0, config_path=config,
        specs_path=Path("config/specs_table_iii.yaml"), runner=runner,
    )
    assert pending["pending_run_id"] != report["pending_run_id"]
    assert calls == [("S1_seed0_teach3_resonance", report["pending_run_id"])]
    assert report["status"] == "pending_remote_evaluation"
    assert report["safe_to_retry"] is False
    assert json.loads((trace / "feedback_pending.json").read_text(encoding="utf-8")) == report
    assert not (trace / "agent_trace.json").exists()
    journal = inspect_journal(trace, candidate_runs_root=_ROOT)
    assert journal.disposition == "reconcile_pending_evaluation"
    assert journal.evaluations_used == 2 and journal.candidate_bindings_verified


@pytest.mark.parametrize("target_round", [1, 2])
def test_reply_injector_suppresses_only_selected_successful_spectre_return(
    monkeypatch: pytest.MonkeyPatch, target_round: int,
) -> None:
    config = RemoteCadenceConfig(
        host="example.invalid", user="test", remote_root="/tmp/three_stage_agent",
    )
    command = [
        config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
        "+log", "spectre.log", "teaching_three_stage_probe.scs",
    ]
    calls = []

    def actual(self, argv, *, cwd=None, timeout_seconds=None):
        calls.append((tuple(argv), cwd))
        return CommandResult(action="ssh", argv=tuple(argv), returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(RemoteRunner, "run_remote", actual)
    runner = NthReplySuppressedRunner(config, target_round=target_round)
    first = runner.run_remote(command, cwd="/tmp/one", timeout_seconds=180)
    second = runner.run_remote(command, cwd="/tmp/two", timeout_seconds=180)
    assert runner.spectre_calls == 2
    assert runner.target_real_returncode == 0 and runner.target_reply_suppressed
    assert [first.returncode, second.returncode] == (
        [255, 0] if target_round == 1 else [0, 255]
    )
    assert len(calls) == 2
    with pytest.raises(ValueError, match="exactly two"):
        runner.run_remote(command, cwd="/tmp/three", timeout_seconds=180)
