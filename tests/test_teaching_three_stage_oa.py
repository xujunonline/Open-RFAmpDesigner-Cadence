import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage
from orfadc.experiments.audit_teaching_three_stage_oa import (
    _components, audit_teaching_three_stage_oa,
)


_OA = Path("results/runs/teaching_three_stage_oa/df6db2c10a")
_AUTO_OA = Path("results/runs/teaching_three_stage_oa/20260926T184521Z_4561f7d5")
_DIRECT = Path("results/runs/teaching_three_stage/probe_7eecbf34a74a")


def _archives() -> tuple[Path, Path]:
    if not _OA.is_dir() or not _DIRECT.is_dir():
        pytest.skip("private three-stage Cadence archives are unavailable")
    return _OA, _DIRECT


def _rehash(run_dir: Path) -> None:
    path = run_dir / "evidence_manifest.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    path.write_text(json.dumps(build_evidence_manifest(run_dir, artifacts)), encoding="utf-8")


def test_three_stage_component_canonicalization_rejects_parameter_change() -> None:
    reference = _components(render_teaching_three_stage().decode("ascii"))
    assert len(reference) == 47
    altered = _components(render_teaching_three_stage().decode("ascii").replace(
        "K3 mutual_inductor coupling=0.45", "K3 mutual_inductor coupling=0.4",
    ))
    assert altered != reference


def test_real_three_stage_oa_crosscheck_is_rebuildable() -> None:
    oa, direct = _archives()
    result = audit_teaching_three_stage_oa(oa, direct)
    assert result["status"] == "verified"
    assert result["points"] == 161
    assert result["not_lna_result"] is True


def test_automated_three_stage_oa_crosscheck_is_rebuildable() -> None:
    if not _AUTO_OA.is_dir() or not _DIRECT.is_dir():
        pytest.skip("private automated three-stage Cadence archive is unavailable")
    result = audit_teaching_three_stage_oa(_AUTO_OA, _DIRECT)
    assert result["status"] == "verified"
    assert result["points"] == 161


def test_rehashed_oa_trace_tamper_is_rejected(tmp_path: Path) -> None:
    oa, direct = _archives()
    copied = tmp_path / oa.name
    shutil.copytree(oa, copied)
    path = copied / "ocnprint/s21_real.txt"
    text = path.read_text(encoding="utf-8")
    assert "4.193375203" in text
    path.write_text(text.replace("4.193375203", "4.293375203", 1), encoding="utf-8")
    _rehash(copied)
    with pytest.raises(ValueError, match="complex S differ"):
        audit_teaching_three_stage_oa(copied, direct)


def test_rehashed_oa_netlist_tamper_is_rejected(tmp_path: Path) -> None:
    oa, direct = _archives()
    copied = tmp_path / oa.name
    shutil.copytree(oa, copied)
    path = copied / "netlist.scs"
    text = path.read_text(encoding="utf-8")
    assert "K3 mutual_inductor coupling=0.45" in text
    path.write_text(text.replace("K3 mutual_inductor coupling=0.45", "K3 mutual_inductor coupling=0.4"), encoding="utf-8")
    _rehash(copied)
    with pytest.raises(ValueError, match="netlist components differ"):
        audit_teaching_three_stage_oa(copied, direct)
