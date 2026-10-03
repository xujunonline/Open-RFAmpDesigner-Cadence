from __future__ import annotations

import pytest

from orfadc.cadence.compression_metrics import extract_p1db


def _row(pin: float, gain: float) -> dict[str, float]:
    return {"pin_dbm": pin, "pout_dbm": pin + gain}


def test_p1db_interpolates_both_reference_planes() -> None:
    rows = [_row(-30, 10), _row(-25, 10), _row(-20, 10), _row(-15, 9.5), _row(-10, 8.5)]

    result = extract_p1db(rows)

    assert result["status"] == "ok"
    assert result["ip1db_dbm"] == pytest.approx(-12.5)
    assert result["op1db_dbm"] == pytest.approx(-3.5)
    assert result["small_signal_gain_db"] == pytest.approx(10.0)
    assert result["crossing_indices"] == [3, 4]


def test_p1db_unbracketed_is_not_extrapolated() -> None:
    rows = [_row(-30, 10), _row(-25, 10), _row(-20, 10), _row(-15, 9.7)]

    result = extract_p1db(rows)

    assert result["status"] == "unbracketed"
    assert result["ip1db_dbm"] is None
    assert result["op1db_dbm"] is None


def test_p1db_rejects_missing_linear_region_and_invalid_grid() -> None:
    with pytest.raises(ValueError, match="linear gain reference"):
        extract_p1db([_row(-30, 10), _row(-25, 9.3), _row(-20, 9), _row(-15, 8)])
    with pytest.raises(ValueError, match="strictly increasing"):
        extract_p1db([_row(-30, 10), _row(-25, 10), _row(-25, 10), _row(-15, 8)])
    with pytest.raises(ValueError, match="finite"):
        extract_p1db([_row(-30, 10), _row(-25, 10), _row(-20, 10), _row(-15, float("nan"))])
    with pytest.raises(ValueError, match="finite"):
        extract_p1db([_row(-30, 10), _row(-25, 10), _row(-20, 10), {"pin_dbm": True, "pout_dbm": -5}])


def test_p1db_flags_nonmonotonic_output() -> None:
    rows = [_row(-30, 10), _row(-25, 10), _row(-20, 10), _row(-15, 9), _row(-10, 3)]

    result = extract_p1db(rows)

    assert result["status"] == "quality_warning"
    assert result["quality_flags"] == ["nonmonotonic_output_power"]
