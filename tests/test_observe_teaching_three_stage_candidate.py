import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.config_loader import load_specs
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.schemas import Candidate


_SOURCE = Path(
    "results/runs/teaching_three_stage_candidates/S1/seed0/"
    "S1_seed0_teach3_l3s2/20260927T180217Z_33e94f02"
)


def _context() -> tuple[object, Candidate]:
    if not _SOURCE.is_dir():
        pytest.skip("private candidate-bound three-stage source is unavailable")
    spec = next(item for item in load_specs(Path("config/specs_table_iii.yaml")) if item.id == "S1")
    candidate = Candidate(**read_evidenced_metrics(_SOURCE)["candidate"])
    return spec, candidate


def test_real_three_stage_candidate_observation_rebuilds_s1_band() -> None:
    spec, candidate = _context()
    observation = observe_teaching_three_stage_candidate(_SOURCE, spec, candidate)
    assert observation["status"] == "raw_audited_teaching_small_signal"
    assert observation["band_points"] == 81
    assert observation["s11_worst_db"] == pytest.approx(-14.22087151085634)
    assert observation["s21_worst_db"] == pytest.approx(-1.2099472359686239)
    assert observation["s22_worst_db"] == pytest.approx(-0.9481347388037369)
    assert observation["nf_worst_db"] == pytest.approx(5.663518392505789)
    assert observation["s21_ripple_db"] == pytest.approx(9.722330193349261)
    assert observation["compression_status"] == "not_measured"
    assert observation["not_lna_result"] is True and observation["spec_pass"] is None


def test_three_stage_observation_rejects_wrong_candidate_and_changed_source(tmp_path: Path) -> None:
    spec, candidate = _context()
    changed_candidate = Candidate(**candidate.to_dict())
    changed_candidate.passive_params["output_secondary_nh"] = 4.0
    with pytest.raises(ValueError, match="does not match"):
        observe_teaching_three_stage_candidate(_SOURCE, spec, changed_candidate)
    copied = tmp_path / _SOURCE.name
    shutil.copytree(_SOURCE, copied)
    with (copied / "waveforms.csv").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        observe_teaching_three_stage_candidate(copied, spec, candidate)
