from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_pdk_rf_source_termination import audit_pdk_rf_source_termination
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_RUN = _PRIVATE_ROOT / "pdk_rf_source_termination" / "20260927T071510Z_5e906f78"


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private authorized source-termination evidence is unavailable")
    return _RUN


def test_real_source_termination_predicts_independent_spectre_run() -> None:
    assert audit_pdk_rf_source_termination(_private()) == {
        "status": "verified", "points": 161, "not_lna_result": True,
    }
    report = json.loads((_RUN / "metrics.json").read_text(encoding="utf-8"))
    assert report["max_abs_nf_prediction_delta_db"] < 1e-6
    assert report["max_abs_gain_prediction_delta_db"] < 1e-6
    assert report["terminated_worst_nf_db"] < report["baseline_worst_nf_db"]
    assert report["physical_qualification"] is False and report["spec_pass"] is None


@pytest.mark.parametrize("mutation", (
    "netlist", "noise", "sp", "touchstone_s11", "status", "summary", "csv",
))
def test_source_termination_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_source_termination_", dir=_PRIVATE_ROOT.resolve()) as root:
        run_dir = Path(root) / source.name
        shutil.copytree(source, run_dir)
        if mutation == "netlist":
            path = run_dir / "netlist.scs"
            raw = path.read_bytes()
            assert b"PORT1 (in 0) port r=100 num=1 type=sine" in raw
            path.write_bytes(raw.replace(b"port r=100 num=1", b"port r=75 num=1"))
        elif mutation == "noise":
            path = run_dir / "sp.noise.sp"
            raw = path.read_bytes()
            index = raw.index(b'"Gopt" ', raw.index(b"VALUE"))
            path.write_bytes(raw[:index] + raw[index:].replace(b'"Gopt" ', b'"Gopt" 9', 1))
        elif mutation == "sp":
            path = run_dir / "sp.sp"
            raw = path.read_bytes()
            index = raw.index(b'"s21" (', raw.index(b"VALUE"))
            path.write_bytes(raw[:index] + raw[index:].replace(b'"s21" (', b'"s21" (9', 1))
        elif mutation == "touchstone_s11":
            path = run_dir / "source_termination.s2p"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            index = next(index for index, line in enumerate(lines) if line.startswith("8.000000000000000e+09"))
            values = lines[index].split()
            assert len(values) == 9
            values[1] = "9"
            lines[index] = " ".join(values) + "\n"
            path.write_text("".join(lines), encoding="utf-8")
        elif mutation == "status":
            path = run_dir / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["physical_qualification"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "summary":
            path = run_dir / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["terminated_worst_nf_db"] -= 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = run_dir / "prediction.csv"
            raw = path.read_text(encoding="utf-8")
            path.write_text(raw.replace("nf_100_pred_db", "invented_nf_db", 1), encoding="utf-8")
        manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
        artifacts = {key: entry["path"] for key, entry in manifest["artifacts"].items()}
        (run_dir / "evidence_manifest.json").write_text(
            json.dumps(build_evidence_manifest(run_dir, artifacts)), encoding="utf-8",
        )
        with pytest.raises(ValueError):
            audit_pdk_rf_source_termination(run_dir)


def test_false_source_termination_spec_pass_cannot_build_manifest() -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_source_pass_", dir=_PRIVATE_ROOT.resolve()) as root:
        run_dir = Path(root) / source.name
        shutil.copytree(source, run_dir)
        path = run_dir / "metrics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_pass"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            build_evidence_manifest(run_dir, {"metrics": "metrics.json"})
