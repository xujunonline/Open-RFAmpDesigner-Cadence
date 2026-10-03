import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage_hb
from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_teaching_three_stage_hb import audit_teaching_three_stage_hb
from orfadc.experiments.run_teaching_three_stage_hb import run_teaching_three_stage_hb


_REAL = Path("results/runs/teaching_three_stage_hb/0f785d08cc")
_AUTO = Path("results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b")


def test_three_stage_hb_renderer_changes_only_excitation_and_analysis() -> None:
    source = render_teaching_three_stage_hb(-70).decode("ascii")
    assert source.count("PORT1 (in 0) port r=50 num=1 type=sine dbm=-70 freq=10000000000") == 1
    assert source.count("PORT2 (outp outn) port r=1787 num=2 type=dc") == 1
    assert source.count("hb hb fundfreqs=[10000000000] maxharms=[7]") == 1
    assert source.count("K3 mutual_inductor coupling=0.45") == 1
    assert source.count("L3S (outp outn) inductor l=1n") == 1


@pytest.mark.parametrize("input_dbm", [float("nan"), -101, 1, True])
def test_three_stage_hb_renderer_rejects_bad_power(input_dbm: float) -> None:
    with pytest.raises(ValueError, match="input"):
        render_teaching_three_stage_hb(input_dbm)


@pytest.mark.parametrize("frequency_ghz", [7.99, 10.01, 12.01])
def test_three_stage_hb_renderer_requires_sp_grid(frequency_ghz: float) -> None:
    with pytest.raises(ValueError, match="SP grid"):
        render_teaching_three_stage_hb(-70, frequency_ghz=frequency_ghz)


@pytest.mark.parametrize("harmonics", [0, 12, 3.0])
def test_three_stage_hb_renderer_rejects_bad_harmonics(harmonics: int) -> None:
    with pytest.raises(ValueError, match="harmonics"):
        render_teaching_three_stage_hb(-70, harmonics=harmonics)


def test_three_stage_hb_renderer_supports_harmonic_convergence_points() -> None:
    source = render_teaching_three_stage_hb(-13.2, harmonics=11).decode("ascii")
    assert "PORT1 (in 0) port r=50 num=1 type=sine dbm=-13.199999999999999 freq=10000000000" in source
    assert "hb hb fundfreqs=[10000000000] maxharms=[11] annotate=status" in source


def test_real_three_stage_low_drive_hb_is_rebuildable() -> None:
    if not _REAL.is_dir():
        pytest.skip("private Cadence three-stage HB archive is unavailable")
    result = audit_teaching_three_stage_hb(_REAL)
    assert result["status"] == "verified"
    assert result["not_lna_result"] is True


def test_automated_three_stage_low_drive_hb_is_rebuildable() -> None:
    if not _AUTO.is_dir():
        pytest.skip("private automated three-stage HB archive is unavailable")
    result = audit_teaching_three_stage_hb(_AUTO)
    assert result["status"] == "verified"
    assert result["not_lna_result"] is True


def test_rehashed_differential_hb_current_tamper_is_rejected(tmp_path: Path) -> None:
    if not _REAL.is_dir():
        pytest.skip("private Cadence three-stage HB archive is unavailable")
    copied = tmp_path / _REAL.name
    shutil.copytree(_REAL, copied)
    path = copied / "hb.fd.pss_hb"
    text = path.read_text(encoding="utf-8")
    assert "5.409997506179987e-08" in text
    path.write_text(text.replace("5.409997506179987e-08", "6.409997506179987e-08", 1), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="port current"):
        audit_teaching_three_stage_hb(copied)


def test_three_stage_hb_runner_bounds_power_before_remote_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orfadc.experiments.run_teaching_three_stage_hb._require_private_path",
        lambda path: None,
    )
    for power in (-101, 1, float("nan"), True):
        with pytest.raises(ValueError, match="three-stage HB requires"):
            run_teaching_three_stage_hb(tmp_path / "missing.yaml", tmp_path / "run", input_dbm=power)


def test_rehashed_input_hb_current_tamper_is_rejected(tmp_path: Path) -> None:
    if not _AUTO.is_dir():
        pytest.skip("private Cadence three-stage HB archive is unavailable")
    copied = tmp_path / _AUTO.name
    shutil.copytree(_AUTO, copied)
    path = copied / "hb.fd.pss_hb"
    raw = path.read_text(encoding="utf-8")
    marker = '"PORT1:p" (1.100788580145040e-07 1.983092829282661e-06)'
    assert marker in raw
    path.write_text(raw.replace(marker, '"PORT1:p" (1.100788580145040e-07 2.983092829282661e-06)', 1), encoding="utf-8")
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    with pytest.raises(ValueError, match="input power differs"):
        audit_teaching_three_stage_hb(copied)
