from __future__ import annotations

import math
import re
from pathlib import Path


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_SCALAR_RE = re.compile(rf'^"(?P<name>[^"]+)"\s+(?P<value>{_NUMBER})$')
_COMPLEX_RE = re.compile(
    rf'^"(?P<name>[^"]+)"\s+\((?P<real>{_NUMBER})\s+(?P<imag>{_NUMBER})\)$'
)
_TYPED_SCALAR_RE = re.compile(
    rf'^"(?P<name>[^"]+)"\s+"(?P<kind>[^"]+)"\s+(?P<value>{_NUMBER})$'
)
_STRUCT_FIELD_RE = re.compile(
    r'^"(?P<name>[^"]+)"\s+(?:FLOAT\s+DOUBLE|INT\s+(?:LONG|BYTE))\s+PROP\($'
)


def parse_complex_trace(
    path: Path,
    signal: str,
    *,
    sweep_variable: str = "freq",
) -> tuple[list[float], list[complex]]:
    sweep_values: list[float] = []
    signal_values: list[complex] = []
    current_sweep: float | None = None

    for line in _lines(path):
        scalar_match = _SCALAR_RE.match(line)
        if scalar_match and scalar_match.group("name") == sweep_variable:
            current_sweep = float(scalar_match.group("value"))
            continue
        complex_match = _COMPLEX_RE.match(line)
        if complex_match and complex_match.group("name") == signal and current_sweep is not None:
            sweep_values.append(current_sweep)
            signal_values.append(
                complex(
                    float(complex_match.group("real")),
                    float(complex_match.group("imag")),
                )
            )
            current_sweep = None

    _require_trace(path, signal, sweep_values)
    return sweep_values, signal_values


def parse_scalar_trace(
    path: Path,
    signal: str,
    *,
    sweep_variable: str = "freq",
    require_each_sweep: bool = False,
) -> tuple[list[float], list[float]]:
    sweep_values: list[float] = []
    signal_values: list[float] = []
    current_sweep: float | None = None
    signal_seen = False
    in_values = False

    for line in _lines(path):
        if line == "VALUE":
            in_values = True
            continue
        if not in_values:
            continue
        scalar_match = _SCALAR_RE.match(line)
        if not scalar_match:
            if require_each_sweep and line.startswith(f'"{signal}" '):
                raise ValueError(f"malformed scalar signal {signal!r} in {path}")
            continue
        name = scalar_match.group("name")
        value = float(scalar_match.group("value"))
        if name == sweep_variable:
            if require_each_sweep and current_sweep is not None and not signal_seen:
                raise ValueError(f"signal {signal!r} missing at frequency {current_sweep} in {path}")
            current_sweep = value
            signal_seen = False
        elif name == signal and current_sweep is not None:
            if require_each_sweep and signal_seen:
                raise ValueError(f"duplicate signal {signal!r} at frequency {current_sweep} in {path}")
            sweep_values.append(current_sweep)
            signal_values.append(value)
            signal_seen = True
            if not require_each_sweep:
                current_sweep = None

    if require_each_sweep and current_sweep is not None and not signal_seen:
        raise ValueError(f"signal {signal!r} missing at frequency {current_sweep} in {path}")
    _require_trace(path, signal, sweep_values)
    return sweep_values, signal_values


def parse_trace_kinds(path: Path) -> dict[str, str]:
    kinds: dict[str, str] = {}
    in_trace = False
    for line in _lines(path):
        if line == "TRACE":
            in_trace = True
            continue
        if line == "VALUE":
            break
        if in_trace:
            match = re.fullmatch(r'"([^"]+)"\s+"([^"]+)"', line)
            if match:
                kinds[match.group(1)] = match.group(2)
    return kinds


def parse_dc_values(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in _lines(path):
        match = _TYPED_SCALAR_RE.match(line)
        if match:
            values[match.group("name")] = float(match.group("value"))
    if not values:
        raise ValueError(f"no typed scalar values found in {path}")
    return values


def parse_struct_values(path: Path, *, instance: str, struct_type: str) -> dict[str, float]:
    fields: list[str] = []
    values: list[float] = []
    in_type = False
    in_instance = False
    type_seen = False
    instance_seen = False
    in_values = False
    for line in _lines(path):
        if line == "VALUE":
            in_values = True
            in_type = False
            continue
        if not in_values:
            if line == f'"{struct_type}" STRUCT(':
                in_type = True
                type_seen = True
            elif in_type and line == ") PROP(":
                in_type = False
            elif in_type:
                match = _STRUCT_FIELD_RE.match(line)
                if match:
                    fields.append(match.group("name"))
        elif line == f'"{instance}" "{struct_type}" (':
            in_instance = True
            instance_seen = True
        elif in_instance and line == ") PROP(":
            in_instance = False
        elif in_instance:
            try:
                values.append(float(line))
            except ValueError as exc:
                raise ValueError(f"malformed structured value in {path}") from exc
    if not type_seen or not instance_seen or not fields or len(fields) != len(values):
        raise ValueError(f"incomplete {struct_type} operating-point record for {instance} in {path}")
    if len(fields) != len(set(fields)):
        raise ValueError(f"duplicate {struct_type} operating-point field in {path}")
    return dict(zip(fields, values, strict=True))


def subtract_complex_traces(
    positive: tuple[list[float], list[complex]],
    negative: tuple[list[float], list[complex]],
) -> tuple[list[float], list[complex]]:
    positive_x, positive_values = positive
    negative_x, negative_values = negative
    if positive_x != negative_x:
        raise ValueError("positive and negative trace sweeps do not match")
    return positive_x, [p_value - n_value for p_value, n_value in zip(positive_values, negative_values)]


def magnitude_db(values: list[complex]) -> list[float]:
    return [20.0 * math.log10(max(abs(value), 1e-300)) for value in values]


def unwrap_degrees(values: list[complex]) -> list[float]:
    unwrapped: list[float] = []
    for value in values:
        phase = math.degrees(math.atan2(value.imag, value.real))
        if unwrapped:
            while phase - unwrapped[-1] > 180.0:
                phase -= 360.0
            while phase - unwrapped[-1] < -180.0:
                phase += 360.0
        unwrapped.append(phase)
    return unwrapped


def interpolate_descending_crossing(
    sweep_values: list[float],
    y_values: list[float],
    auxiliary_values: list[float] | None = None,
    *,
    threshold: float = 0.0,
    logarithmic_sweep: bool = True,
) -> tuple[float | None, float | None]:
    if len(sweep_values) != len(y_values):
        raise ValueError("sweep and y-value lengths do not match")
    if auxiliary_values is not None and len(auxiliary_values) != len(sweep_values):
        raise ValueError("auxiliary-value length does not match sweep")

    for index in range(1, len(sweep_values)):
        before = y_values[index - 1]
        after = y_values[index]
        if before >= threshold and after < threshold:
            fraction = (before - threshold) / (before - after)
            if logarithmic_sweep:
                if sweep_values[index - 1] <= 0 or sweep_values[index] <= 0:
                    raise ValueError("logarithmic interpolation requires positive sweep values")
                x_before = math.log10(sweep_values[index - 1])
                x_after = math.log10(sweep_values[index])
                crossing = 10.0 ** (x_before + fraction * (x_after - x_before))
            else:
                crossing = sweep_values[index - 1] + fraction * (
                    sweep_values[index] - sweep_values[index - 1]
                )
            auxiliary = None
            if auxiliary_values is not None:
                auxiliary = auxiliary_values[index - 1] + fraction * (
                    auxiliary_values[index] - auxiliary_values[index - 1]
                )
            return crossing, auxiliary
    return None, None


def _lines(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            yield raw_line.strip()


def _require_trace(path: Path, signal: str, sweep_values: list[float]) -> None:
    if not sweep_values:
        raise ValueError(f"signal {signal!r} not found in {path}")
