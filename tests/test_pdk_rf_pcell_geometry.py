from __future__ import annotations

import json
import hashlib
import re
import shutil
from pathlib import Path

import pytest

from orfadc.experiments.audit_pdk_rf_pcell_geometry import _box, audit_pdk_rf_pcell_geometry


_DEFAULT = Path("results/runs/pdk_geometry_instantiation/rf_pcell_default_20260927_01")
_VARIANT = Path("results/runs/pdk_geometry_instantiation/rf_pcell_wr3_20260927_01")
_CHILDREN = Path("results/runs/pdk_geometry_readonly/rf_saved_children_20260927_01")


def test_bbox_parser_rejects_malformed_or_zero_area() -> None:
    assert _box("((0 0) (1 2))") == (0.0, 0.0, 1.0, 2.0)
    for value in ("(0 0 1 1)", "((0 0) (0 1))", "((nan 0) (1 1))"):
        with pytest.raises(ValueError):
            _box(value)


def _private_runs() -> tuple[Path, Path, Path]:
    if not all(path.is_dir() for path in (_DEFAULT, _VARIANT, _CHILDREN)):
        pytest.skip("private authorized PCell archives are unavailable")
    return _DEFAULT, _VARIANT, _CHILDREN


def test_real_pcell_geometry_response_reaudits() -> None:
    result = audit_pdk_rf_pcell_geometry(*_private_runs())
    assert result["status"] == "raw_pcell_width_response_verified"
    assert result["core_bbox_changed"] is True
    assert result["cdf_callback_validated"] is False
    assert result["drc_validated"] is False
    assert result["physical_qualification"] is False
    assert result["spec_pass"] is None and result["not_lna_result"] is True


@pytest.mark.parametrize("mutation", ["remote_oa", "width_report", "child_geometry", "callback_claim", "extra_param"])
def test_pcell_geometry_audit_rejects_tampered_archive(tmp_path: Path, mutation: str) -> None:
    originals = _private_runs()
    copied = []
    for source in originals:
        destination = tmp_path / source.name
        shutil.copytree(source, destination)
        copied.append(destination)
    default, variant, children = copied
    if mutation == "remote_oa":
        path = variant / "remote_layout.oa"
        path.write_bytes(path.read_bytes() + b"tamper")
    elif mutation == "width_report":
        path = variant / "report.txt"
        original = (default / "report.txt").read_text(encoding="utf-8")
        changed = path.read_text(encoding="utf-8")
        entries = re.findall(r'^parameter name="([^"]+)" type="([^"]+)" value="([^"]+)"$', original, re.MULTILINE)
        for name, kind, value in entries:
            source_line = f'parameter name="{name}" type="{kind}" value="{value}"'
            if source_line not in changed:
                changed = re.sub(rf'parameter name="{re.escape(name)}" type="[^"]+" value="[^"]+"',
                                 source_line, changed)
                break
        path.write_text(changed, encoding="utf-8")
    elif mutation == "child_geometry":
        path = children / "report.txt"
        report = path.read_text(encoding="utf-8")
        first, second = report.split(f"cell={variant.name} opened=t", 1)
        pattern = r'(?m)^    child="[^"]+" bbox=(\(\([^\n]+\)\)) master_bbox='
        baseline = re.search(pattern, first)
        changed = re.search(pattern, second)
        assert baseline and changed
        path.write_text(first + f"cell={variant.name} opened=t" + second.replace(
            changed[1], baseline[1], 1,
        ), encoding="utf-8")
    elif mutation == "callback_claim":
        path = variant / "run_status.json"
        status = json.loads(path.read_text(encoding="utf-8"))
        status["cdf_callback_invoked"] = True
        path.write_text(json.dumps(status), encoding="utf-8")
    else:
        source = variant / "create.ocn"
        original = source.read_bytes()
        modified = re.sub(rb'list\(list\("[^"]+" "[^"]+" "[^"]+"\)\)',
                          lambda match: match[0][:-1] + b' list("extra" "string" "20"))', original)
        assert modified != original
        source.write_bytes(modified)
        (variant / "remote_create.ocn").write_bytes(modified)
        path = variant / "run_status.json"
        status = json.loads(path.read_text(encoding="utf-8"))
        status["script_sha256"] = hashlib.sha256(modified).hexdigest()
        path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError):
        audit_pdk_rf_pcell_geometry(default, variant, children)
