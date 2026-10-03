from __future__ import annotations

import cmath
import csv
import math
from pathlib import Path


_FREQUENCY_SCALE = {
    "hz": 1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
}


def parse_touchstone_1port(path: Path) -> list[dict[str, float]]:
    """Parse a Touchstone v1 one-port S11 file into normalized rows."""
    tokens: list[str] = []
    option_tokens: list[str] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            option_tokens = line[1:].lower().split()
            continue
        tokens.extend(line.split())
    if option_tokens is None or len(option_tokens) != 5 or option_tokens[3] != "r":
        raise ValueError("one-port Touchstone option line is missing or incomplete")
    unit, parameter, data_format = option_tokens[:3]
    if unit not in _FREQUENCY_SCALE or parameter != "s" or data_format not in {"ri", "ma", "db"}:
        raise ValueError("unsupported one-port Touchstone options")
    try:
        reference = float(option_tokens[4])
    except ValueError as exc:
        raise ValueError("one-port Touchstone reference impedance must be numeric") from exc
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError("one-port Touchstone reference impedance must be positive")
    if not tokens or len(tokens) % 3:
        raise ValueError("one-port Touchstone data must contain 3 values per frequency")
    rows = []
    previous = 0.0
    for offset in range(0, len(tokens), 3):
        try:
            frequency, first, second = map(float, tokens[offset:offset + 3])
        except ValueError as exc:
            raise ValueError("one-port Touchstone sample is not numeric") from exc
        frequency *= _FREQUENCY_SCALE[unit]
        if not all(math.isfinite(value) for value in (frequency, first, second)) or frequency <= previous:
            raise ValueError("one-port Touchstone samples must be finite and ordered")
        previous = frequency
        value = _to_complex(first, second, data_format)
        rows.append({
            "freq_hz": frequency, "s11_real": value.real, "s11_imag": value.imag,
            "reference_ohm": reference,
        })
    return rows


def parse_touchstone_2port(path: Path) -> list[dict[str, float]]:
    """Parse a Touchstone v1 two-port S-parameter file into normalized rows."""
    tokens: list[str] = []
    option_tokens: list[str] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw_line.lstrip().upper().startswith("! NOISE PARAMETERS"):
            break
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            option_tokens = line[1:].lower().split()
            continue
        tokens.extend(line.split())

    if option_tokens is None:
        raise ValueError("Touchstone option line is missing")
    if len(option_tokens) not in {5, 6} or option_tokens[3] != "r":
        raise ValueError("Touchstone option line is incomplete")
    unit, parameter, data_format = option_tokens[:3]
    try:
        references = tuple(float(value) for value in option_tokens[4:])
    except ValueError as exc:
        raise ValueError("Touchstone reference impedance must be numeric") from exc
    if any(not math.isfinite(value) or value <= 0 for value in references):
        raise ValueError("Touchstone reference impedance must be positive and finite")
    if unit not in _FREQUENCY_SCALE:
        raise ValueError(f"unsupported Touchstone frequency unit: {unit}")
    if parameter != "s":
        raise ValueError(f"only S-parameters are supported, got: {parameter}")
    if data_format not in {"ri", "ma", "db"}:
        raise ValueError(f"unsupported Touchstone data format: {data_format}")
    if len(tokens) % 9:
        raise ValueError("two-port Touchstone data must contain 9 values per frequency")
    if not tokens:
        raise ValueError("Touchstone file has no S-parameter samples")

    rows: list[dict[str, float]] = []
    scale = _FREQUENCY_SCALE[unit]
    previous_frequency = 0.0
    for offset in range(0, len(tokens), 9):
        values = [float(value) for value in tokens[offset : offset + 9]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Touchstone samples must be finite")
        frequency_hz = values[0] * scale
        if frequency_hz <= previous_frequency or not math.isfinite(frequency_hz):
            raise ValueError("Touchstone frequencies must be positive and strictly increasing")
        previous_frequency = frequency_hz
        pairs = [
            _to_complex(values[index], values[index + 1], data_format)
            for index in range(1, 9, 2)
        ]
        row: dict[str, float] = {
            "freq_hz": frequency_hz,
            "freq_ghz": frequency_hz / 1e9,
        }
        # Touchstone two-port order is S11, S21, S12, S22.
        for name, value in zip(("s11", "s21", "s12", "s22"), pairs, strict=True):
            row[f"{name}_real"] = value.real
            row[f"{name}_imag"] = value.imag
            row[f"{name}_db"] = _magnitude_db(value)
        if len(references) == 1 or references[0] == references[1]:
            row["reference_ohm"] = references[0]
        else:
            row["reference_input_ohm"] = references[0]
            row["reference_output_ohm"] = references[1]
        rows.append(row)
    return rows


def write_sparameter_csv(path: Path, rows: list[dict[str, float]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty S-parameter table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _to_complex(first: float, second: float, data_format: str) -> complex:
    if data_format == "ri":
        return complex(first, second)
    if data_format == "ma" and first < 0:
        raise ValueError("Touchstone MA magnitude must be nonnegative")
    magnitude = 10 ** (first / 20) if data_format == "db" else first
    if not math.isfinite(magnitude):
        raise ValueError("Touchstone magnitude must be finite")
    return cmath.rect(magnitude, math.radians(second))


def _magnitude_db(value: complex) -> float:
    magnitude = abs(value)
    return 20 * math.log10(max(magnitude, 1e-300))
