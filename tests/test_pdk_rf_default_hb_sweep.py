from __future__ import annotations

from orfadc.experiments.audit_pdk_rf_default_hb_sweep import summarize_diagnostic_p1db


def _rows(powers: tuple[float, ...], gains: tuple[float, ...]) -> list[dict]:
    return [
        {"pin_dbm": pin, "pout_dbm": pin + gain}
        for pin, gain in zip(powers, gains, strict=True)
    ]


def test_diagnostic_p1db_requires_narrow_measured_bracket() -> None:
    fine = summarize_diagnostic_p1db(_rows(
        (-70, -60, -50, -20, -11, -10),
        (-20, -20, -20, -20.1, -20.9, -21.2),
    ))
    assert fine["status"] == "ok"
    assert fine["bracket_width_db"] == 1
    assert fine["ip1db_dbm"] is not None
    coarse = summarize_diagnostic_p1db(_rows(
        (-70, -60, -50, -20, -10),
        (-20, -20, -20, -20.1, -21.2),
    ))
    assert coarse["status"] == "coarse_bracket"
    assert coarse["ip1db_dbm"] is None and coarse["op1db_dbm"] is None


def test_diagnostic_p1db_keeps_unbracketed_null() -> None:
    result = summarize_diagnostic_p1db(_rows(
        (-70, -60, -50, -20), (-20, -20, -20, -20.1),
    ))
    assert result["status"] == "unbracketed"
    assert result["ip1db_dbm"] is None and result["bracket_width_db"] is None
