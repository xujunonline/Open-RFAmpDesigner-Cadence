from pathlib import Path

import pytest

from orfadc.experiments import run_teaching_three_stage_candidate as module
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _candidate(secondary: float = 2.0) -> Candidate:
    return Candidate(
        "S1_seed0_teach3_0", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": secondary},
        status="teaching_three_stage_diagnostic",
    )


def test_candidate_runner_binds_unique_directory_and_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    calls = []

    def fake_run(config, run_dir, **kwargs):
        calls.append((run_dir, kwargs))
        run_dir.mkdir()
        return {"status": "ok_with_warnings", "not_lna_result": True, "spec_pass": None}

    monkeypatch.setattr(module, "run_teaching_three_stage", fake_run)
    monkeypatch.setattr(module, "audit_teaching_three_stage", lambda path: {"status": "verified"})
    runs_root = tmp_path / "runs"
    run_dir, payload = module.run_teaching_three_stage_candidate(
        tmp_path / "config", runs_root, _spec(), _candidate(), run_id="run0",
    )
    assert run_dir == runs_root / "S1/seed0/S1_seed0_teach3_0/run0"
    assert calls[0][1]["output_secondary_nh"] == 2.0
    assert calls[0][1]["candidate"].to_dict() == _candidate().to_dict()
    assert payload["spec_pass"] is None
    with pytest.raises(FileExistsError, match="already exists"):
        module.run_teaching_three_stage_candidate(
            tmp_path / "config", runs_root, _spec(), _candidate(), run_id="run0",
        )
    assert len(calls) == 1


def test_candidate_runner_rejects_out_of_domain_before_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    runs_root = tmp_path / "runs"
    with pytest.raises(ValueError, match="secondary inductance"):
        module.run_teaching_three_stage_candidate(
            tmp_path / "config", runs_root, _spec(), _candidate(20.0), run_id="run0",
        )
    invalid_id = _candidate()
    invalid_id.candidate_id = "../escape"
    with pytest.raises(ValueError, match="unsafe context"):
        module.run_teaching_three_stage_candidate(
            tmp_path / "config", runs_root, _spec(), invalid_id, run_id="run0",
        )
    assert not runs_root.exists()
