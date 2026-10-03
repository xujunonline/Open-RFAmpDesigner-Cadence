from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate


_ARCHIVE = Path("results/runs/S1/seed0/S1_seed0_oa_diag/20260927T005554Z_9f36c477")
_TEMPLATE = Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs")
_TEMPLATE_SHA = "9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814"


def _private_archive() -> None:
    if not _ARCHIVE.is_dir() or not _TEMPLATE.is_file():
        pytest.skip("private OA diagnostic source archive is unavailable")


def _rehash(run_dir: Path) -> None:
    path = run_dir / "evidence_manifest.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    artifacts = {key: item["path"] for key, item in old["artifacts"].items()}
    path.write_text(json.dumps(build_evidence_manifest(run_dir, artifacts)), encoding="utf-8")


def test_real_active_archive_rebuilds_from_raw_psf() -> None:
    _private_archive()
    result = audit_active_diagnostic_candidate(_ARCHIVE, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA)
    assert result["points"] == 47
    assert result["status"] == "ok_with_warnings"
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize("artifact", ["metrics.json", "netlist.scs"])
def test_rehashed_active_archive_tamper_is_rejected(tmp_path: Path, artifact: str) -> None:
    _private_archive()
    copied = tmp_path / _ARCHIVE.name
    shutil.copytree(_ARCHIVE, copied)
    path = copied / artifact
    if artifact == "metrics.json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["metrics"]["nf_db"] += 0.5
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_bytes(path.read_bytes() + b"\n// altered archive\n")
    _rehash(copied)
    with pytest.raises(ValueError, match="differs"):
        audit_active_diagnostic_candidate(copied, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA)


def _recovered_copy(tmp_path: Path) -> Path:
    _private_archive()
    copied = tmp_path / _ARCHIVE.name
    shutil.copytree(_ARCHIVE, copied)
    manifest_path = copied / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {key: item["path"] for key, item in manifest["artifacts"].items()}
    for key in ("stdout", "stderr"):
        (copied / artifacts.pop(key)).unlink()
    payload_path = copied / "metrics.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    files = ("netlist.scs", "ade_e.scs", "spectre.log", "psf/dcOp.dc",
             "psf/sp.sp", "psf/sp.noise.sp")
    provenance = {
        "schema_version": 1, "mode": "remote_quiescent_download_v1",
        "trace_id": "mocktrace001", "spec_id": payload["spec"]["id"],
        "seed": payload["seed"], "candidate_id": payload["candidate"]["candidate_id"],
        "run_id": copied.name, "remote_identity_sha256": "a" * 64,
        "remote_dir_sha256": "b" * 64,
        "remote_artifacts_sha256": {
            name: hashlib.sha256((copied / name).read_bytes()).hexdigest() for name in files
        },
        "controller_stdout_stderr_captured": False,
        "spectre_dispatched_by_recovery": False,
    }
    provenance_path = copied / "recovery_provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    payload["recovery_mode"] = "remote_quiescent_download_v1"
    payload["controller_stdout_stderr_captured"] = False
    payload["recovery_provenance_sha256"] = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    artifacts["recovery_provenance"] = "recovery_provenance.json"
    manifest_path.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    return copied


def test_recovered_copy_uses_real_raw_psf_without_forged_controller_logs(tmp_path: Path) -> None:
    copied = _recovered_copy(tmp_path)
    result = audit_active_diagnostic_candidate(copied, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA)
    assert result["recovery_mode"] == "remote_quiescent_download_v1"
    assert result["controller_stdout_stderr_captured"] is False
    assert result["points"] == 47 and result["spec_pass"] is None


@pytest.mark.parametrize("mutation", ["source_hash", "stdout_claim", "raw_sp"])
def test_recovered_copy_rejects_rehashed_tampering(tmp_path: Path, mutation: str) -> None:
    copied = _recovered_copy(tmp_path)
    provenance_path = copied / "recovery_provenance.json"
    metrics_path = copied / "metrics.json"
    if mutation == "source_hash":
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
        record["remote_artifacts_sha256"]["netlist.scs"] = "f" * 64
        provenance_path.write_text(json.dumps(record), encoding="utf-8")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["recovery_provenance_sha256"] = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    elif mutation == "stdout_claim":
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["controller_stdout_stderr_captured"] = True
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    else:
        path = copied / "psf/sp.sp"
        path.write_bytes(path.read_bytes().replace(b'"s11" (', b'"s11" (9', 1))
    _rehash(copied)
    with pytest.raises(ValueError):
        audit_active_diagnostic_candidate(copied, template=_TEMPLATE, template_sha256=_TEMPLATE_SHA)
