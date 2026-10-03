from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.experiments import run_teaching_three_stage_hb as module


def test_three_stage_hb_runner_rejects_out_of_range_power_before_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    with pytest.raises(ValueError, match="-100..0"):
        module.run_teaching_three_stage_hb(
            tmp_path / "unused.yaml", tmp_path / "archive", input_dbm=1,
        )
    assert not (tmp_path / "archive").exists()


def test_three_stage_hb_runner_memory_gate_precedes_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage_hb(tmp_path / "unused.yaml", tmp_path / "archive")
    assert not (tmp_path / "archive").exists()


def test_three_stage_hb_higher_drive_reaches_memory_gate_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage_hb(
            tmp_path / "unused.yaml", tmp_path / "archive", input_dbm=-40,
        )
    assert not (tmp_path / "archive").exists()


def test_three_stage_hb_runner_remote_directory_failure_keeps_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    runner = SimpleNamespace(
        config=SimpleNamespace(remote_root="/tmp/teaching_runs"),
        probe=lambda tools: {"status": "ok", "tools": {"spectre": {"found": True}}},
        run_remote=lambda command, **kwargs: SimpleNamespace(ok=True),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "failed_run"
    with pytest.raises(RuntimeError, match="remote_directory"):
        module.run_teaching_three_stage_hb(
            tmp_path / "unused.yaml", archive, runner=runner,
        )
    assert (archive / "netlist.scs").is_file()
    assert (archive / "teaching_mos1_model.scs").is_file()
    assert '"status": "remote_directory"' in (archive / "failure.json").read_text(encoding="utf-8")
