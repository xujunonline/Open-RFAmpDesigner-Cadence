from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_virtuoso_callback_spectre import audit_virtuoso_callback_spectre


_PATHS = (
    Path("results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a"),
    Path("results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd"),
    Path("results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b"),
    Path("results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs"),
    Path("results/runs/virtuoso_form_spectre/20260927T031150Z_9fc4af44"),
    Path("results/runs/virtuoso_form_spectre/20260927T031219Z_799a854f"),
    Path("results/runs/virtuoso_form_exports/20260927T031454Z_3d73accb"),
    Path("results/runs/virtuoso_form_exports/20260927T031517Z_d1026182"),
    Path("results/runs/virtuoso_cdf_callback_probe/20260927T034641Z_e4e5a696"),
    Path("results/runs/virtuoso_callback_netlist/20260927T034844Z_b2be7dd9"),
    Path("results/runs/virtuoso_callback_spectre/20260927T035402Z_bd6a7d3d"),
    Path("results/runs/virtuoso_callback_exports/20260927T035439Z_9afbc1ca"),
)


def _private() -> list[Path]:
    if not all(path.exists() for path in _PATHS):
        pytest.skip("private authorized callback/Spectre archives are unavailable")
    return list(_PATHS)


def test_real_callback_spectre_uses_audited_netlist_and_has_no_sampled_delta() -> None:
    result = audit_virtuoso_callback_spectre(*_private())
    assert result["status"] == "callback_parasitic_change_without_sampled_response_delta"
    assert result["sample_count"] == 47
    assert result["changed_netlist_parameter_count"] == 4
    assert result["same_15_digit_sampled_sp_noise"] is True
    assert result["same_exported_dc_current"] is True
    assert result["model_width_changed"] is False
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None


@pytest.mark.parametrize(
    "mutation", ("raw_sp", "input_rehashed", "oa", "s12_trace", "false_spec", "wrong_source"),
)
def test_callback_spectre_rejects_tampered_evidence(mutation: str) -> None:
    paths = _private()
    index = 11 if mutation in {"s12_trace", "false_spec"} else 10
    with tempfile.TemporaryDirectory(
        prefix="test_callback_spectre_", dir=Path("results/runs").resolve(),
    ) as root:
        copied = Path(root) / paths[index].name
        shutil.copytree(paths[index], copied)
        paths[index] = copied
        if mutation == "raw_sp":
            path = copied / "sp.sp"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "input_rehashed":
            path = copied / "input.scs"
            source = path.read_text(encoding="utf-8", errors="replace")
            changed, count = re.subn(r"(?m)^(M1 .*?\bw=)[^\s\\]+", r"\g<1>987654u", source, count=1)
            assert count == 1
            path.write_text(changed, encoding="utf-8")
            status_path = copied / "run_status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            payload["netlist_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            status_path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "oa":
            path = copied / "oa_after.oa"
            path.write_bytes(path.read_bytes() + b"tampered")
        elif mutation == "s12_trace":
            path = copied / "s12_real.txt"
            source = path.read_text(encoding="utf-8")
            changed, count = re.subn(
                r"(?m)^(\s*1\.00000000000000e\+08\s+)[^\s]+",
                r"\g<1>1.00000000000000e-01", source, count=1,
            )
            assert count == 1
            path.write_text(changed, encoding="utf-8")
        else:
            path = copied / "run_status.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "false_spec":
                payload["spec_pass"] = True
            else:
                payload["source_callback_run"] = "different_source"
            path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_virtuoso_callback_spectre(*paths)
