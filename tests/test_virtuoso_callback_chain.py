from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_callback_chain import audit_virtuoso_callback_chain
from orfadc.experiments.run_virtuoso_callback_netlist import _callback_context


_PATHS = (
    Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a"),
    Path("results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd"),
    Path("results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b"),
    Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"),
    Path("results/runs/virtuoso_cdf_callback_probe/20260927T034641Z_e4e5a696"),
    Path("results/runs/virtuoso_callback_netlist/20260927T034844Z_b2be7dd9"),
)


def _private() -> list[Path]:
    if not all(path.exists() for path in _PATHS):
        pytest.skip("private authorized CDF callback archives are unavailable")
    return list(_PATHS)


def test_real_callback_chain_reaudits_without_qualification_claim() -> None:
    paths = _private()
    _, _, cell = _callback_context(paths[4])
    assert cell.startswith("cdf_callback_")
    result = audit_virtuoso_callback_chain(*paths)
    assert result["status"] == "cdf_callback_invoked_with_partial_parasitic_response"
    assert result["changed_netlist_parameter_count"] == 4
    assert result["model_width_changed"] is False
    assert result["source_oa_unchanged"] is True
    assert result["independent_netlist_oa_identical"] is True
    assert result["callback_invocation_recorded"] is True
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize(
    "mutation", ("report", "source_oa", "log_error", "false_callback", "model_rehashed", "passive_rehashed"),
)
def test_callback_chain_rejects_tampered_evidence(mutation: str) -> None:
    paths = _private()
    index = 5 if mutation in {"model_rehashed", "passive_rehashed"} else 4
    with tempfile.TemporaryDirectory(
        prefix="test_cdf_callback_", dir=Path("results/runs").resolve(),
    ) as root:
        copied = Path(root) / paths[index].name
        shutil.copytree(paths[index], copied)
        paths[index] = copied
        if mutation == "report":
            path = copied / "callback_report.txt"
            source = path.read_bytes()
            assert b"callback_returned=t" in source
            path.write_bytes(source.replace(b"callback_returned=t", b"callback_returned=nil"))
        elif mutation == "source_oa":
            path = copied / "source_after.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "log_error":
            path = copied / "virtuoso.log"
            path.write_bytes(path.read_bytes() + b"\n\\e *Error* invented failure\n")
        elif mutation == "false_callback":
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["cdf_callback_validated"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = copied / "input.scs"
            source = path.read_text(encoding="utf-8", errors="replace")
            pattern = (
                r"(?m)^(M1 .*?\bw=)[^\s\\]+" if mutation == "model_rehashed"
                else r"(?m)^(RD .*?\br=)[^\s\\]+"
            )
            replacement = r"\g<1>987654u" if mutation == "model_rehashed" else r"\g<1>999"
            changed, count = re.subn(pattern, replacement, source, count=1)
            assert count == 1
            path.write_text(changed, encoding="utf-8")
            status_path = copied / "run_status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            payload["netlist_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            status_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_callback_chain(*paths)
