from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_NETLIST, render_teaching_three_stage
from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.experiments import run_teaching_three_stage as module
from orfadc.schemas import Candidate, Spec


def test_three_stage_renderer_preserves_baseline_and_limits_changes() -> None:
    assert render_teaching_three_stage() == PUBLIC_NETLIST.read_bytes()
    tuned = render_teaching_three_stage(output_tune_ff=190).decode("ascii")
    assert tuned.count("COUTTUNE (outp outn) capacitor c=190f") == 1
    assert tuned.count("PORT2 (outp outn) port r=1787") == 1
    transformed = render_teaching_three_stage(output_secondary_nh=4.1).decode("ascii")
    assert "L3S (outp outn) inductor l=4.0999999999999996n" in transformed
    assert "COUTTUNE" not in transformed
    for bad in (-1, 501, float("nan"), "190"):
        with pytest.raises(ValueError, match="tuning capacitance"):
            render_teaching_three_stage(output_tune_ff=bad)
    for bad in (0.1, 17, float("nan"), "4.1"):
        with pytest.raises(ValueError, match="secondary inductance"):
            render_teaching_three_stage(output_secondary_nh=bad)
    broadband = render_teaching_three_stage(broadband=True).decode("ascii")
    baseline = PUBLIC_NETLIST.read_text(encoding="ascii")
    assert broadband == baseline.replace(
        "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2]",
        "sp sp start=100M stop=20.1G lin=400 ports=[PORT1 PORT2]",
    )
    with pytest.raises(ValueError, match="boolean"):
        render_teaching_three_stage(broadband=1)


def test_three_stage_memory_gate_precedes_archive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    archive = tmp_path / "no_run"
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage(tmp_path / "unused.yaml", archive)
    assert not archive.exists()


def test_three_stage_broadband_memory_gate_precedes_archive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    archive = tmp_path / "no_broadband_run"
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage(tmp_path / "unused.yaml", archive, broadband=True)
    assert not archive.exists()


def test_three_stage_remote_mkdir_failure_is_retained(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    runner = SimpleNamespace(
        config=SimpleNamespace(remote_root="/tmp/teaching_runs"),
        probe=lambda **kwargs: {"status": "ok", "tools": {"spectre": {"found": True}}},
        run_remote=lambda command, **kwargs: SimpleNamespace(ok=True),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=False),
    )
    archive = tmp_path / "mkdir_failure"
    with pytest.raises(RuntimeError, match="remote_directory"):
        module.run_teaching_three_stage(tmp_path / "unused.yaml", archive, runner=runner)
    assert (archive / "netlist.scs").is_file()
    assert (archive / "failure.json").is_file()
    assert not (archive / "metrics.json").exists()


def test_three_stage_candidate_context_is_bounded_before_remote_work(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    candidate = Candidate(
        "S1_seed0_teach3_0", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 2.0},
        status="teaching_three_stage_diagnostic",
    )
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_three_stage(
            tmp_path / "unused", tmp_path / "valid", output_secondary_nh=2.0,
            candidate=candidate, spec=spec,
        )
    with pytest.raises(ValueError, match="bounded S1"):
        module.run_teaching_three_stage(
            tmp_path / "unused", tmp_path / "mismatch", output_secondary_nh=4.0,
            candidate=candidate, spec=spec,
        )
    assert not (tmp_path / "mismatch").exists()


@pytest.mark.parametrize("failure", ["transport_code", "transport_exception"])
def test_candidate_dispatch_uncertainty_keeps_remote_identity_and_no_metrics(
    monkeypatch, tmp_path: Path, failure: str,
) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    spec = Spec("S1", 10.0, 0.2, 30.0, 25.0, 5.0, -25.0)
    candidate = Candidate(
        "S1_seed0_teach3_pending", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 4.085532},
        status="teaching_three_stage_diagnostic",
    )
    config = RemoteCadenceConfig(host="example.invalid", user="test", remote_root="/tmp/teach3")
    dispatches = []

    def run_remote(command, **kwargs):
        if command[0] == "pgrep":
            return SimpleNamespace(ok=True)
        if command[0] == "mkdir":
            return SimpleNamespace(ok=True)
        dispatches.append((command, kwargs))
        if failure == "transport_exception":
            raise OSError("lost controller response")
        return SimpleNamespace(returncode=255, stdout="", stderr="control channel failed", ok=False)

    runner = SimpleNamespace(
        config=config,
        probe=lambda **kwargs: {"status": "ok", "tools": {"spectre": {"found": True}}},
        run_remote=run_remote,
        ensure_remote_dir=lambda path: SimpleNamespace(ok=True),
        upload=lambda local, remote: SimpleNamespace(ok=True),
    )
    archive = tmp_path / "planned_run"
    with pytest.raises(RemoteEvaluationUncertain, match="outcome is uncertain"):
        module.run_teaching_three_stage(
            tmp_path / "unused", archive, output_secondary_nh=4.085532,
            candidate=candidate, spec=spec, runner=runner,
        )
    import json
    plan = json.loads((archive / "dispatch_plan.json").read_text(encoding="utf-8"))
    uncertain = json.loads((archive / "dispatch_uncertain.json").read_text(encoding="utf-8"))
    assert len(dispatches) == 1
    assert dispatches[0][1]["cwd"] == plan["remote_dir"]
    assert plan["remote_dir"] == "/tmp/teach3/teach3_S1_seed0_S1_seed0_teach3_pending_planned_run"
    assert plan["remote_identity_sha256"] and (archive / "agent_remote.json").is_file()
    assert uncertain["safe_to_retry"] is False
    assert not (archive / "metrics.json").exists()
    assert not (archive / "evidence_manifest.json").exists()


def test_candidate_refuses_existing_remote_directory_before_upload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    spec = Spec("S1", 10.0, 0.2, 30.0, 25.0, 5.0, -25.0)
    candidate = Candidate(
        "S1_seed0_teach3_exclusive", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 2.0},
        status="teaching_three_stage_diagnostic",
    )
    operations = []

    def run_remote(command, **kwargs):
        operations.append(command[0])
        return SimpleNamespace(ok=command[0] != "mkdir")

    runner = SimpleNamespace(
        config=RemoteCadenceConfig(host="example.invalid", user="test", remote_root="/tmp/teach3"),
        probe=lambda **kwargs: {"status": "ok", "tools": {"spectre": {"found": True}}},
        run_remote=run_remote,
        ensure_remote_dir=lambda path: SimpleNamespace(ok=True),
        upload=lambda *args: pytest.fail("upload must not follow a reused remote directory"),
    )
    archive = tmp_path / "new_run"
    with pytest.raises(RuntimeError, match="remote_directory"):
        module.run_teaching_three_stage(
            tmp_path / "unused", archive, output_secondary_nh=2.0,
            candidate=candidate, spec=spec, runner=runner,
        )
    assert operations == ["pgrep", "mkdir"]
    assert (archive / "dispatch_plan.json").is_file()
    assert (archive / "failure.json").is_file()
    assert not (archive / "evidence_manifest.json").exists()
