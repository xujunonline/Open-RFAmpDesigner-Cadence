from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_form_spectre_pair import audit_virtuoso_form_spectre_pair


_PATHS = (
    Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a"),
    Path("results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd"),
    Path("results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b"),
    Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"),
    Path("results/runs/virtuoso_form_spectre/20260927T031150Z_9fc4af44"),
    Path("results/runs/virtuoso_form_spectre/20260927T031219Z_799a854f"),
    Path("results/runs/virtuoso_form_exports/20260927T031454Z_3d73accb"),
    Path("results/runs/virtuoso_form_exports/20260927T031517Z_d1026182"),
)


def _private() -> list[Path]:
    if not all(path.exists() for path in _PATHS):
        pytest.skip("private authorized form/Spectre archives are unavailable")
    return list(_PATHS)


def test_real_form_spectre_pair_is_diagnostic_only() -> None:
    result = audit_virtuoso_form_spectre_pair(*_private())
    assert result["status"] == "same_condition_spectre_diagnostic_verified"
    assert result["sample_count"] == 47
    assert result["same_frequency_grid"] is True
    assert result["max_abs_delta_s21_db"] > 0.9
    assert result["max_abs_delta_nf_db"] > 0.4
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize(
    "mutation", ("raw_sp", "input_rehashed", "passive_rehashed", "oa", "trace", "summary", "false_spec"),
)
def test_form_spectre_pair_rejects_tampering(mutation: str) -> None:
    paths = _private()
    index = {
        "raw_sp": 4, "input_rehashed": 5, "passive_rehashed": 5, "oa": 5,
        "trace": 6, "summary": 7, "false_spec": 7,
    }[mutation]
    private_root = Path("results/runs").resolve()
    with tempfile.TemporaryDirectory(prefix="test_form_pair_", dir=private_root) as root:
        copied = Path(root) / paths[index].name
        shutil.copytree(paths[index], copied)
        paths[index] = copied
        if mutation == "raw_sp":
            path = copied / "sp.sp"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation in {"input_rehashed", "passive_rehashed"}:
            path = copied / "input.scs"
            source = path.read_text(encoding="utf-8", errors="replace")
            pattern = (
                r"(?m)^(M1 .*?\bw=)[^\s\\]+" if mutation == "input_rehashed"
                else r"(?m)^(RD .*?\br=)[^\s\\]+"
            )
            replacement = r"\g<1>987654u" if mutation == "input_rehashed" else r"\g<1>999"
            changed, count = re.subn(pattern, replacement, source, count=1)
            assert count == 1
            path.write_text(changed, encoding="utf-8")
            status_path = copied / "run_status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            payload["netlist_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            status_path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "oa":
            path = copied / "oa_after.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "trace":
            path = copied / "s11_real.txt"
            source = path.read_text(encoding="utf-8")
            changed, count = re.subn(
                r"(?m)^(\s*1\.00000000000000e\+08\s+)[^\s]+",
                r"\g<1>9.00000000000000e+00", source, count=1,
            )
            assert count == 1
            path.write_text(changed, encoding="utf-8")
        elif mutation == "summary":
            path = copied / "diagnostic_summary.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sample_count"] += 1
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["spec_pass"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_form_spectre_pair(*paths)
