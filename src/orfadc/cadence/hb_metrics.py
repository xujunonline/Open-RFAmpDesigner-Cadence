from __future__ import annotations

import math
import re
from pathlib import Path

from orfadc.cadence.psfascii_reader import parse_complex_trace


_FUNDAMENTAL = re.compile(r'^"fundamental"\s+([-+0-9.eE]+)$', re.MULTILINE)


def extract_hb_fundamental_power(
    path: Path, *, output_node: str, fundamental_hz: float, load_ohm: float = 50.0
) -> dict[str, float]:
    if not output_node or not re.fullmatch(r"[A-Za-z0-9_.]+", output_node):
        raise ValueError("HB output node must be a safe signal name")
    if any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
           for value in (fundamental_hz, load_ohm)):
        raise ValueError("HB frequency and load must be finite and positive")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if '"analysis type" "fd.pss_hb"' not in raw:
        raise ValueError("HB result is not frequency-domain PSS/HB data")
    header = raw.split("TYPE", 1)[0]
    match = _FUNDAMENTAL.search(header)
    if not match or not math.isclose(float(match[1]), fundamental_hz, rel_tol=1e-9):
        raise ValueError("HB fundamental header disagrees with the requested tone")
    frequencies, voltages = parse_complex_trace(path, output_node)
    current_frequencies, currents = parse_complex_trace(path, "PORT2:p")
    if frequencies != current_frequencies or len(frequencies) < 2:
        raise ValueError("HB output voltage/current frequency axes disagree")
    matches = [index for index, frequency in enumerate(frequencies)
               if math.isclose(frequency, fundamental_hz, rel_tol=1e-9)]
    if len(matches) != 1:
        raise ValueError("HB result must contain exactly one fundamental point")
    voltage = voltages[matches[0]]
    current = currents[matches[0]]
    if any(not math.isfinite(part) for value in (voltage, current) for part in (value.real, value.imag)):
        raise ValueError("HB fundamental contains nonfinite voltage/current")
    expected_current = voltage / load_ohm
    if abs(current - expected_current) > max(1e-12, 1e-3 * abs(expected_current)):
        raise ValueError("HB output port current disagrees with the declared resistive load")
    delivered_w = 0.5 * (voltage * current.conjugate()).real
    if delivered_w <= 0 or not math.isfinite(delivered_w):
        raise ValueError("HB fundamental delivered power must be positive")
    voltage_power_w = abs(voltage) ** 2 / (2 * load_ohm)
    if not math.isclose(delivered_w, voltage_power_w, rel_tol=1e-3):
        raise ValueError("HB voltage/current and load-power formulas disagree")
    return {
        "fundamental_hz": fundamental_hz,
        "vout_peak_v": abs(voltage),
        "iout_peak_a": abs(current),
        "output_power_dbm": 10 * math.log10(delivered_w / 1e-3),
        "load_current_relative_error": abs(current - expected_current) / max(abs(expected_current), 1e-30),
    }


def extract_sp_s21_at_frequency(path: Path, frequency_hz: float) -> float:
    if type(frequency_hz) not in {int, float} or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("S21 comparison frequency must be finite and positive")
    frequencies, s21 = parse_complex_trace(path, "s21")
    matches = [index for index, frequency in enumerate(frequencies)
               if math.isclose(frequency, frequency_hz, rel_tol=1e-9)]
    if len(matches) != 1 or abs(s21[matches[0]]) <= 0:
        raise ValueError("S21 result lacks the exact HB fundamental point")
    return 20 * math.log10(abs(s21[matches[0]]))


def extract_hb_input_available_power(
    path: Path, *, fundamental_hz: float, source_ohm: float = 50.0,
    input_node: str = "in",
) -> float:
    """Recover a Spectre port's available input power from its HB fundamental."""
    if not re.fullmatch(r"[A-Za-z0-9_.]+", input_node):
        raise ValueError("HB input node must be a safe signal name")
    if any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
           for value in (fundamental_hz, source_ohm)):
        raise ValueError("HB input frequency and source resistance must be positive")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if '"analysis type" "fd.pss_hb"' not in raw:
        raise ValueError("HB input result is not frequency-domain PSS/HB data")
    header = raw.split("TYPE", 1)[0]
    tone = _FUNDAMENTAL.search(header)
    port = re.search(r'^"PORT1:r"\s+([-+0-9.eE]+)$', header, re.MULTILINE)
    if (not tone or not math.isclose(float(tone[1]), fundamental_hz, rel_tol=1e-9)
            or not port or not math.isclose(float(port[1]), source_ohm, rel_tol=1e-9)):
        raise ValueError("HB input tone or port resistance differs")
    grid_v, voltage = parse_complex_trace(path, input_node)
    grid_i, current = parse_complex_trace(path, "PORT1:p")
    if grid_v != grid_i:
        raise ValueError("HB input voltage/current grids differ")
    matches = [index for index, frequency in enumerate(grid_v)
               if math.isclose(frequency, fundamental_hz, rel_tol=1e-9)]
    if len(matches) != 1:
        raise ValueError("HB input result requires one fundamental point")
    index = matches[0]
    if any(not math.isfinite(part) for value in (voltage[index], current[index])
           for part in (value.real, value.imag)):
        raise ValueError("HB input fundamental contains nonfinite voltage/current")
    # Spectre PORT1:p is directed into the port, so Vsource = Vnode - R*Iport.
    source_peak = voltage[index] - source_ohm * current[index]
    available_w = abs(source_peak) ** 2 / (8 * source_ohm)
    if available_w <= 0 or not math.isfinite(available_w):
        raise ValueError("HB input available power is invalid")
    return 10 * math.log10(available_w / 1e-3)


def extract_hb_differential_fundamental_power(
    path: Path, *, fundamental_hz: float, load_ohm: float = 1787.0,
    positive_node: str = "outp", negative_node: str = "outn",
) -> dict[str, float]:
    if (any(re.fullmatch(r"[A-Za-z0-9_.]+", name) is None for name in (positive_node, negative_node))
            or positive_node == negative_node):
        raise ValueError("HB differential output node names are invalid")
    if any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
           for value in (fundamental_hz, load_ohm)):
        raise ValueError("HB differential frequency and load must be finite and positive")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if '"analysis type" "fd.pss_hb"' not in raw:
        raise ValueError("HB result is not frequency-domain PSS/HB data")
    header = raw.split("TYPE", 1)[0]
    tone = _FUNDAMENTAL.search(header)
    port = re.search(r'^"PORT2:r"\s+([-+0-9.eE]+)$', header, re.MULTILINE)
    if not tone or not math.isclose(float(tone[1]), fundamental_hz, rel_tol=1e-9):
        raise ValueError("HB differential fundamental header differs")
    if not port or not math.isclose(float(port[1]), load_ohm, rel_tol=1e-9):
        raise ValueError("HB differential output port resistance differs")
    positive_grid, positive = parse_complex_trace(path, positive_node)
    negative_grid, negative = parse_complex_trace(path, negative_node)
    current_grid, currents = parse_complex_trace(path, "PORT2:p")
    if positive_grid != negative_grid or positive_grid != current_grid:
        raise ValueError("HB differential voltage/current grids differ")
    matches = [index for index, frequency in enumerate(positive_grid)
               if math.isclose(frequency, fundamental_hz, rel_tol=1e-9)]
    if len(matches) != 1:
        raise ValueError("HB differential result requires one fundamental point")
    index = matches[0]
    voltage = positive[index] - negative[index]
    current = currents[index]
    if any(not math.isfinite(part) for value in (voltage, current) for part in (value.real, value.imag)):
        raise ValueError("HB differential fundamental contains nonfinite voltage/current")
    expected_current = voltage / load_ohm
    if abs(current - expected_current) > max(1e-12, 1e-3 * abs(expected_current)):
        raise ValueError("HB differential port current disagrees with load")
    delivered_w = 0.5 * (voltage * current.conjugate()).real
    voltage_power_w = abs(voltage) ** 2 / (2 * load_ohm)
    if delivered_w <= 0 or not math.isclose(delivered_w, voltage_power_w, rel_tol=1e-3):
        raise ValueError("HB differential delivered power is invalid")
    return {
        "fundamental_hz": fundamental_hz,
        "vout_diff_peak_v": abs(voltage),
        "iout_peak_a": abs(current),
        "output_power_dbm": 10 * math.log10(delivered_w / 1e-3),
        "load_current_relative_error": abs(current - expected_current) / max(abs(expected_current), 1e-30),
    }
