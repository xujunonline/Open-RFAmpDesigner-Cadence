from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_readonly import audit_virtuoso_form_readonly


_GOOD = Path("results/runs/virtuoso_cdf_readonly/20260927T024933Z_5988b692")
_FALSE_POSITIVE = Path("results/runs/virtuoso_cdf_readonly/20260927T024605Z_6420a646")
_SOURCE = Path("results/runs/lna_stage03/private_schematic_core/probe_mos_cdf_v1_v2.ocn")
_BASELINE = Path("results/runs/lna_stage03/private_schematic_core/mos_cdf_readonly_20260926_02_report.txt")


def _private() -> tuple[Path, Path, Path]:
    if not all(path.exists() for path in (_GOOD, _SOURCE, _BASELINE)):
        pytest.skip("private authorized form probe archives are unavailable")
    return _GOOD, _SOURCE, _BASELINE


def test_real_form_readonly_reaudits() -> None:
    result = audit_virtuoso_form_readonly(*_private())
    assert result["status"] == "gui_form_readonly_verified"
    assert result["property_form_global_present"] is True
    assert result["current_form_focused"] is False
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False


def test_false_positive_with_skill_error_is_rejected() -> None:
    if not _FALSE_POSITIVE.is_dir():
        pytest.skip("private failed form probe archive is unavailable")
    _, source, baseline = _private()
    with pytest.raises(ValueError):
        audit_virtuoso_form_readonly(_FALSE_POSITIVE, source, baseline)


@pytest.mark.parametrize("mutation", ("script", "report", "error_log", "false_callback"))
def test_form_probe_rejects_tampering(tmp_path: Path, mutation: str) -> None:
    run, source, baseline = _private()
    copied = tmp_path / run.name
    shutil.copytree(run, copied)
    if mutation == "script":
        path = copied / "virtuoso_gui_smoke.il"
        path.write_bytes(path.read_bytes() + b"\n; modified\n")
    elif mutation == "report":
        path = copied / "cdf_readonly_report.txt"
        path.write_bytes(path.read_bytes().replace(b"form_Wfg_field=t", b"form_Wfg_field=nil"))
    elif mutation == "error_log":
        path = copied / "virtuoso.log"
        path.write_bytes(path.read_bytes() + b"\n\\e *Error* invented failure\n")
    else:
        path = copied / "run_status.json"
        status = json.loads(path.read_text(encoding="utf-8"))
        status["cdf_callback_invoked"] = True
        path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError):
        audit_virtuoso_form_readonly(copied, source, baseline)
