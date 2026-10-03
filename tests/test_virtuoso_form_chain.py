from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_chain import audit_virtuoso_form_chain


_FORM = Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a")
_READBACK = Path("results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd")
_NETLIST = Path("results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b")
_BASELINE = Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs")
_FAILED_DEFAULT = Path("results/runs/virtuoso_cdf_form_variant/20260927T025508Z_91ead4e8")


@pytest.fixture
def private_tmp_dir() -> Path:
    with tempfile.TemporaryDirectory(
        prefix="test_form_chain_", dir=Path("results/runs").resolve(),
    ) as root:
        yield Path(root)


def _private() -> tuple[Path, Path, Path, Path]:
    if not all(path.exists() for path in (_FORM, _READBACK, _NETLIST, _BASELINE)):
        pytest.skip("private authorized form/OA/netlist archives are unavailable")
    return _FORM, _READBACK, _NETLIST, _BASELINE


def test_real_form_chain_reaudits_without_callback_claim() -> None:
    result = audit_virtuoso_form_chain(*_private())
    assert result["status"] == "form_change_persisted_with_partial_model_propagation"
    assert result["single_form_field_changed"] is True
    assert result["saved_oa_identical_across_three_archives"] is True
    assert result["spectre_netlist_exported"] is True
    assert result["model_width_changed"] is False
    assert result["changed_parasitic_parameter_count"] > 0
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


def test_failed_default_form_does_not_qualify() -> None:
    if not _FAILED_DEFAULT.is_dir():
        pytest.skip("private failed form probe archive is unavailable")
    _, readback, netlist, baseline = _private()
    with pytest.raises(ValueError):
        audit_virtuoso_form_chain(_FAILED_DEFAULT, readback, netlist, baseline)


@pytest.mark.parametrize(
    "mutation", ("oa", "form_report", "readback_report", "model_width", "false_callback", "log_error"),
)
def test_form_chain_rejects_tampered_evidence(private_tmp_dir: Path, mutation: str) -> None:
    paths = list(_private())
    index = {
        "oa": 1, "form_report": 0, "readback_report": 1,
        "model_width": 2, "false_callback": 0, "log_error": 2,
    }[mutation]
    copied = private_tmp_dir / paths[index].name
    shutil.copytree(paths[index], copied)
    paths[index] = copied
    if mutation == "oa":
        path = copied / "sch.oa"
        path.write_bytes(path.read_bytes() + b"tampered")
    elif mutation == "form_report":
        path = copied / "form_report.txt"
        path.write_bytes(path.read_bytes().replace(b"check_return=(0 0)", b"check_return=(0 1)"))
    elif mutation == "readback_report":
        path = copied / "readback_report.txt"
        path.write_bytes(path.read_bytes().replace(b"readback_complete=t", b"readback_complete=nil"))
    elif mutation == "model_width":
        path = copied / "input.scs"
        source = path.read_text(encoding="utf-8", errors="replace")
        changed, count = re.subn(r"(?m)^(M1 .*?\bw=)[^\s\\]+", r"\g<1>987654u", source, count=1)
        assert count == 1
        path.write_text(changed, encoding="utf-8")
        status_path = copied / "run_status.json"
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        import hashlib
        payload["netlist_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        status_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "false_callback":
        path = copied / "run_status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cdf_callback_validated"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path = copied / "ocean.log"
        path.write_bytes(path.read_bytes() + b"\n\\e *Error* invented failure\n")
    with pytest.raises(ValueError):
        audit_virtuoso_form_chain(*paths)
