from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments import run_passive_candidate as candidate_module
from orfadc.experiments import run_passive_noise as passive_module
from orfadc.experiments.run_passive_candidate import (
    render_passive_candidate_netlist,
    run_passive_candidate,
)
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec(id="S1", fc_ghz=10, fbw_ratio=0.2, power_ma=10,
                gain_db=10, nf_max_db=3, ip1db_min_dbm=-15)


def _candidate() -> Candidate:
    return Candidate(candidate_id="diagnostic01", spec_id="S1", seed=0,
                     power_ratio_list=[0.4, 0.3, 0.3],
                     passive_params={"rloss_ohm": 5.0, "lpath_nh": 1.0, "cshunt_pf": 0.5})


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "remote.yaml"
    path.write_text("remote:\n  host: example.test\n  user: testuser\n", encoding="utf-8")
    return path


def _command(ok: bool = True) -> CommandResult:
    return CommandResult("fake", (), 0 if ok else 1, "", "")


class _FakeRunner:
    fail_mkdir = False

    def __init__(self, config: RemoteCadenceConfig) -> None:
        self.config = config

    def ensure_remote_dir(self, remote_dir: str) -> CommandResult:
        return _command(not self.fail_mkdir)

    def upload(self, local_path: Path, remote_path: str) -> CommandResult:
        return _command()

    def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
        return _command()

    def download(self, remote_path: str, local_path: Path) -> CommandResult:
        contents = {
            "spectre.log": "spectre completes with 0 errors, 0 warnings\n",
            "ideal_twoport_noise.s2p": (
                "# Hz S RI R 50\n"
                "1e8 0 0 0.5 0 0.5 0 0 0\n"
                "2e10 0 0 0.5 0 0.5 0 0 0\n"
            ),
            "sp_noise.sp": "raw sp data\n",
            "sp_noise.noise.sp": (
                'TRACE\n"NF" "dB"\n"NFmin" "dB"\n'
                '"F" "Noise factor"\n"Fmin" "Noise factor"\n'
                'VALUE\n"freq" 1e8\n"NF" 3.010299956639812\n'
                '"NFmin" 0\n"F" 2\n"Fmin" 1\n'
                '"freq" 2e10\n"NF" 3.010299956639812\n'
                '"NFmin" 0\n"F" 2\n"Fmin" 1\nEND\n'
            ),
        }
        local_path.write_text(contents[local_path.name], encoding="utf-8")
        return _command()


def test_passive_candidate_success_archive_is_never_lna_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(passive_module, "RemoteRunner", _FakeRunner)
    runs = tmp_path / "runs"
    runs.mkdir()
    run_dir, payload = run_passive_candidate(
        _config(tmp_path), runs, _spec(), _candidate(), run_id="run001"
    )
    assert run_dir == runs / "S1/seed0/diagnostic01/run001"
    assert payload["status"] == "ok"
    assert payload["run_id"] == "run001"
    assert payload["spec_pass"] is None and payload["not_lna_result"] is True
    assert payload["candidate"]["candidate_id"] == "diagnostic01"
    assert payload["metrics"]["s21_db"] == pytest.approx(-6.020599913, abs=1e-6)
    assert payload["metrics"]["ripple_db"] == pytest.approx(0.0)
    assert payload["units"]["s21_db"] == "dB"
    assert "RLOSS=5" in (run_dir / "netlist.scs").read_text(encoding="ascii")
    assert read_evidenced_metrics(run_dir) == payload
    assert json.loads((run_dir / "candidate.json").read_text(encoding="utf-8")) == _candidate().to_dict()
    with pytest.raises(FileExistsError):
        run_passive_candidate(_config(tmp_path), runs, _spec(), _candidate(), run_id="run001")


def test_passive_candidate_failure_archive_retains_context(tmp_path: Path, monkeypatch) -> None:
    class FailingRunner(_FakeRunner):
        fail_mkdir = True

    monkeypatch.setattr(passive_module, "RemoteRunner", FailingRunner)
    runs = tmp_path / "runs"
    runs.mkdir()
    run_dir, payload = run_passive_candidate(
        _config(tmp_path), runs, _spec(), _candidate(), run_id="run002"
    )
    assert payload["status"] == "mkdir_failed"
    assert payload["failure_code"] == "remote_directory_failed"
    assert payload["simulation_status"] == "unknown"
    assert payload["spec_pass"] is None
    assert read_evidenced_metrics(run_dir) == payload
    assert not (run_dir / "spectre.log").exists()


@pytest.mark.parametrize("bad_value", [float("nan"), -1, "5", True, 1000])
def test_passive_candidate_rejects_bad_parameter_values(bad_value: object) -> None:
    candidate = _candidate()
    candidate.passive_params["rloss_ohm"] = bad_value
    with pytest.raises(ValueError, match="rloss_ohm"):
        render_passive_candidate_netlist(candidate)


def test_passive_candidate_rejects_active_params_and_extra_keys() -> None:
    candidate = _candidate()
    candidate.active_params = {"w": 1}
    with pytest.raises(ValueError, match="active parameters"):
        render_passive_candidate_netlist(candidate)
    candidate = _candidate()
    candidate.passive_params["include"] = "private.scs"
    with pytest.raises(ValueError, match="exactly"):
        render_passive_candidate_netlist(candidate)
    candidate.passive_params = ["rloss_ohm", "lpath_nh", "cshunt_pf"]
    with pytest.raises(ValueError, match="exactly"):
        render_passive_candidate_netlist(candidate)


def test_passive_candidate_netlist_preserves_float_value() -> None:
    candidate = _candidate()
    candidate.passive_params["rloss_ohm"] = 1.2345678901234567
    text = render_passive_candidate_netlist(candidate)
    token = next(part for part in text.split() if part.startswith("RLOSS="))
    assert float(token.partition("=")[2]) == candidate.passive_params["rloss_ohm"]


def test_passive_runner_rejects_unsafe_run_id_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "not_created"
    with pytest.raises(ValueError, match="run_id"):
        passive_module.run_passive_noise(
            tmp_path / "remote.yaml", tmp_path / "netlist.scs", output, run_id="../escape"
        )
    assert not output.exists()


def test_passive_candidate_labels_license_related_timeout(tmp_path: Path, monkeypatch) -> None:
    class TimeoutRunner(_FakeRunner):
        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            return CommandResult("fake", (), 124, "", "")

        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            local_path.write_text("waiting for license\n", encoding="utf-8")
            return _command()

    monkeypatch.setattr(passive_module, "RemoteRunner", TimeoutRunner)
    runs = tmp_path / "runs"
    runs.mkdir()
    run_dir, payload = run_passive_candidate(
        _config(tmp_path), runs, _spec(), _candidate(), run_id="run003"
    )
    assert payload["status"] == "spectre_failed"
    assert payload["failure_code"] == "license_related_timeout"
    assert payload["spec_pass"] is None
    assert read_evidenced_metrics(run_dir) == payload


def test_passive_candidate_downgrades_unclean_success_log(tmp_path: Path, monkeypatch) -> None:
    class UncleanLogRunner(_FakeRunner):
        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            result = super().download(remote_path, local_path)
            if local_path.name == "spectre.log":
                local_path.write_text("SPECTRE-25 termination failure\n", encoding="utf-8")
            return result

    monkeypatch.setattr(passive_module, "RemoteRunner", UncleanLogRunner)
    runs = tmp_path / "runs"
    runs.mkdir()
    run_dir, payload = run_passive_candidate(
        _config(tmp_path), runs, _spec(), _candidate(), run_id="run004"
    )
    assert payload["status"] == "evidence_failed"
    assert payload["failure_code"] == "evidence_validation_failed"
    assert payload["simulation_status"] == "unknown"
    assert payload["spec_pass"] is None
    assert read_evidenced_metrics(run_dir) == payload


def test_passive_candidate_injected_remote_config_uses_provided_runner(
    tmp_path: Path, monkeypatch
) -> None:
    class DeniedRunner(_FakeRunner):
        fail_mkdir = True

    class UnexpectedRunner:
        def __init__(self, config: RemoteCadenceConfig) -> None:
            raise AssertionError("the default remote config must not be loaded")

    monkeypatch.setattr(candidate_module, "RemoteRunner", DeniedRunner)
    monkeypatch.setattr(passive_module, "RemoteRunner", UnexpectedRunner)
    runs = tmp_path / "runs"
    runs.mkdir()
    config = RemoteCadenceConfig(
        host="example.test", user="testuser", remote_root="/root/denied",
        command_timeout_seconds=7,
    )
    run_dir, payload = run_passive_candidate(
        tmp_path / "missing.yaml", runs, _spec(), _candidate(),
        run_id="run005", remote_config=config,
    )
    assert payload["status"] == "mkdir_failed"
    assert payload["timeout_seconds"] == 7
    assert read_evidenced_metrics(run_dir) == payload
