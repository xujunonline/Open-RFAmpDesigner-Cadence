from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.agents.remote_identity import remote_identity
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments import probe_sfe1131 as module
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_PATH = "/private/models/../models/./scale.scs"
_NORMALIZED = "/private/models/scale.scs"
_WARNING = (
    "WARNING (SFE-1131): Scope option `scalefactor' specified with scope `TopCircuit' "
    "at line `2' has also been specified at line `5' in file `" + _PATH + "'. "
    "As a result, the last specified value will be used for simulation."
)


class FakeRunner:
    def __init__(self, *, value: float = 0.9, wrong_path: bool = False) -> None:
        self.config = RemoteCadenceConfig(host="example.org", user="student")
        self.value = value
        self.wrong_path = wrong_path
        self.calls: list[list[str]] = []

    def run_remote(self, command: list[str], **_: object) -> CommandResult:
        self.calls.append(command)
        items = json.loads(command[-1])
        assert items == [{"path": _NORMALIZED, "line": 5}]
        report = [{
            "line": 5, "value": self.value,
            "path_sha256": "f" * 64 if self.wrong_path else hashlib.sha256(_NORMALIZED.encode()).hexdigest(),
            "model_sha256": "a" * 64,
        }]
        return CommandResult("ssh", (), 0, json.dumps(report), "")


def _fixture(root: Path, *, extra_warning: bool = False) -> tuple[Path, Path, Path, Path]:
    run_dir = root / "S1/seed0/S1_seed0_oa_diag/mock_run"
    run_dir.mkdir(parents=True)
    trace = root / "trace"
    trace.mkdir()
    (trace / "agent_events.jsonl").write_text(
        json.dumps({"action": "RunStarted", "remote_identity_sha256": "b" * 64}) + "\n"
        + json.dumps({"action": "RefineCandidate", "candidate_id": "S1_seed0_oa_diag",
                      "run_id": "mock_run"}) + "\n", encoding="utf-8",
    )
    log = _WARNING + "\n    scalefactor = 0.9\n"
    if extra_warning:
        log += "WARNING (SFE-1131): other unrecognized format\n"
    (run_dir / "spectre.log").write_text(log, encoding="utf-8")
    (run_dir / "evidence_manifest.json").write_text("mock manifest", encoding="utf-8")
    return run_dir, trace, root / "report", root / "template.scs"


def _trusted_mocks(monkeypatch: pytest.MonkeyPatch, root: Path, runner: FakeRunner) -> None:
    monkeypatch.setattr(module, "_PRIVATE_ROOT", root)
    monkeypatch.setattr(module, "inspect_journal", lambda *a, **k: SimpleNamespace(
        disposition="complete", remote_identity_verified=True,
        candidate_bindings_verified=True, spec_verified=True,
        candidate_snapshots_verified=True, spec_id="S1", seed=0,
    ))
    monkeypatch.setattr(module, "read_remote_identity_snapshot", lambda *a: remote_identity(runner.config))
    monkeypatch.setattr(module, "audit_active_diagnostic_candidate", lambda *a, **k: {
        "not_lna_result": True, "spec_pass": None,
    })


@pytest.mark.parametrize(("value", "expected"), [
    (0.9, "observed_assignments_match_effective_value"),
    (0.7, "observed_scale_conflict"),
])
def test_model_scale_probe_redacts_paths_and_never_qualifies_pdk(
    monkeypatch: pytest.MonkeyPatch, value: float, expected: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="scale_probe_test_", dir=_PRIVATE_ROOT.resolve()) as name:
        run_dir, trace, output_dir, template = _fixture(Path(name))
        runner = FakeRunner(value=value)
        _trusted_mocks(monkeypatch, Path(name), runner)
        report = module.probe_sfe1131(
            run_dir, trace, output_dir, runner, template=template, template_sha256="a" * 64,
        )
        assert report["status"] == expected and report["warning_count"] == 1
        assert report["model_warning_resolved"] is False
        assert report["pdk_qualification"] is False and report["spec_pass"] is None
        raw = (output_dir / "scale_probe.json").read_text(encoding="utf-8")
        assert _PATH not in raw and _NORMALIZED not in raw
        assert len(runner.calls) == 1


@pytest.mark.parametrize("fault", ["extra_warning", "wrong_path", "nonfinite"])
def test_scale_probe_rejects_uncertain_evidence_without_report(
    monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="scale_probe_test_", dir=_PRIVATE_ROOT.resolve()) as name:
        run_dir, trace, output_dir, template = _fixture(Path(name), extra_warning=fault == "extra_warning")
        runner = FakeRunner(value=float("nan") if fault == "nonfinite" else 0.9,
                            wrong_path=fault == "wrong_path")
        _trusted_mocks(monkeypatch, Path(name), runner)
        with pytest.raises(ValueError):
            module.probe_sfe1131(
                run_dir, trace, output_dir, runner, template=template, template_sha256="a" * 64,
            )
        assert not output_dir.exists()
        if fault == "extra_warning":
            assert runner.calls == []


def test_scale_probe_rejects_changed_remote_before_reading_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory(prefix="scale_probe_test_", dir=_PRIVATE_ROOT.resolve()) as name:
        run_dir, trace, output_dir, template = _fixture(Path(name))
        runner = FakeRunner()
        _trusted_mocks(monkeypatch, Path(name), runner)
        monkeypatch.setattr(module, "read_remote_identity_snapshot", lambda *a: remote_identity(
            RemoteCadenceConfig(host="different.example.org", user="student")
        ))
        with pytest.raises(ValueError, match="endpoint differs"):
            module.probe_sfe1131(
                run_dir, trace, output_dir, runner, template=template, template_sha256="a" * 64,
            )
        assert runner.calls == [] and not output_dir.exists()


def test_scale_probe_rejects_model_version_change_within_one_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory(prefix="scale_probe_test_", dir=_PRIVATE_ROOT.resolve()) as name:
        run_dir, trace, output_dir, template = _fixture(Path(name))
        with (run_dir / "spectre.log").open("a", encoding="utf-8") as stream:
            stream.write(_WARNING.replace("line `5'", "line `6'") + "\n")

        class ChangingRunner(FakeRunner):
            def run_remote(self, command: list[str], **_: object) -> CommandResult:
                self.calls.append(command)
                items = json.loads(command[-1])
                assert [item["line"] for item in items] == [5, 6]
                digest = hashlib.sha256(_NORMALIZED.encode()).hexdigest()
                report = [
                    {"line": line, "value": 0.9, "path_sha256": digest,
                     "model_sha256": token * 64}
                    for line, token in ((5, "a"), (6, "b"))
                ]
                return CommandResult("ssh", (), 0, json.dumps(report), "")

        runner = ChangingRunner()
        _trusted_mocks(monkeypatch, Path(name), runner)
        with pytest.raises(ValueError, match="model file changed"):
            module.probe_sfe1131(
                run_dir, trace, output_dir, runner, template=template,
                template_sha256="a" * 64,
            )
        assert not output_dir.exists()
