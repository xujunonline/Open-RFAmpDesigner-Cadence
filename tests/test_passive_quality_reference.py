from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments import run_passive_quality_reference as module
from orfadc.experiments.audit_passive_quality_reference import audit_passive_quality_reference


_REAL = Path("results/runs/passive_quality_reference/20260926T203114Z_60899fd6")


def _copy_and_rehash(tmp_path: Path, change) -> Path:
    if not _REAL.is_dir():
        pytest.skip("private Cadence passive quality archive is unavailable")
    copied = tmp_path / _REAL.name
    shutil.copytree(_REAL, copied)
    change(copied)
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    return copied


def test_real_passive_quality_reference_rebuilds_from_spectre() -> None:
    if not _REAL.is_dir():
        pytest.skip("private Cadence passive quality archive is unavailable")
    assert audit_passive_quality_reference(_REAL)["status"] == "verified"
    result = read_evidenced_metrics(_REAL)
    assert result["points"] == 591
    assert result["metrics"]["minimum_q_in_band"] == pytest.approx(16.2524937569)
    assert result["metrics"]["observed_srf_hz"] == pytest.approx(15.9126665654e9)
    assert result["physical_qualification"] is False
    assert result["spec_pass"] is None


def test_rehashed_physical_qualification_claim_is_rejected(tmp_path: Path) -> None:
    def modify(copied: Path) -> None:
        path = copied / "metrics.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["physical_qualification"] = True
        path.write_text(json.dumps(result), encoding="utf-8")

    copied = _copy_and_rehash(tmp_path, modify)
    with pytest.raises(ValueError, match="metrics differ from raw"):
        audit_passive_quality_reference(copied)


def test_rehashed_quality_csv_tamper_is_rejected(tmp_path: Path) -> None:
    def modify(copied: Path) -> None:
        path = copied / "quality.csv"
        rows = path.read_text(encoding="utf-8").splitlines()
        fields = rows[1].split(",")
        fields[5] = str(float(fields[5]) + 1)
        rows[1] = ",".join(fields)
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    copied = _copy_and_rehash(tmp_path, modify)
    with pytest.raises(ValueError, match="CSV differs"):
        audit_passive_quality_reference(copied)


def test_passive_quality_runner_memory_gate_precedes_archive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_passive_quality_reference(tmp_path / "unused.yaml", output)
    assert not output.exists()


def test_passive_quality_runner_remote_failure_is_retained(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 3.0)
    runner = SimpleNamespace(
        config=SimpleNamespace(remote_root="/tmp/teaching_runs"),
        probe=lambda **kwargs: {"status": "ok", "tools": {"spectre": {"found": True}}},
        run_remote=lambda command, **kwargs: SimpleNamespace(ok=True),
        ensure_remote_dir=lambda path: SimpleNamespace(ok=False),
    )
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="remote_directory"):
        module.run_passive_quality_reference(tmp_path / "unused.yaml", output, runner=runner)
    assert (output / "netlist.scs").is_file()
    assert '"status": "remote_directory"' in (output / "failure.json").read_text(encoding="utf-8")
    assert not (output / "metrics.json").exists()
