import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.cadence.remote_runner import load_remote_config
from dataclasses import replace
from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments import recover_teaching_three_stage_candidate as module
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage


_SOURCE = Path(
    "results/runs/teaching_three_stage_candidates/S1/seed0/"
    "S1_seed0_teach3_dispatch_v2/20260927T183521Z_c14f4fad"
)
_RECOVERED = Path(
    "results/runs/teaching_three_stage_candidates/S1/seed0/"
    "S1_seed0_teach3_lostreply_v3/20260927T184116Z_0cb68043"
)


def _pending(tmp_path: Path) -> Path:
    if not _SOURCE.is_dir() or not Path("config/remote_cadence.local.yaml").is_file():
        pytest.skip("private protocol-v2 Spectre source or remote config is unavailable")
    run_dir = tmp_path / "runs/S1/seed0/S1_seed0_teach3_dispatch_v2" / _SOURCE.name
    run_dir.mkdir(parents=True)
    for name in ("netlist.scs", "teaching_mos1_model.scs", "candidate.json",
                 "dispatch_plan.json", "agent_remote.json"):
        shutil.copy2(_SOURCE / name, run_dir / name)
    plan_path = run_dir / "dispatch_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    original = json.loads((_SOURCE / "probe_status.json").read_text(encoding="utf-8"))
    plan["host_available_gib_before"] = original["host_available_gib_before"]
    write_json(plan_path, plan)
    write_json(run_dir / "dispatch_uncertain.json", {
        "schema_version": 1, "status": "unverified_remote_dispatch",
        "run_id": run_dir.name, "safe_to_retry": False,
        "not_lna_result": True, "spec_pass": None,
    })
    return run_dir


class _RemoteFixture:
    def __init__(self, *, active: bool = False, corrupt_hash: bool = False,
                 corrupt_download: bool = False, clean_log: bool = True) -> None:
        self.config = load_remote_config(Path("config/remote_cadence.local.yaml"))
        self.active = active
        self.corrupt_hash = corrupt_hash
        self.corrupt_download = corrupt_download
        self.clean_log = clean_log
        self.commands = []
        self.hash_calls = 0

    def run_remote(self, command, *, cwd=None, timeout_seconds=None):
        self.commands.append((tuple(command), cwd))
        if command[0] == "bash" and cwd is None:
            return SimpleNamespace(
                ok=True,
                stdout=f"directory=present\nactive={int(self.active)}\nlog=1\nsp=1\nnoise=1\n",
            )
        if command[0] == "bash":
            return SimpleNamespace(ok=True, stdout="")
        if command[0] == "sha256sum":
            self.hash_calls += 1
            lines = []
            for remote in command[2:]:
                local = module._REMOTE_FILES[remote]
                digest = hashlib.sha256((_SOURCE / local).read_bytes()).hexdigest()
                if self.corrupt_hash and self.hash_calls == 2 and remote == "psf/sp.sp":
                    digest = "0" * 64
                lines.append(f"{digest}  {remote}")
            return SimpleNamespace(ok=True, stdout="\n".join(lines) + "\n")
        if command[0] == "grep":
            return SimpleNamespace(ok=self.clean_log, stdout="")
        raise AssertionError(f"unexpected remote command: {command[0]}")

    def download(self, remote_path, destination):
        remote = next(name for name in module._REMOTE_FILES if remote_path.endswith("/" + name))
        shutil.copy2(_SOURCE / module._REMOTE_FILES[remote], destination)
        if self.corrupt_download and remote == "psf/sp.sp":
            with destination.open("ab") as stream:
                stream.write(b"changed")
        return SimpleNamespace(ok=True)


def test_recovery_adopts_real_raw_data_without_dispatch_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _pending(tmp_path)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    runner = _RemoteFixture()
    report = module.recover_teaching_three_stage_candidate(run_dir, runner)
    assert report["status"] == "verified_recovered"
    assert audit_teaching_three_stage(run_dir)["status"] == "verified"
    assert json.loads((run_dir / "probe_status.json").read_text(encoding="utf-8"))[
        "dispatch_protocol_version"
    ] == 4
    assert (run_dir / "dispatch_uncertain.json").is_file()
    assert all(command[0][0] != "spectre" for command in runner.commands)
    assert module.recover_teaching_three_stage_candidate(run_dir, runner)["status"] == "already_recovered"


@pytest.mark.parametrize("active,corrupt_hash", [(True, False), (False, True)])
def test_recovery_rejects_active_or_changed_remote_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool, corrupt_hash: bool,
) -> None:
    run_dir = _pending(tmp_path)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    runner = _RemoteFixture(active=active, corrupt_hash=corrupt_hash)
    with pytest.raises(ValueError, match="active|changed"):
        module.recover_teaching_three_stage_candidate(run_dir, runner)
    assert not (run_dir / "metrics.json").exists()
    assert not (run_dir / "evidence_manifest.json").exists()
    assert (run_dir / "dispatch_uncertain.json").is_file()


def test_pending_recovery_refuses_changed_remote_identity_before_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _pending(tmp_path)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    runner = _RemoteFixture()
    runner.config = replace(runner.config, host="changed.invalid")
    with pytest.raises(ValueError, match="identity differs"):
        module.recover_teaching_three_stage_candidate(run_dir, runner)
    assert runner.commands == []


@pytest.mark.parametrize("corrupt_download,clean_log", [(True, True), (False, False)])
def test_recovery_refuses_download_drift_or_missing_clean_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    corrupt_download: bool, clean_log: bool,
) -> None:
    run_dir = _pending(tmp_path)
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    runner = _RemoteFixture(corrupt_download=corrupt_download, clean_log=clean_log)
    with pytest.raises(ValueError, match="differs|clean terminal"):
        module.recover_teaching_three_stage_candidate(run_dir, runner)
    assert not (run_dir / "metrics.json").exists()
    assert not (run_dir / "evidence_manifest.json").exists()
    assert (run_dir / "dispatch_uncertain.json").is_file()


def test_real_lost_reply_recovery_reaudits_and_rejects_changed_source_hash(
    tmp_path: Path,
) -> None:
    if not _RECOVERED.is_dir():
        pytest.skip("private controlled lost-reply Spectre recovery is unavailable")
    assert audit_teaching_three_stage(_RECOVERED)["status"] == "verified"
    probe = json.loads((_RECOVERED / "probe_status.json").read_text(encoding="utf-8"))
    assert probe["spectre_returncode"] is None
    assert probe["dispatch_protocol_version"] == 4
    assert (_RECOVERED / "dispatch_uncertain.json").is_file()
    copied = tmp_path / _RECOVERED.name
    shutil.copytree(_RECOVERED, copied)
    provenance_path = copied / "recovery_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["remote_artifacts_sha256"]["psf/sp.sp"] = "0" * 64
    write_json(provenance_path, provenance)
    manifest_path = copied / "evidence_manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {key: item["path"] for key, item in original["artifacts"].items()}
    write_json(manifest_path, build_evidence_manifest(copied, artifacts))
    with pytest.raises(ValueError, match="recovery provenance differs"):
        audit_teaching_three_stage(copied)
