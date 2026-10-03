import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_three_stage import (
    _ARTIFACTS, audit_teaching_three_stage, extract_teaching_three_stage,
)
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.schemas import Candidate, Spec


def _archive() -> Path:
    path = Path("results/runs/teaching_three_stage/probe_7eecbf34a74a")
    if not path.is_dir():
        pytest.skip("private Cadence three-stage probe archive is unavailable")
    return path


def _copy(tmp_path: Path) -> Path:
    source = _archive()
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _rehash(path: Path) -> None:
    manifest = path / "evidence_manifest.json"
    previous = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in previous["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(path, artifacts)), encoding="utf-8")


def test_real_three_stage_probe_is_audited() -> None:
    result = audit_teaching_three_stage(_archive())
    assert result["points"] == 161
    assert result["not_lna_result"] is True


def test_rehashed_metrics_change_is_rejected(tmp_path: Path) -> None:
    archive = _copy(tmp_path)
    path = archive / "metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["s21_db"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash(archive)
    with pytest.raises(ValueError, match="metrics differ from raw"):
        audit_teaching_three_stage(archive)


def test_rehashed_remote_netlist_change_is_rejected(tmp_path: Path) -> None:
    archive = _copy(tmp_path)
    path = archive / "remote_teaching_three_stage_probe.scs"
    path.write_text(path.read_text(encoding="ascii").replace("r=1787", "r=50"), encoding="ascii")
    _rehash(archive)
    with pytest.raises(ValueError, match="remotely executed input differs"):
        audit_teaching_three_stage(archive)


def test_rehashed_mixed_reference_change_is_rejected(tmp_path: Path) -> None:
    archive = _copy(tmp_path)
    path = archive / "teaching_three_stage_probe.s2p"
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace("1787.000000", "50.000000", 1), encoding="utf-8")
    _rehash(archive)
    with pytest.raises(ValueError, match="port references differ"):
        audit_teaching_three_stage(archive)


def test_rehashed_waveform_change_is_rejected(tmp_path: Path) -> None:
    archive = _copy(tmp_path)
    path = archive / "waveforms.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    fields = lines[1].split(",")
    fields[3] = str(float(fields[3]) + 1)
    lines[1] = ",".join(fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash(archive)
    with pytest.raises(ValueError, match="waveform CSV differs"):
        audit_teaching_three_stage(archive)


def _candidate_archive(tmp_path: Path) -> Path:
    archive = _copy(tmp_path)
    status_path = archive / "probe_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    candidate = Candidate(
        "S1_seed0_teach3_0", "S1", 0, [],
        passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 1.0},
        status="teaching_three_stage_diagnostic",
    )
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    status.update({
        "candidate": candidate.to_dict(), "spec": asdict(spec),
        "seed": 0, "timeout_seconds": 180,
    })
    write_json(status_path, status)
    write_json(archive / "candidate.json", candidate.to_dict())
    rows, metrics = extract_teaching_three_stage(archive)
    for name in ("metrics.json", "waveforms.csv", "evidence_manifest.json"):
        (archive / name).unlink()
    write_active_oa_results(archive, rows, metrics)
    write_evidence_manifest(archive, {**_ARTIFACTS, "candidate": "candidate.json"})
    return archive


def test_three_stage_candidate_archive_binds_spec_and_source(tmp_path: Path) -> None:
    archive = _candidate_archive(tmp_path)
    assert audit_teaching_three_stage(archive)["status"] == "verified"
    metrics = json.loads((archive / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["candidate"]["passive_params"] == {
        "output_tune_ff": 0.0, "output_secondary_nh": 1.0,
    }
    assert metrics["spec"]["id"] == "S1"
    assert metrics["not_lna_result"] is True and metrics["spec_pass"] is None


def test_three_stage_candidate_parameter_rehash_cannot_hide_wrong_netlist(tmp_path: Path) -> None:
    archive = _candidate_archive(tmp_path)
    status_path = archive / "probe_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["output_secondary_nh"] = 4.1
    status["candidate"]["passive_params"]["output_secondary_nh"] = 4.1
    write_json(status_path, status)
    write_json(archive / "candidate.json", status["candidate"])
    with pytest.raises(ValueError, match="remotely executed input differs"):
        extract_teaching_three_stage(archive)


def test_protocol_v2_real_archive_and_rehashed_remote_path_tamper(tmp_path: Path) -> None:
    source = Path(
        "results/runs/teaching_three_stage_candidates/S1/seed0/"
        "S1_seed0_teach3_dispatch_v2/20260927T183521Z_c14f4fad"
    )
    if not source.is_dir():
        pytest.skip("private protocol-v2 three-stage source is unavailable")
    assert audit_teaching_three_stage(source)["status"] == "verified"
    copied = tmp_path / source.name
    shutil.copytree(source, copied)
    plan_path = copied / "dispatch_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["remote_dir"] += "_wrong"
    write_json(plan_path, plan)
    _rehash(copied)
    with pytest.raises(ValueError, match="planned remote dispatch differs"):
        audit_teaching_three_stage(copied)


def test_protocol_v3_real_archive_and_rehashed_memory_gate_tamper(tmp_path: Path) -> None:
    source = Path(
        "results/runs/teaching_three_stage_candidates/S1/seed0/"
        "S1_seed0_teach3_exclusive_v3/20260927T184352Z_58c45fbb"
    )
    if not source.is_dir():
        pytest.skip("private protocol-v3 three-stage source is unavailable")
    assert audit_teaching_three_stage(source)["status"] == "verified"
    copied = tmp_path / source.name
    shutil.copytree(source, copied)
    plan_path = copied / "dispatch_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["host_available_gib_before"] += 1.0
    write_json(plan_path, plan)
    _rehash(copied)
    with pytest.raises(ValueError, match="planned remote dispatch differs"):
        audit_teaching_three_stage(copied)
