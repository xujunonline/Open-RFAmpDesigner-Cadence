from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import run_teaching_oa as module


@pytest.mark.parametrize("value", ["relative/context.cxt", "/tmp/../context.cxt", "/tmp/a;id", ""])
def test_teaching_oa_rejects_unsafe_context(value: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schematic context"):
        module.run_teaching_oa(tmp_path / "unused.yaml", tmp_path / "archive", schematic_context=value)
    assert not (tmp_path / "archive").exists()


def test_teaching_oa_rejects_unknown_topology(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="topology"):
        module.run_teaching_oa(
            tmp_path / "unused.yaml", tmp_path / "archive",
            schematic_context="/tmp/schematic.cxt", topology="paper_lna",
        )
    assert not (tmp_path / "archive").exists()


@pytest.mark.parametrize("topology,vcas", [("cascode", 0.7), ("cascode", float("nan")),
                                            ("flat", 1.05), ("damped", 1.05)])
def test_teaching_oa_rejects_invalid_or_unused_cascode_bias(tmp_path: Path, topology: str, vcas: float) -> None:
    with pytest.raises(ValueError, match="VCAS"):
        module.run_teaching_oa(
            tmp_path / "unused.yaml", tmp_path / "archive", schematic_context="/tmp/schematic.cxt",
            topology=topology, vcas_v=vcas,
        )
    assert not (tmp_path / "archive").exists()


def test_teaching_oa_memory_gate_precedes_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_oa(
            tmp_path / "unused.yaml", tmp_path / "archive", schematic_context="/tmp/schematic.cxt"
        )
    assert not (tmp_path / "archive").exists()


@pytest.mark.parametrize("topology", ["flat", "damped", "cascode"])
def test_teaching_oa_remote_mkdir_failure_keeps_local_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    topology: str,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    runner = SimpleNamespace(
        config=SimpleNamespace(remote_root="/tmp/teaching_runs"),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "failed_run"
    result = module.run_teaching_oa(
        tmp_path / "unused.yaml", archive,
        schematic_context="/tmp/schematic.cxt", topology=topology, runner=runner,
    )
    assert result["status"] == "mkdir_failed"
    assert result["simulation_status"] == "unknown"
    assert result["spec_pass"] is None and result["not_lna_result"] is True
    assert result["teaching_topology"] == topology
    if topology == "cascode":
        assert result["teaching_vcas_v"] == 0.95
    assert all((archive / name).is_file() for _, name in module._PUBLIC_FILES.values())
    assert read_evidenced_metrics(archive) == result


def test_teaching_oa_missing_ocean_log_stops_before_simulation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    calls = []

    def run_remote(command, **kwargs):
        calls.append(tuple(command))
        return SimpleNamespace(ok=True, stdout="OCEAN returned\n", stderr="")

    runner = SimpleNamespace(
        config=SimpleNamespace(
            remote_root="/tmp/teaching_runs", xvfb_path=None,
            display=None, xauthority=None, ocean_bin="ocean",
        ),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=True),
        upload=lambda source, destination: SimpleNamespace(ok=True),
        run_remote=run_remote,
        download=lambda source, destination: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "missing_log"
    result = module.run_teaching_oa(
        tmp_path / "unused.yaml", archive,
        schematic_context="/tmp/schematic.cxt", runner=runner,
    )
    assert result["status"] == "schematic_creation_failed"
    assert len(calls) == 1
    assert (archive / "ocean_create_stdout.log").read_text(encoding="utf-8") == "OCEAN returned\n"
    assert read_evidenced_metrics(archive) == result
