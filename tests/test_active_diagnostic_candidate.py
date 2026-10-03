from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.agents.uncertainty import RemoteEvaluationUncertain
from orfadc.experiments import run_active_diagnostic_candidate as active_module
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _candidate() -> Candidate:
    return Candidate("active01", "S1", 0, [],
                     active_params={"rd_ohm": 120.0, "vbias_v": 0.67})


def _template(runs: Path) -> tuple[Path, str]:
    template = runs / "private_oa_netlist.scs"
    template.write_text(
        "simulator lang=spectre\n"
        "PORT1 (input 0) port r=50 num=1 type=sine\n"
        "PORT2 (output 0) port r=50 num=2 type=sine\n"
        "VDD (vdd 0) vsource dc=1.1 type=dc\n"
        "VBIAS (bias 0) vsource dc=0.65 type=dc\n"
        "RD (vdd out) resistor r=100\n"
        "dcOp dc write=\"spectre.dc\"\n"
        "sp sp ports=[PORT1 PORT2] start=100M stop=20G donoise=yes\n",
        encoding="ascii",
    )
    return template, hashlib.sha256(template.read_bytes()).hexdigest()


def _result(ok: bool = True) -> CommandResult:
    return CommandResult("fake", (), 0 if ok else 2, "", "")


class _FakeRunner:
    def ensure_remote_dir(self, remote_dir: str) -> CommandResult:
        return _result()

    def upload(self, local_path: Path, remote_path: str) -> CommandResult:
        return _result()

    def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
        return _result()

    def download(self, remote_path: str, local_path: Path) -> CommandResult:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        content = "spectre completes with 0 errors, 1 warning\n" if local_path.name == "spectre.log" else "raw\n"
        local_path.write_text(content, encoding="ascii")
        return _result()


def _config() -> RemoteCadenceConfig:
    return RemoteCadenceConfig("example.test", "testuser", command_timeout_seconds=60)


def test_active_diagnostic_success_archive_is_never_lna_pass(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)

    def fake_extract(psf_dir: Path, **kwargs: object) -> tuple[list[dict], dict]:
        return ([{"freq_hz": 1e10, "freq_ghz": 10.0, "s11_db": -1.0,
                  "s21_db": -2.0, "s22_db": -3.0, "nf_db": 4.0, "nfmin_db": 2.0}], {
            "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
            "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
            "not_lna_result": True, "spec_pass": None, "run_id": kwargs["run_id"],
            "metrics": {"s21_db": -2.0}, "spec": None, "candidate": None,
        })

    monkeypatch.setattr(active_module, "extract_active_oa", fake_extract)
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run001",
        remote_config=_config(), runner=_FakeRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "ok_with_warnings"
    assert payload["source_template_sha256"] == digest
    assert payload["spec_pass"] is None and payload["not_lna_result"] is True
    assert read_evidenced_metrics(run_dir) == payload
    rendered = (run_dir / "netlist.scs").read_text(encoding="ascii")
    assert "dc=0.67000000000000004" in rendered
    assert "r=120" in rendered
    assert b"\r\r\n" not in (run_dir / "netlist.scs").read_bytes()
    assert (run_dir / "netlist.scs").read_bytes().count(b"\r\n") == template.read_bytes().count(b"\r\n")
    with pytest.raises(FileExistsError):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="run001",
            remote_config=_config(), runner=_FakeRunner(), memory_provider=lambda: 8.0,
        )


def test_active_diagnostic_spectre_failure_is_archived(tmp_path: Path, monkeypatch) -> None:
    class FailingRunner(_FakeRunner):
        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            return _result(False)

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run002",
        remote_config=_config(), runner=FailingRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "spectre_failed"
    assert payload["failure_code"] == "spectre_error"
    assert payload["simulation_status"] == "failed"
    assert payload["spec_pass"] is None
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_download_failure_is_not_a_simulation_result(
    tmp_path: Path, monkeypatch
) -> None:
    class MissingRawRunner(_FakeRunner):
        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            if local_path.name == "sp.noise.sp":
                return _result(False)
            return super().download(remote_path, local_path)

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run003",
        remote_config=_config(), runner=MissingRawRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "download_failed"
    assert payload["simulation_status"] == "unknown"
    assert payload["failure_code"] == "result_download_failed"
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_raw_parse_failure_is_archived(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run005",
        remote_config=_config(), runner=_FakeRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "result_parse_failed"
    assert payload["failure_code"] == "result_parse_failed"
    assert payload["simulation_status"] == "ok"
    assert payload["source"] == "cadence_spectre"
    assert payload["spec_pass"] is None
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_labels_license_related_timeout(tmp_path: Path, monkeypatch) -> None:
    class LicenseWaitRunner(_FakeRunner):
        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            return CommandResult("fake", (), 124, "", "waiting for license\n")

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run006",
        remote_config=_config(), runner=LicenseWaitRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "spectre_failed"
    assert payload["failure_code"] == "license_related_timeout"
    assert read_evidenced_metrics(run_dir) == payload


@pytest.mark.parametrize("returncode", [124, 255])
def test_planned_active_diagnostic_preserves_uncertain_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int,
) -> None:
    class UncertainRunner(_FakeRunner):
        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            return CommandResult("fake", (), returncode, "controller output", "controller error")

        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            pytest.fail("uncertain dispatch must not download results")

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    with pytest.raises(RemoteEvaluationUncertain):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="planned01",
            remote_config=_config(), runner=UncertainRunner(), memory_provider=lambda: 8.0,
            preserve_uncertain_dispatch=True,
        )
    run_dir = runs / "S1" / "seed0" / "active01" / "planned01"
    assert (run_dir / "netlist.scs").is_file()
    assert (run_dir / "candidate.json").is_file()
    assert json.loads((run_dir / "control_attempt/dispatch.json").read_text())["returncode"] == returncode
    assert not (run_dir / "metrics.json").exists()
    assert not (run_dir / "evidence_manifest.json").exists()
    assert not (run_dir / "spectre.stdout.log").exists()
    assert not (run_dir / "spectre.stderr.log").exists()


def test_planned_active_diagnostic_preserves_dispatch_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DisconnectedRunner(_FakeRunner):
        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            raise OSError("private network detail")

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    with pytest.raises(RemoteEvaluationUncertain, match="uncertain") as captured:
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="planned02",
            remote_config=_config(), runner=DisconnectedRunner(), memory_provider=lambda: 8.0,
            preserve_uncertain_dispatch=True,
        )
    assert "private" not in str(captured.value)
    run_dir = runs / "S1" / "seed0" / "active01" / "planned02"
    assert (run_dir / "candidate.json").is_file()
    assert not (run_dir / "evidence_manifest.json").exists()


def test_active_diagnostic_unclean_log_is_downgraded(tmp_path: Path, monkeypatch) -> None:
    class UncleanLogRunner(_FakeRunner):
        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            result = super().download(remote_path, local_path)
            if local_path.name == "spectre.log":
                local_path.write_text("SPECTRE-25 termination failure\n", encoding="ascii")
            return result

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    monkeypatch.setattr(active_module, "extract_active_oa", lambda *a, **k: (
        [{"freq_hz": 1e10, "freq_ghz": 10.0, "s11_db": -1.0,
          "s21_db": -2.0, "s22_db": -3.0, "nf_db": 4.0, "nfmin_db": 2.0}],
        {"schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
         "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
         "not_lna_result": True, "spec_pass": None, "run_id": k["run_id"],
         "metrics": {"s21_db": -2.0}, "spec": None, "candidate": None},
    ))
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="run004",
        remote_config=_config(), runner=UncleanLogRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == "evidence_failed"
    assert payload["failure_code"] == "evidence_validation_failed"
    assert payload["simulation_status"] == "unknown"
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_rejects_template_changes_and_unsafe_paths(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    assert "r=120" in active_module.render_active_diagnostic_netlist(_candidate(), template, digest)
    template.write_text(template.read_text(encoding="ascii") + "extra\n", encoding="ascii")
    with pytest.raises(ValueError, match="hash changed"):
        active_module.render_active_diagnostic_netlist(_candidate(), template, digest)
    outside = tmp_path / "outside.scs"
    outside.write_text("test", encoding="ascii")
    with pytest.raises(ValueError, match="private results"):
        active_module.render_active_diagnostic_netlist(_candidate(), outside, digest)


def test_active_diagnostic_uploads_required_ade_companion(tmp_path: Path, monkeypatch) -> None:
    class RecordingRunner(_FakeRunner):
        def __init__(self) -> None:
            self.uploaded: list[str] = []

        def upload(self, local_path: Path, remote_path: str) -> CommandResult:
            self.uploaded.append(local_path.name)
            return _result()

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, _ = _template(runs)
    template.write_text(
        template.read_text(encoding="ascii") + 'include "ade_e.scs"\n', encoding="ascii"
    )
    (runs / "ade_e.scs").write_text("// private ADE settings\n", encoding="ascii")
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    runner = RecordingRunner()
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="with_ade",
        remote_config=_config(), runner=runner, memory_provider=lambda: 8.0,
    )
    assert runner.uploaded == ["netlist.scs", "ade_e.scs"]
    assert (run_dir / "ade_e.scs").read_text(encoding="ascii") == "// private ADE settings\n"
    assert "ade_companion" in json.loads(
        (run_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )["artifacts"]
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_companion_upload_failure_is_archived(tmp_path: Path, monkeypatch) -> None:
    class FailingCompanionRunner(_FakeRunner):
        def upload(self, local_path: Path, remote_path: str) -> CommandResult:
            return _result(local_path.name != "ade_e.scs")

        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            raise AssertionError("Spectre must not run after companion upload failure")

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, _ = _template(runs)
    template.write_text(
        template.read_text(encoding="ascii") + 'include "ade_e.scs"\n', encoding="ascii"
    )
    (runs / "ade_e.scs").write_text("// private ADE settings\n", encoding="ascii")
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    run_dir, payload = active_module.run_active_diagnostic_candidate(
        tmp_path / "unused.yaml", runs, _spec(), _candidate(),
        template=template, template_sha256=digest, run_id="ade_upload_failed",
        remote_config=_config(), runner=FailingCompanionRunner(), memory_provider=lambda: 8.0,
    )
    assert payload["status"] == payload["failure_code"] == "upload_failed"
    assert read_evidenced_metrics(run_dir) == payload


def test_active_diagnostic_missing_companion_fails_before_run_reservation(
    tmp_path: Path, monkeypatch
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, _ = _template(runs)
    template.write_text(
        template.read_text(encoding="ascii") + 'include "ade_e.scs"\n', encoding="ascii"
    )
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="companion.*missing"):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="missing_ade",
            remote_config=_config(), runner=_FakeRunner(), memory_provider=lambda: 8.0,
        )
    assert not (runs / "S1").exists()


def test_active_diagnostic_memory_gate_blocks_before_reserving_run(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    with pytest.raises(ValueError, match="memory below"):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="blocked",
            remote_config=_config(), runner=_FakeRunner(),
            memory_provider=lambda: 1.27,
        )
    assert not (runs / "S1").exists()
    with pytest.raises(ValueError, match="memory reading"):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="invalid",
            remote_config=_config(), runner=_FakeRunner(),
            memory_provider=lambda: float("nan"),
        )
    assert not (runs / "S1").exists()
    with pytest.raises(ValueError, match="resource floor"):
        active_module.run_active_diagnostic_candidate(
            tmp_path / "unused.yaml", runs, _spec(), _candidate(),
            template=template, template_sha256=digest, run_id="bypass",
            remote_config=_config(), runner=_FakeRunner(),
            minimum_host_free_gb=0, memory_provider=lambda: 8.0,
        )
    assert not (runs / "S1").exists()


@pytest.mark.parametrize("key,value", [("rd_ohm", 1), ("vbias_v", 1), ("vbias_v", "0.65")])
def test_active_diagnostic_rejects_out_of_range_candidate(
    tmp_path: Path, monkeypatch, key: str, value: object
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(active_module, "_PRIVATE_ROOT", runs)
    template, digest = _template(runs)
    candidate = _candidate()
    candidate.active_params[key] = value
    with pytest.raises(ValueError, match=key):
        active_module.render_active_diagnostic_netlist(candidate, template, digest)
