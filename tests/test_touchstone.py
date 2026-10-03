from __future__ import annotations

import math
from pathlib import Path

import pytest

from orfadc.cadence.touchstone import parse_touchstone_1port, parse_touchstone_2port, write_sparameter_csv
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.extract_rf_metrics import band_values
from orfadc.experiments.run_ideal_twoport import run_ideal_twoport


def test_parse_touchstone_ri_uses_two_port_column_order(tmp_path: Path) -> None:
    source = tmp_path / "sample.s2p"
    source.write_text(
        "! test data\n"
        "# GHz S RI R 50\n"
        "1 0.1 0 0.5 0 0.4 0 0.2 0\n",
        encoding="utf-8",
    )

    rows = parse_touchstone_2port(source)

    assert rows[0]["freq_hz"] == 1e9
    assert rows[0]["s11_real"] == 0.1
    assert rows[0]["s21_real"] == 0.5
    assert rows[0]["s12_real"] == 0.4
    assert rows[0]["s22_real"] == 0.2
    assert rows[0]["s21_db"] == pytest.approx(20 * math.log10(0.5))
    assert rows[0]["reference_ohm"] == 50


def test_parse_spectre_mixed_port_reference_without_faking_common_z0(tmp_path: Path) -> None:
    source = tmp_path / "mixed.s2p"
    source.write_text(
        "# Hz S RI R 50.000000 1787.000000\n"
        "8000000000 0.1 0 0.5 0 0.01 0 0.9 0\n",
        encoding="utf-8",
    )
    row = parse_touchstone_2port(source)[0]
    assert row["reference_input_ohm"] == 50
    assert row["reference_output_ohm"] == 1787
    assert "reference_ohm" not in row
    assert row["s21_real"] == 0.5
    source.write_text(source.read_text(encoding="utf-8").replace("1787.000000", "nan"), encoding="utf-8")
    with pytest.raises(ValueError, match="positive and finite"):
        parse_touchstone_2port(source)


def test_parse_touchstone_db_and_write_csv(tmp_path: Path) -> None:
    source = tmp_path / "sample.s2p"
    source.write_text(
        "# MHz S DB R 50\n1000 -20 0 -3 90 -4 0 -10 0\n",
        encoding="utf-8",
    )
    rows = parse_touchstone_2port(source)
    target = tmp_path / "sparams.csv"

    write_sparameter_csv(target, rows)

    assert rows[0]["freq_ghz"] == 1.0
    assert rows[0]["s21_db"] == pytest.approx(-3.0)
    assert rows[0]["s21_real"] == pytest.approx(0.0, abs=1e-12)
    assert "freq_hz,freq_ghz,s11_real" in target.read_text(encoding="utf-8")


def test_parse_touchstone_rejects_incomplete_two_port_row(tmp_path: Path) -> None:
    source = tmp_path / "bad.s2p"
    source.write_text("# Hz S RI R 50\n1 0 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="9 values"):
        parse_touchstone_2port(source)


def test_parse_touchstone_ignores_spectre_noise_parameter_block(tmp_path: Path) -> None:
    source = tmp_path / "noise.s2p"
    source.write_text(
        "# Hz S RI R 50\n"
        "100000000 0.1 0 0.5 0 0.5 0 0.2 0\n"
        "! NOISE PARAMETERS  :\n"
        "100000000 0 1 0 0.1\n",
        encoding="utf-8",
    )
    rows = parse_touchstone_2port(source)
    assert len(rows) == 1
    assert rows[0]["s21_real"] == 0.5


def test_touchstone_rejects_nonfinite_and_out_of_order_frequency(tmp_path: Path) -> None:
    source = tmp_path / "bad.s2p"
    source.write_text("# Hz S RI R 50\n1 nan 0 1 0 1 0 1 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        parse_touchstone_2port(source)
    source.write_text(
        "# Hz S RI R 50\n2 0 0 1 0 1 0 0 0\n1 0 0 1 0 1 0 0 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="increasing"):
        parse_touchstone_2port(source)


def test_band_summary_includes_rounded_endpoint_and_zero_sparameter(tmp_path: Path) -> None:
    source = tmp_path / "edge.s2p"
    source.write_text(
        "# Hz S RI R 50\n99999999.99999999 0 0 0.9 0 0.9 0 0.1 0\n"
        "200000000 0.1 0 0.5 0 0.5 0 0.2 0\n",
        encoding="utf-8",
    )
    rows = parse_touchstone_2port(source)
    summary = summarize_sparams(rows, 0.1, 0.2)
    assert summary["ripple_db"] == pytest.approx(20 * math.log10(0.9 / 0.5))
    assert rows[0]["s11_db"] == -6000


def test_band_edges_are_interpolated_in_log_frequency() -> None:
    rows = [
        {"freq_ghz": 1.0, "s21_db": 0.0},
        {"freq_ghz": 10.0, "s21_db": 10.0},
        {"freq_ghz": 100.0, "s21_db": 20.0},
    ]
    values = band_values(rows, "freq_ghz", "s21_db", math.sqrt(10), 10 * math.sqrt(10))
    assert values == pytest.approx([5.0, 10.0, 15.0])


def test_band_summary_rejects_uncovered_or_disordered_grid() -> None:
    rows = [{"freq_ghz": 1.0, "s21_db": 2.0}, {"freq_ghz": 2.0, "s21_db": 3.0}]
    with pytest.raises(ValueError, match="do not cover"):
        band_values(rows, "freq_ghz", "s21_db", 1.5, 3.0)
    with pytest.raises(ValueError, match="increasing"):
        band_values(list(reversed(rows)), "freq_ghz", "s21_db", 1.0, 2.0)


def test_smoke_runner_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    output = tmp_path / "run"
    output.mkdir()
    (output / "metrics.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        run_ideal_twoport(tmp_path / "private.yaml", tmp_path / "netlist.scs", output)


def test_parse_touchstone_one_port_ri_and_rejects_bad_reference(tmp_path: Path) -> None:
    source = tmp_path / "sample.s1p"
    source.write_text("! one-port\n# GHz S RI R 50\n1 0.1 -0.2\n2 0.3 0.4\n", encoding="ascii")
    rows = parse_touchstone_1port(source)
    assert rows == [
        {"freq_hz": 1e9, "s11_real": 0.1, "s11_imag": -0.2, "reference_ohm": 50},
        {"freq_hz": 2e9, "s11_real": 0.3, "s11_imag": 0.4, "reference_ohm": 50},
    ]
    source.write_text("# GHz S RI R -50\n1 0.1 0\n", encoding="ascii")
    with pytest.raises(ValueError, match="reference impedance"):
        parse_touchstone_1port(source)
