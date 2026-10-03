from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import run_teaching_three_stage_oa as module


@pytest.mark.parametrize("context", ["relative/context.cxt", "/tmp/../context.cxt", "/tmp/a;id", ""])
def test_three_stage_oa_rejects_unsafe_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: str,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    with pytest.raises(ValueError, match="schematic context"):
        module.run_teaching_three_stage_oa(
            tmp_path / "unused.yaml", tmp_path / "archive", schematic_context=context,
        )
    assert not (tmp_path / "archive").exists()


def test_three_stage_oa_memory_gate_precedes_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "audit_teaching_three_stage", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage_oa(
            tmp_path / "unused.yaml", tmp_path / "archive",
            schematic_context="/tmp/schematic.cxt",
        )
    assert not (tmp_path / "archive").exists()


def test_three_stage_oa_remote_directory_failure_keeps_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "audit_teaching_three_stage", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    runner = SimpleNamespace(
        config=SimpleNamespace(remote_root="/tmp/teaching_runs"),
        probe=lambda tools: {"status": "ok", "tools": {name: {"found": True} for name in tools}},
        run_remote=lambda command, **kwargs: SimpleNamespace(ok=True),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "failed_run"
    result = module.run_teaching_three_stage_oa(
        tmp_path / "unused.yaml", archive, schematic_context="/tmp/schematic.cxt", runner=runner,
    )
    assert result["status"] == "remote_directory_failed"
    assert result["not_lna_result"] is True and result["spec_pass"] is None
    assert read_evidenced_metrics(archive) == result


def test_three_stage_oa_missing_create_log_stops_before_simulation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "audit_teaching_three_stage", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    calls = []

    def run_remote(command, **kwargs):
        calls.append(tuple(command))
        return SimpleNamespace(ok=True, stdout="OCEAN completed\n", stderr="")

    runner = SimpleNamespace(
        config=SimpleNamespace(
            remote_root="/tmp/teaching_runs", xvfb_path=None, display=None,
            xauthority=None, ocean_bin="ocean",
        ),
        probe=lambda tools: {"status": "ok", "tools": {name: {"found": True} for name in tools}},
        run_remote=run_remote,
        ensure_remote_dir=lambda path: SimpleNamespace(ok=True),
        upload=lambda source, destination: SimpleNamespace(ok=True),
        download=lambda source, destination: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "missing_log"
    result = module.run_teaching_three_stage_oa(
        tmp_path / "unused.yaml", archive, schematic_context="/tmp/schematic.cxt", runner=runner,
    )
    assert result["status"] == "schematic_creation_failed"
    assert len(calls) == 2
    assert (archive / "create_stdout.log").read_text(encoding="utf-8") == "OCEAN completed\n"
    assert read_evidenced_metrics(archive) == result
