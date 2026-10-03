from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_gui_smoke import audit_virtuoso_gui_smoke


_REAL = Path("results/runs/virtuoso_gui_smoke/20260927T023222Z_0f857b59")


def _real() -> Path:
    if not _REAL.is_dir():
        pytest.skip("private authorized Virtuoso GUI smoke archive is unavailable")
    return _REAL


def test_real_gui_smoke_reaudits_without_cdf_claim() -> None:
    result = audit_virtuoso_gui_smoke(_real())
    assert result["status"] == "gui_replay_verified"
    assert result["full_virtuoso_initialized"] is True
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize("mutation", ("script", "log", "false_cdf", "missing_log"))
def test_gui_smoke_rejects_tampered_archive(tmp_path: Path, mutation: str) -> None:
    copied = tmp_path / _real().name
    shutil.copytree(_REAL, copied)
    if mutation == "script":
        path = copied / "virtuoso_gui_smoke.il"
        path.write_bytes(path.read_bytes() + b"\n; changed\n")
    elif mutation == "log":
        path = copied / "virtuoso.log"
        log = path.read_text(encoding="utf-8", errors="replace")
        assert "\\o ORFADC_GUI_REPLAY_END" in log
        path.write_text(log.replace("\\o ORFADC_GUI_REPLAY_END", "\\o REPLAY_MISSING", 1), encoding="utf-8")
    elif mutation == "false_cdf":
        path = copied / "run_status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cdf_callback_invoked"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        (copied / "xvfb.stderr").unlink()
    with pytest.raises(ValueError):
        audit_virtuoso_gui_smoke(copied)
