import json
import math
import shutil
from pathlib import Path

import pytest

from orfadc.config_loader import load_specs
from orfadc.experiments import run_teaching_three_stage_refinement as module
from orfadc.schemas import Candidate
from orfadc.agents.uncertainty import RemoteEvaluationUncertain


_SOURCE = Path(
    "results/runs/teaching_three_stage_candidates/S1/seed0/"
    "S1_seed0_teach3_l3s2/20260927T180217Z_33e94f02"
)
_RUNS_ROOT = Path("results/runs/teaching_three_stage_candidates")
_TRACE = Path("results/runs/teaching_three_stage_feedback/20260927T181057Z_e080745d")
_RECOVERED_TRACE = Path(
    "results/runs/teaching_three_stage_feedback_lost_reply/"
    "20260927T184753Z_14f1245f/20260927T184753Z_d4102dc4"
)


def _spec():
    return next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")


def test_resonance_seed_is_derived_from_s1_center_and_load_capacitance() -> None:
    expected = round(1e9 / ((2 * math.pi * 10e9) ** 2 * 62e-15), 6)
    assert module.resonance_seed_nh(_spec()) == expected == 4.085532


def test_proposal_is_bound_to_raw_spectre_parent() -> None:
    if not _SOURCE.is_dir():
        pytest.skip("private candidate-bound source is unavailable")
    candidate, observed, proposal = module._proposal(_SOURCE, _RUNS_ROOT, _spec(), 0)
    assert candidate.passive_params == {"output_tune_ff": 0.0, "output_secondary_nh": 4.085532}
    assert observed["s22_worst_db"] > -10
    assert observed["s21_worst_db"] < _spec().gain_db
    assert proposal["first_manifest_sha256"] == observed["evidence_manifest_sha256"]
    assert proposal["first_observation"] == observed
    assert proposal["not_lna_result"] is True and proposal["spec_pass"] is None
    _, _, absolute_root_proposal = module._proposal(
        _SOURCE, _RUNS_ROOT.resolve(), _spec(), 0,
    )
    assert absolute_root_proposal["first_run_relative"] == proposal["first_run_relative"]
    with pytest.raises(ValueError, match="outside the candidate run root"):
        module._proposal(_SOURCE, _RUNS_ROOT / "another", _spec(), 0)


def test_proposal_rejects_valid_raw_archive_under_wrong_candidate_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SOURCE.is_dir():
        pytest.skip("private candidate-bound source is unavailable")
    copied_root = tmp_path / "runs"
    copied = copied_root / "S1/seed0/wrong_candidate_id" / _SOURCE.name
    shutil.copytree(_SOURCE, copied)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    with pytest.raises(ValueError, match="does not match candidate identity"):
        module._proposal(copied, copied_root, _spec(), 0)


def test_uncertain_dispatch_is_recorded_without_summary_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = Candidate(
        "S1_seed0_teach3_resonance", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 4.085532},
        status="teaching_three_stage_diagnostic",
    )
    proposal = {"schema_version": 1, "second_candidate": candidate.to_dict()}
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "_proposal", lambda *args: (candidate, {}, proposal.copy()))
    calls = []

    def unavailable(*args, **kwargs):
        calls.append((args, kwargs))
        raise RemoteEvaluationUncertain("transport response lost")

    monkeypatch.setattr(module, "run_teaching_three_stage_candidate", unavailable)
    with pytest.raises(RemoteEvaluationUncertain, match="response lost"):
        module.run_teaching_three_stage_refinement(
            tmp_path / "config", tmp_path / "runs", tmp_path / "traces",
            tmp_path / "first", _spec(), seed=0,
        )
    trace_dir, = (tmp_path / "traces").iterdir()
    planned = json.loads((trace_dir / "proposal.json").read_text(encoding="utf-8"))
    uncertainty = json.loads((trace_dir / "dispatch_uncertain.json").read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert uncertainty["safe_to_retry"] is False
    assert planned["second_run_relative"] == uncertainty["second_run_relative"]
    assert not (trace_dir / "feedback_summary.json").exists()
    with pytest.raises(ValueError, match="remains unverified"):
        module.rebuild_teaching_three_stage_feedback(trace_dir, tmp_path / "runs")


def test_real_feedback_reaudits_and_rejects_changed_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _TRACE.is_dir():
        pytest.skip("private two-candidate Spectre feedback trace is unavailable")
    report = module.audit_teaching_three_stage_feedback(_TRACE, _RUNS_ROOT)
    assert report["status"] == "audited_teaching_three_stage_feedback"
    assert report["second_observation"]["s21_worst_db"] > report["first_observation"]["s21_worst_db"]
    assert report["second_observation"]["s22_worst_db"] < report["first_observation"]["s22_worst_db"]
    assert report["compression_status"] == "not_measured"
    assert report["not_lna_result"] is True and report["spec_pass"] is None
    copy = tmp_path / "changed_trace"
    shutil.copytree(_TRACE, copy)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    summary = json.loads((copy / "feedback_summary.json").read_text(encoding="utf-8"))
    summary["delta_s21_worst_db"] += 1
    (copy / "feedback_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from source-audited"):
        module.audit_teaching_three_stage_feedback(copy, _RUNS_ROOT)


def test_definite_backend_error_is_not_mislabeled_as_uncertain_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = Candidate(
        "S1_seed0_teach3_resonance", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 4.085532},
        status="teaching_three_stage_diagnostic",
    )
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "_proposal", lambda *args: (
        candidate, {}, {"schema_version": 1, "second_candidate": candidate.to_dict()},
    ))
    monkeypatch.setattr(
        module, "run_teaching_three_stage_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("definite backend error")),
    )
    with pytest.raises(RuntimeError, match="definite backend error"):
        module.run_teaching_three_stage_refinement(
            tmp_path / "config", tmp_path / "runs", tmp_path / "traces",
            tmp_path / "first", _spec(), seed=0,
        )
    trace_dir, = (tmp_path / "traces").iterdir()
    marker = json.loads((trace_dir / "evaluation_unverified.json").read_text(encoding="utf-8"))
    assert marker["safe_to_retry"] is False
    assert not (trace_dir / "dispatch_uncertain.json").exists()
    assert not (trace_dir / "feedback_summary.json").exists()
    with pytest.raises(ValueError, match="outside the recovery protocol"):
        module.rebuild_teaching_three_stage_feedback(trace_dir, tmp_path / "runs")


def test_real_recovered_second_round_finalizer_is_readonly_and_ack_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _RECOVERED_TRACE.is_dir():
        pytest.skip("private recovered two-round Spectre trace is unavailable")
    report = module.audit_teaching_three_stage_feedback(_RECOVERED_TRACE, _RUNS_ROOT)
    assert report["status"] == "audited_teaching_three_stage_feedback"
    assert report["delta_s21_worst_db"] == pytest.approx(2.8871623395955286)
    assert report["not_lna_result"] is True and report["spec_pass"] is None
    copied = tmp_path / "copied_trace"
    shutil.copytree(_RECOVERED_TRACE, copied)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    (copied / "feedback_summary.json").unlink()
    assert module.finalize_teaching_three_stage_feedback(copied, _RUNS_ROOT) == report
    assert module.finalize_teaching_three_stage_feedback(copied, _RUNS_ROOT) == report
    ack_path = copied / "recovery_ack.json"
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    ack["second_manifest_sha256"] = "0" * 64
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    with pytest.raises(ValueError, match="dispatch remains unverified"):
        module.audit_teaching_three_stage_feedback(copied, _RUNS_ROOT)
    with pytest.raises(ValueError, match="acknowledgement changed"):
        module.finalize_teaching_three_stage_feedback(copied, _RUNS_ROOT)
