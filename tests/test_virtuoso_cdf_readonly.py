from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_cdf_readonly import audit_virtuoso_cdf_readonly
from orfadc.experiments.run_virtuoso_cdf_readonly import _render_readonly_script


_RUN = Path("results/runs/virtuoso_cdf_readonly/20260927T023600Z_26d308a8")
_SOURCE = Path("results/runs/lna_stage03/private_schematic_core/probe_mos_cdf_v1_v2.ocn")
_BASELINE = Path("results/runs/lna_stage03/private_schematic_core/mos_cdf_readonly_20260926_02_report.txt")


def _private() -> tuple[Path, Path, Path]:
    if not all(path.exists() for path in (_RUN, _SOURCE, _BASELINE)):
        pytest.skip("private authorized CDF archives are unavailable")
    return _RUN, _SOURCE, _BASELINE


def test_real_gui_cdf_readonly_matches_prior_ocean() -> None:
    result = audit_virtuoso_cdf_readonly(*_private())
    assert result["status"] == "gui_cdf_readonly_verified"
    assert result["cdf_report_matches_prior_ocean"] is True
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("report", "rendered", "false_callback", "log"))
def test_gui_cdf_readonly_rejects_tampering(tmp_path: Path, mutation: str) -> None:
    run, source, baseline = _private()
    copied = tmp_path / run.name
    shutil.copytree(run, copied)
    if mutation == "report":
        path = copied / "cdf_readonly_report.txt"
        path.write_bytes(path.read_bytes() + b"changed\n")
    elif mutation == "rendered":
        path = copied / "virtuoso_gui_smoke.il"
        path.write_bytes(path.read_bytes() + b"\n; changed\n")
    elif mutation == "false_callback":
        path = copied / "run_status.json"
        status = json.loads(path.read_text(encoding="utf-8"))
        status["cdf_callback_invoked"] = True
        path.write_text(json.dumps(status), encoding="utf-8")
    else:
        path = copied / "virtuoso.log"
        log = path.read_text(encoding="utf-8", errors="replace")
        assert "Virtuoso has launched" in log
        path.write_text(log.replace("Virtuoso has launched", "Startup missing", 1), encoding="utf-8")
    with pytest.raises(ValueError):
        audit_virtuoso_cdf_readonly(copied, source, baseline)


def test_cdf_script_renderer_rejects_changed_source(tmp_path: Path) -> None:
    _, source, _ = _private()
    invalid = tmp_path / "cdf.ocn"
    invalid.write_bytes(source.read_bytes().replace(b"exit()\n", b"dbSave(cv)\nexit()\n"))
    with pytest.raises(ValueError):
        _render_readonly_script(
            invalid, hashlib.sha256(invalid.read_bytes()).hexdigest(), "/tmp/report.txt",
        )
