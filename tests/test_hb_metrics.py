from __future__ import annotations

import math
from pathlib import Path

import pytest

from orfadc.cadence.hb_metrics import (
    extract_hb_differential_fundamental_power, extract_hb_fundamental_power,
    extract_hb_input_available_power,
    extract_sp_s21_at_frequency,
)


def _hb_file(path: Path, *, current_scale: float = 1.0, fundamental_hz: float = 10e9) -> Path:
    voltage = math.sqrt(2 * 50 * 1e-7)
    path.write_text(
        'HEADER\n"analysis type" "fd.pss_hb"\n'
        f'"fundamental" {fundamental_hz:.17g}\nTYPE\nVALUE\n'
        '"freq" 0\n"out" (0 0)\n"PORT2:p" (0 0)\n'
        f'"freq" 10000000000\n"out" ({voltage:.17g} 0)\n'
        f'"PORT2:p" ({voltage / 50 * current_scale:.17g} 0)\nEND\n',
        encoding="ascii",
    )
    return path


def test_extract_hb_fundamental_uses_peak_phasor_and_port_current(tmp_path: Path) -> None:
    result = extract_hb_fundamental_power(_hb_file(tmp_path / "hb.fd"), output_node="out", fundamental_hz=10e9)
    assert result["output_power_dbm"] == pytest.approx(-40.0)
    assert result["vout_peak_v"] == pytest.approx(math.sqrt(2 * 50 * 1e-7))
    assert result["load_current_relative_error"] < 1e-12


def test_extract_hb_rejects_wrong_load_and_frequency(tmp_path: Path) -> None:
    path = _hb_file(tmp_path / "hb.fd", current_scale=0.9)
    with pytest.raises(ValueError, match="port current"):
        extract_hb_fundamental_power(path, output_node="out", fundamental_hz=10e9)
    path = _hb_file(tmp_path / "hb.fd", fundamental_hz=9e9)
    with pytest.raises(ValueError, match="header"):
        extract_hb_fundamental_power(path, output_node="out", fundamental_hz=10e9)


def test_extract_sp_s21_requires_exact_hb_tone(tmp_path: Path) -> None:
    path = tmp_path / "sp.sp"
    path.write_text('VALUE\n"freq" 10000000000\n"s21" (2 0)\nEND\n', encoding="ascii")
    assert extract_sp_s21_at_frequency(path, 10e9) == pytest.approx(20 * math.log10(2))
    with pytest.raises(ValueError, match="exact HB"):
        extract_sp_s21_at_frequency(path, 9e9)


def _differential_hb_file(path: Path, *, current_scale: float = 1.0, load_ohm: float = 1787.0) -> Path:
    voltage = math.sqrt(2 * load_ohm * 1e-7)
    path.write_text(
        'HEADER\n"analysis type" "fd.pss_hb"\n'
        f'"fundamental" 10000000000\n"PORT2:r" {load_ohm:.17g}\nTYPE\nVALUE\n'
        '"freq" 0\n"outp" (0 0)\n"outn" (0 0)\n"PORT2:p" (0 0)\n'
        f'"freq" 10000000000\n"outp" ({voltage / 2:.17g} 0)\n'
        f'"outn" ({-voltage / 2:.17g} 0)\n'
        f'"PORT2:p" ({voltage / load_ohm * current_scale:.17g} 0)\nEND\n',
        encoding="ascii",
    )
    return path


def test_extract_differential_hb_uses_port_current_and_peak_phasor(tmp_path: Path) -> None:
    result = extract_hb_differential_fundamental_power(
        _differential_hb_file(tmp_path / "hb.fd"), fundamental_hz=10e9,
    )
    assert result["output_power_dbm"] == pytest.approx(-40.0)
    assert result["load_current_relative_error"] < 1e-12


def test_extract_differential_hb_rejects_wrong_current_or_load(tmp_path: Path) -> None:
    path = _differential_hb_file(tmp_path / "hb.fd", current_scale=0.9)
    with pytest.raises(ValueError, match="port current"):
        extract_hb_differential_fundamental_power(path, fundamental_hz=10e9)
    path = _differential_hb_file(path)
    with pytest.raises(ValueError, match="port resistance"):
        extract_hb_differential_fundamental_power(path, fundamental_hz=10e9, load_ohm=50)


def test_extract_hb_input_available_power_uses_spectre_port_current_sign(tmp_path: Path) -> None:
    path = tmp_path / "hb.fd"
    source_peak = math.sqrt(8 * 50 * 1e-10)
    node_peak = source_peak / 2
    port_current = (node_peak - source_peak) / 50
    path.write_text(
        'HEADER\n"analysis type" "fd.pss_hb"\n'
        '"fundamental" 10000000000\n"PORT1:r" 50\nTYPE\nVALUE\n'
        '"freq" 0\n"in" (0 0)\n"PORT1:p" (0 0)\n'
        f'"freq" 10000000000\n"in" ({node_peak:.17g} 0)\n'
        f'"PORT1:p" ({port_current:.17g} 0)\nEND\n',
        encoding="ascii",
    )
    assert extract_hb_input_available_power(path, fundamental_hz=10e9) == pytest.approx(-70.0)
    with pytest.raises(ValueError, match="port resistance"):
        extract_hb_input_available_power(path, fundamental_hz=10e9, source_ohm=75)


def test_real_three_stage_hb_input_reconstructs_netlist_power() -> None:
    path = Path("results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b/hb.fd.pss_hb")
    if not path.is_file():
        pytest.skip("private Cadence three-stage HB archive is unavailable")
    assert extract_hb_input_available_power(path, fundamental_hz=10e9) == pytest.approx(-70.0)
