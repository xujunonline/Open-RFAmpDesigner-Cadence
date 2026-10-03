from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from orfadc.agents.journal import inspect_journal
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.cadence.remote_runner import load_remote_config
from orfadc.config_loader import load_specs, write_json
from orfadc.agents import resume_teaching_three_stage_agent as module
from orfadc.experiments.probe_teaching_three_stage_agent_resume import (
    audit_teaching_three_stage_agent_resume_probe,
)


_ROOT = Path("results/runs/teaching_three_stage_candidates")
_COMPLETE = Path("results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba")
_SPECS = Path("config/specs_table_iii.yaml")
_CONFIG = Path("config/remote_cadence.local.yaml")
_REAL_RESUMED = Path("results/runs/teaching_three_stage_agent_resume/20260927T202048Z_e6bdafbe")


def _spec():
    return next(item for item in load_specs(_SPECS) if item.id == "S1")


def _copy_before_second(tmp_path: Path, *, queued: bool) -> Path:
    if not _COMPLETE.is_dir() or not _CONFIG.is_file():
        pytest.skip("private complete three-stage trace or remote config is unavailable")
    trace = tmp_path / ("before_second_eval" if queued else "before_second_search")
    shutil.copytree(_COMPLETE, trace)
    (trace / "agent_trace.json").unlink()
    (trace / "feedback_summary.json").unlink()
    lines = (trace / "agent_events.jsonl").read_bytes().splitlines(keepends=True)
    (trace / "agent_events.jsonl").write_bytes(b"".join(lines[:5 if queued else 4]))
    if not queued:
        snapshots = (trace / "agent_candidates.jsonl").read_bytes().splitlines(keepends=True)
        (trace / "agent_candidates.jsonl").write_bytes(snapshots[0])
    journal = inspect_journal(trace, candidate_runs_root=_ROOT)
    assert journal.disposition == "interrupted"
    return trace


@pytest.mark.parametrize("queued", [False, True])
def test_resume_only_dispatches_new_second_after_audited_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queued: bool,
) -> None:
    trace = _copy_before_second(tmp_path, queued=queued)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    dispatched = []

    def uncertain(config, root, spec, candidate, **kwargs):
        dispatched.append((candidate.candidate_id, kwargs["run_id"]))
        raise RemoteEvaluationUncertain("controlled second reply loss")

    monkeypatch.setattr(module, "run_teaching_three_stage_candidate", uncertain)
    runner = Mock()
    runner.config = load_remote_config(_CONFIG)
    report = module.resume_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0,
        config_path=_CONFIG, specs_path=_SPECS, runner=runner,
    )
    assert report["status"] == "pending_remote_evaluation"
    assert report["safe_to_retry"] is False
    assert dispatched == [("S1_seed0_teach3_resonance", report["pending_run_id"])]
    journal = inspect_journal(trace, candidate_runs_root=_ROOT)
    assert journal.disposition == "reconcile_pending_evaluation"
    assert journal.evaluations_used == 2 and journal.candidate_bindings_verified
    assert not (trace / "agent_trace.json").exists()
    with pytest.raises(ValueError, match="not eligible"):
        module.resume_teaching_three_stage_agent(
            trace, _ROOT, _spec(), seed=0,
            config_path=_CONFIG, specs_path=_SPECS, runner=runner,
        )
    assert len(dispatched) == 1


def test_resume_rejects_changed_intent_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _copy_before_second(tmp_path, queued=False)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    runner = Mock()
    runner.config = load_remote_config(_CONFIG)
    write_json(trace / "feedback_search_resume_intent.json", {
        "status": "first_source_audited_before_second_dispatch",
        "first_manifest_sha256": "0" * 64,
    })
    with pytest.raises(ValueError, match="intent changed"):
        module.resume_teaching_three_stage_agent(
            trace, _ROOT, _spec(), seed=0,
            config_path=_CONFIG, specs_path=_SPECS, runner=runner,
        )
    assert [json.loads(line)["action"] for line in (
        trace / "agent_events.jsonl"
    ).read_text(encoding="utf-8").splitlines()] == list(module._FIRST_ACTIONS)
    runner.run_remote.assert_not_called()


def test_real_resumed_trace_reaudits_and_rejects_report_tamper(tmp_path: Path) -> None:
    if not _REAL_RESUMED.is_dir():
        pytest.skip("private resumed three-stage Spectre trace is unavailable")
    report = audit_teaching_three_stage_agent_resume_probe(
        _REAL_RESUMED, _COMPLETE, _ROOT, _SPECS,
    )
    assert report["first_source_reused"] and report["new_second_spectre_calls"] == 1
    copied = tmp_path / _REAL_RESUMED.name
    shutil.copytree(_REAL_RESUMED, copied)
    path = copied / "resume_probe.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["new_second_spectre_calls"] = 2
    write_json(path, changed)
    with pytest.raises(ValueError, match="differs from source-audited"):
        audit_teaching_three_stage_agent_resume_probe(copied, _COMPLETE, _ROOT, _SPECS)
