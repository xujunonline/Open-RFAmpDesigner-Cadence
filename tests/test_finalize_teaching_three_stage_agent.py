from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.agents.finalize_teaching_three_stage_agent import finalize_teaching_three_stage_agent
from orfadc.agents.journal import inspect_journal
from orfadc.config_loader import load_specs
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback,
)


_ROOT = Path("results/runs/teaching_three_stage_candidates")
_COMPLETE = Path("results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba")
_RECOVERED_TRACES = (
    Path("results/runs/teaching_three_stage_agent_feedback/20260927T191949Z_8f1e9695"),
    Path("results/runs/teaching_three_stage_agent_feedback/20260927T200439Z_6577ff6a"),
)
_SPECS = Path("config/specs_table_iii.yaml")


def _spec():
    return next(item for item in load_specs(_SPECS) if item.id == "S1")


def _copy_at_boundary(tmp_path: Path, boundary: str) -> Path:
    if not _COMPLETE.is_dir():
        pytest.skip("private two-run three-stage Spectre trace is unavailable")
    trace = tmp_path / f"terminal_{boundary}"
    shutil.copytree(_COMPLETE, trace)
    (trace / "feedback_summary.json").unlink()
    if boundary in {"before_stop", "before_trace"}:
        (trace / "agent_trace.json").unlink()
    if boundary == "before_stop":
        lines = (trace / "agent_events.jsonl").read_bytes().splitlines(keepends=True)
        (trace / "agent_events.jsonl").write_bytes(b"".join(lines[:-1]))
    return trace


@pytest.mark.parametrize("boundary", ["before_stop", "before_trace", "before_summary"])
def test_finalizer_closes_real_two_source_trace_at_each_terminal_boundary(
    tmp_path: Path, boundary: str,
) -> None:
    trace = _copy_at_boundary(tmp_path, boundary)
    before = inspect_journal(trace, candidate_runs_root=_ROOT)
    assert before.disposition in {"interrupted", "terminal_snapshot_missing", "complete"}
    report = finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    )
    assert report["status"] == "finalized_existing_second_teaching_refinement"
    assert report["spectre_dispatched_by_finalizer"] is False
    assert inspect_journal(trace, candidate_runs_root=_ROOT).disposition == "complete"
    assert audit_teaching_three_stage_agent_feedback(trace, _ROOT, _spec())[
        "status"
    ] == "verified_two_run_teaching_agent_feedback"
    assert finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    ) == report


def test_terminal_finalizer_rejects_existing_complete_trace_without_recovery_intent(
    tmp_path: Path,
) -> None:
    if not _COMPLETE.is_dir():
        pytest.skip("private two-run three-stage Spectre trace is unavailable")
    trace = tmp_path / "already_complete"
    shutil.copytree(_COMPLETE, trace)
    with pytest.raises(ValueError, match="not in terminal recovery"):
        finalize_teaching_three_stage_agent(trace, _ROOT, _spec(), seed=0, specs_path=_SPECS)
    assert not (trace / "feedback_terminal_intent.json").exists()


def test_terminal_finalizer_rejects_changed_intent_or_binding(tmp_path: Path) -> None:
    trace = _copy_at_boundary(tmp_path, "before_trace")
    report = finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    )
    intent_path = trace / "feedback_terminal_intent.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["second_manifest_sha256"] = "0" * 64
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ValueError, match="intent changed"):
        finalize_teaching_three_stage_agent(trace, _ROOT, _spec(), seed=0, specs_path=_SPECS)
    assert report["second_manifest_sha256"] != intent["second_manifest_sha256"]


@pytest.mark.parametrize(
    "boundary", ["after_intent_before_stop", "after_stop_before_trace", "after_summary_before_report"],
)
def test_terminal_finalizer_reenters_after_its_own_write_boundaries(
    tmp_path: Path, boundary: str,
) -> None:
    trace = _copy_at_boundary(tmp_path, "before_stop")
    expected = finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    )
    (trace / "feedback_terminal_recovery.json").unlink()
    if boundary != "after_summary_before_report":
        (trace / "feedback_summary.json").unlink()
        (trace / "agent_trace.json").unlink()
    if boundary == "after_intent_before_stop":
        events = (trace / "agent_events.jsonl").read_bytes().splitlines(keepends=True)
        (trace / "agent_events.jsonl").write_bytes(b"".join(events[:-1]))
    assert finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    ) == expected
    assert audit_teaching_three_stage_agent_feedback(trace, _ROOT, _spec())[
        "status"
    ] == "verified_two_run_teaching_agent_feedback"


@pytest.mark.parametrize("source", _RECOVERED_TRACES)
def test_terminal_finalizer_accepts_v4_recovered_first_or_second_source(
    tmp_path: Path, source: Path,
) -> None:
    if not source.is_dir():
        pytest.skip("private recovered teaching agent trace is unavailable")
    trace = tmp_path / source.name
    shutil.copytree(source, trace)
    (trace / "feedback_summary.json").unlink()
    (trace / "agent_trace.json").unlink()
    report = finalize_teaching_three_stage_agent(
        trace, _ROOT, _spec(), seed=0, specs_path=_SPECS,
    )
    assert report["spectre_dispatched_by_finalizer"] is False
    assert audit_teaching_three_stage_agent_feedback(trace, _ROOT, _spec())[
        "status"
    ] == "verified_two_run_teaching_agent_feedback"
