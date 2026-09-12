from __future__ import annotations

import math
from pathlib import Path

import pytest

from orfadc.cadence.psfascii_reader import (
    interpolate_descending_crossing,
    magnitude_db,
    parse_complex_trace,
    parse_dc_values,
    parse_scalar_trace,
    subtract_complex_traces,
    unwrap_degrees,
)


def test_parse_complex_and_scalar_frequency_traces(tmp_path: Path) -> None:
    path = tmp_path / "sp.sp"
    path.write_text(
        '''VALUE
"freq" 1.0e+09
"S11" (1.0e-01 -2.0e-01)
"nf" 1.25
"freq" 2.0e+09
"S11" (5.0e-02 -1.0e-01)
"nf" 1.40
END
''',
        encoding="utf-8",
    )

    frequencies, s11 = parse_complex_trace(path, "S11")
    nf_frequencies, nf = parse_scalar_trace(path, "nf")

    assert frequencies == [1.0e9, 2.0e9]
    assert s11 == [complex(0.1, -0.2), complex(0.05, -0.1)]
    assert nf_frequencies == frequencies
    assert nf == [1.25, 1.4]


def test_parse_dc_values(tmp_path: Path) -> None:
    path = tmp_path / "dcOp.dc"
    path.write_text(
        '''VALUE
"out" "V" 5.5e-01
"VDD:p" "I" -6.6e-05
END
''',
        encoding="utf-8",
    )

    values = parse_dc_values(path)

    assert values["out"] == pytest.approx(0.55)
    assert values["VDD:p"] == pytest.approx(-66e-6)


def test_differential_trace_and_crossing_interpolation() -> None:
    frequencies = [1.0, 10.0, 100.0]
    positive = [
        complex(10.0, 0.0),
        complex(2**-0.5, -(2**-0.5)),
        complex(0.0, -0.1),
    ]
    negative = [0j, 0j, 0j]

    _, differential = subtract_complex_traces(
        (frequencies, positive),
        (frequencies, negative),
    )
    gain = magnitude_db(differential)
    phase = unwrap_degrees(differential)
    crossing, crossing_phase = interpolate_descending_crossing(
        frequencies,
        gain,
        phase,
    )

    assert gain[0] == pytest.approx(20.0)
    assert crossing == pytest.approx(10.0)
    assert crossing_phase == pytest.approx(-45.0)


def test_phase_unwrap_matches_ota_parser_behavior() -> None:
    values = [
        complex(math.cos(math.radians(angle)), math.sin(math.radians(angle)))
        for angle in (-170, 170, 150)
    ]
    assert unwrap_degrees(values) == pytest.approx([-170.0, -190.0, -210.0])


def test_missing_signal_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.psfascii"
    path.write_text('VALUE\n"freq" 1.0e9\nEND\n', encoding="utf-8")

    with pytest.raises(ValueError, match="S21"):
        parse_complex_trace(path, "S21")
