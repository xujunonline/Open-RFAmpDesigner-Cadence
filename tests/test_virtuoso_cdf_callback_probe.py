from __future__ import annotations

import pytest

from orfadc.experiments.run_virtuoso_cdf_callback_probe import _render_callback_probe


_ARGS = {
    "lib_name": "userlib", "lib_path": "/tmp/userlib",
    "source_cell": "saved_form", "cell_name": "fresh_callback",
    "mos_name": "M1", "report_path": "/tmp/probe/report.txt",
}


def test_callback_probe_is_bounded_to_copied_user_cell() -> None:
    script = _render_callback_probe(**_ARGS)
    assert b'dbCopyCellView(sourceCv libName cellName "schematic")' in script
    assert b'"saved_form"' in script and b'"fresh_callback"' in script
    assert b'callbackParam=cdfFindParamByName(cdfgData "Wfg")' in script
    assert b'errset(evalstring(callbackParam~>callback) t)' in script
    assert b'"Wfg" "w" "l" "nf" "fingers"' in script
    assert b"ORFADC_CALLBACK_RETURNED" in script
    assert b"vfoSetParam" not in script


@pytest.mark.parametrize(
    "override", (
        {"source_cell": "../source"}, {"cell_name": "saved_form"},
        {"lib_path": "/tmp/user lib"}, {"report_path": "/tmp/report;rm"},
        {"mos_name": "M1\nexit()"},
    ),
)
def test_callback_probe_rejects_unsafe_context(override: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        _render_callback_probe(**(_ARGS | override))
