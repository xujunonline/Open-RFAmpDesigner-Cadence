from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.candidate_runs import reserve_candidate_run
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec(id="S1", fc_ghz=10, fbw_ratio=0.2, power_ma=10,
                gain_db=10, nf_max_db=3, ip1db_min_dbm=-15)


def _candidate(candidate_id: str = "S1_seed0_search0") -> Candidate:
    return Candidate(candidate_id=candidate_id, spec_id="S1", seed=0,
                     power_ratio_list=[0.4, 0.3, 0.3])


def test_reserve_candidate_run_is_exclusive(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    path = reserve_candidate_run(runs_root, _spec(), _candidate(), run_id="run001")
    assert path == runs_root / "S1" / "seed0" / "S1_seed0_search0" / "run001"
    assert path.is_dir()
    with pytest.raises(FileExistsError):
        reserve_candidate_run(runs_root, _spec(), _candidate(), run_id="run001")
    second = reserve_candidate_run(runs_root, _spec(), _candidate())
    assert second.is_dir() and second != path


@pytest.mark.parametrize("bad_id", ["../escape", "/absolute", "with space", "CON", "COM1.txt", "trail."])
def test_reserve_candidate_run_rejects_unsafe_ids(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(ValueError, match="candidate id"):
        reserve_candidate_run(tmp_path, _spec(), _candidate(bad_id), run_id="run001")


def test_reserve_candidate_run_checks_context_and_symlink(tmp_path: Path) -> None:
    wrong = _candidate()
    wrong.spec_id = "S2"
    with pytest.raises(ValueError, match="spec/seed"):
        reserve_candidate_run(tmp_path, _spec(), wrong)
    root_link = tmp_path / "runs_link"
    try:
        root_link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError, match="root"):
        reserve_candidate_run(root_link, _spec(), _candidate())


def test_reserve_candidate_run_rejects_symlinked_candidate_parent(tmp_path: Path) -> None:
    spec_dir = tmp_path / "S1"
    spec_dir.mkdir()
    seed_dir = spec_dir / "seed0"
    try:
        seed_dir.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError, match="symlink"):
        reserve_candidate_run(tmp_path, _spec(), _candidate())
