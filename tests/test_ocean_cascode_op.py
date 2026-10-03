import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.cadence.ocean_ascii import read_ocean_cascode_op, read_ocean_device_op
from orfadc.experiments.audit_teaching_oa import audit_teaching_oa


_FIELDS = ("id", "vgs", "vds", "vdsat", "gm", "gds", "cgs", "cgd")


def _write_op(path: Path, *, psf: str = "/run/results/psf") -> None:
    values = {
        "M1": (0.00484345091966318, 0.65, 0.301742497591491, 0.2,
               0.0484345091965317, 0.000144, 2.30208886022549e-13, 0.0),
        "M2": (0.00484382946565672, 0.648257502408509, 0.898257502408509,
               0.198257502408509, 0.048864021858462, 0.000141501734140535,
               2.30208886022549e-13, 0.0),
    }
    lines = [f"source_result={psf}"]
    for instance in ("M1", "M2"):
        lines.extend(f"{instance}:{field}={value:.15g}" for field, value in zip(_FIELDS, values[instance], strict=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_cascode_op_parser_requires_exact_fields_and_source(tmp_path: Path) -> None:
    path = tmp_path / "device_op.txt"
    _write_op(path)
    parsed = read_ocean_cascode_op(path, expected_psf="/run/results/psf")
    assert set(parsed) == {"M1", "M2"}
    assert parsed["M2"]["vds"] > parsed["M2"]["vdsat"]
    with pytest.raises(ValueError, match="source or field count"):
        read_ocean_cascode_op(path, expected_psf="/other/psf")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("M2:gm=", "M1:gm="), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        read_ocean_cascode_op(path, expected_psf="/run/results/psf")
    path.write_text(text.replace("M2:gm=0.048864021858462", "M2:gm=nan"), encoding="utf-8")
    with pytest.raises(ValueError, match="nonfinite"):
        read_ocean_cascode_op(path, expected_psf="/run/results/psf")


def test_six_device_op_parser_requires_all_instances(tmp_path: Path) -> None:
    path = tmp_path / "device_op.txt"
    _write_op(path)
    base = path.read_text(encoding="utf-8")
    path.write_text(base + "".join(
        line.replace("M2:", f"M{index}:") + "\n"
        for index in range(3, 7) for line in base.splitlines()[9:]
    ), encoding="utf-8")
    parsed = read_ocean_device_op(
        path, expected_psf="/run/results/psf", instances=tuple(f"M{i}" for i in range(1, 7)),
    )
    assert len(parsed) == 6
    assert parsed["M6"]["gm"] > 0
    with pytest.raises(ValueError, match="instance list"):
        read_ocean_device_op(path, expected_psf="/run/results/psf", instances=("M1", "M1"))
    path.write_text(path.read_text(encoding="utf-8").replace("M6:gm=", "M5:gm="), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        read_ocean_device_op(
            path, expected_psf="/run/results/psf", instances=tuple(f"M{i}" for i in range(1, 7)),
        )


def _grafted_cascode_archive(tmp_path: Path) -> Path:
    original = Path("results/runs/teaching_oa/20260926T165347Z_36f2fb06")
    exported = Path("results/runs/teaching_oa_op_probes/export_b98ebeb52e91/device_op.txt")
    script = Path("circuit/ocean/export_teaching_mos1_oa.ocn")
    if not original.is_dir() or not exported.is_file():
        pytest.skip("private Cadence archives are not part of the public test fixture")
    target = tmp_path / original.name
    shutil.copytree(original, target)
    shutil.copy2(script, target / "export_ocean.ocn")
    shutil.copy2(exported, target / "ocnprint/device_op.txt")
    metrics_path = target / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["oa_device_op_exported"] = True
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    manifest_path = target / "evidence_manifest.json"
    prior = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {key: entry["path"] for key, entry in prior["artifacts"].items()}
    paths["device_op"] = "ocnprint/device_op.txt"
    manifest_path.write_text(json.dumps(build_evidence_manifest(target, paths)), encoding="utf-8")
    return target


def _rehash(root: Path) -> None:
    manifest_path = root / "evidence_manifest.json"
    prior = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {key: entry["path"] for key, entry in prior["artifacts"].items()}
    manifest_path.write_text(json.dumps(build_evidence_manifest(root, paths)), encoding="utf-8")


def test_new_cascode_op_export_is_audited(tmp_path: Path) -> None:
    run_dir = _grafted_cascode_archive(tmp_path)
    result = audit_teaching_oa(run_dir)
    assert result["points_verified"] == 161
    assert result["device_op"]["M1"]["vds"] > result["device_op"]["M1"]["vdsat"]


def test_real_cascode_op_export_is_audited() -> None:
    run_dir = Path("results/runs/teaching_oa/20260926T172320Z_0661fd2f")
    if not run_dir.is_dir():
        pytest.skip("private OA cascode operating-point archive is unavailable")
    result = audit_teaching_oa(run_dir)
    assert result["points_verified"] == 161
    assert set(result["device_op"]) == {"M1", "M2"}


def test_real_vcas_1p05_oa_export_is_audited() -> None:
    run_dir = Path("results/runs/teaching_oa/20260926T174324Z_476a26f3")
    if not run_dir.is_dir():
        pytest.skip("private VCAS 1.05 V OA archive is unavailable")
    result = audit_teaching_oa(run_dir)
    assert result["points_verified"] == 161
    assert result["device_op"]["M1"]["vds"] - result["device_op"]["M1"]["vdsat"] > 0.2


def test_rehashed_cascode_bias_tamper_is_rejected(tmp_path: Path) -> None:
    run_dir = _grafted_cascode_archive(tmp_path)
    path = run_dir / "ocnprint/device_op.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("M2:vgs=0.648257502408509", "M2:vgs=0.748257502408509"), encoding="utf-8")
    _rehash(run_dir)
    with pytest.raises(ValueError, match="bias differs from netlist"):
        audit_teaching_oa(run_dir)


def test_new_cascode_op_export_cannot_be_disabled_by_metrics(tmp_path: Path) -> None:
    run_dir = _grafted_cascode_archive(tmp_path)
    path = run_dir / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics["oa_device_op_exported"] = False
    path.write_text(json.dumps(metrics), encoding="utf-8")
    _rehash(run_dir)
    with pytest.raises(ValueError, match="export contract differs"):
        audit_teaching_oa(run_dir)
