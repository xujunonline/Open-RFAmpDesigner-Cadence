from __future__ import annotations

import math
import re
from pathlib import Path

from .psfascii_reader import magnitude_db
from .stability_metrics import summarize_sampled_stability


_GRID_REL_TOL = 5e-6  # ocnPrint defaults to six significant digits.
_CASCODE_OP_FIELDS = ("id", "vgs", "vds", "vdsat", "gm", "gds", "cgs", "cgd")


def read_ocnprint_trace(path: Path, *, header_fragment: str) -> tuple[list[float], list[float]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    nonempty = [line.strip() for line in lines if line.strip()]
    if not nonempty or not nonempty[0].startswith("freq (Hz)") or header_fragment not in nonempty[0]:
        raise ValueError(f"invalid ocnPrint header in {path.name}")
    frequencies: list[float] = []
    values: list[float] = []
    for line in nonempty[1:]:
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"invalid ocnPrint sample in {path.name}")
        try:
            frequency, value = map(float, fields)
        except ValueError as exc:
            raise ValueError(f"invalid ocnPrint number in {path.name}") from exc
        if not math.isfinite(frequency) or not math.isfinite(value):
            raise ValueError(f"nonfinite ocnPrint sample in {path.name}")
        if frequency <= (frequencies[-1] if frequencies else 0):
            raise ValueError(f"ocnPrint frequencies must increase in {path.name}")
        frequencies.append(frequency)
        values.append(value)
    if not frequencies:
        raise ValueError(f"empty ocnPrint trace in {path.name}")
    return frequencies, values


def read_ocean_rf_rows(export_dir: Path) -> list[dict[str, float]]:
    rows, _ = read_ocean_rf_data(export_dir)
    return rows


def read_ocean_rf_data(
    export_dir: Path,
    *,
    frequency_rel_tol: float = _GRID_REL_TOL,
) -> tuple[list[dict[str, float]], dict[str, float | bool | None] | None]:
    if not math.isfinite(frequency_rel_tol) or not 0 < frequency_rel_tol <= _GRID_REL_TOL:
        raise ValueError("invalid OCEAN frequency-grid tolerance")
    traces: dict[str, tuple[list[float], list[float]]] = {}
    result_dirs: dict[str, str | None] = {}
    s12_real = (export_dir / "s12_real.txt").is_file()
    s12_imag = (export_dir / "s12_imag.txt").is_file()
    if s12_real != s12_imag:
        raise ValueError("OCEAN S12 real and imaginary exports must be present together")
    signals = ("s11", "s21", "s22", "s12") if s12_real else ("s11", "s21", "s22")
    for signal in signals:
        for component in ("real", "imag"):
            key = f"{signal}_{component}"
            path = export_dir / f"{key}.txt"
            traces[key] = read_ocnprint_trace(
                path,
                header_fragment=f'{component}(getData("{signal}"',
            )
            header = next(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            match = re.search(r'\?resultsDir\s+"([^"]+)"', header)
            result_dirs[key] = match.group(1) if match else None
    for signal in ("NF", "NFmin", "F", "Fmin"):
        path = export_dir / f"{signal}.txt"
        traces[signal] = read_ocnprint_trace(
            path, header_fragment=f'getData("{signal}"',
        )
        header = next(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        match = re.search(r'\?resultsDir\s+"([^"]+)"', header)
        result_dirs[signal] = match.group(1) if match else None
        if signal in {"NF", "NFmin"}:
            if "(dB)" not in header:
                raise ValueError(f"{signal} ocnPrint header lacks dB units")

    if len(set(result_dirs.values())) != 1:
        raise ValueError("ocnPrint traces have different resultsDir provenance")
    if s12_real and next(iter(result_dirs.values())) is None:
        raise ValueError("OCEAN S12 requires explicit resultsDir provenance")

    frequencies = traces["s11_real"][0]
    for key, (other_frequencies, _) in traces.items():
        if len(other_frequencies) != len(frequencies) or any(
            not math.isclose(left, right, rel_tol=frequency_rel_tol, abs_tol=1e-3)
            for left, right in zip(frequencies, other_frequencies, strict=True)
        ):
            raise ValueError(f"ocnPrint frequency grid differs for {key}")

    complex_traces = {
        signal: [
            complex(real, imag)
            for real, imag in zip(traces[f"{signal}_real"][1], traces[f"{signal}_imag"][1], strict=True)
        ]
        for signal in signals
    }
    rows: list[dict[str, float]] = []
    for index, frequency in enumerate(frequencies):
        row = {"freq_hz": frequency, "freq_ghz": frequency / 1e9}
        for signal in ("s11", "s21", "s22"):
            row[f"{signal}_db"] = magnitude_db([complex_traces[signal][index]])[0]
        for figure, factor in (("NF", "F"), ("NFmin", "Fmin")):
            db = traces[figure][1][index]
            linear = traces[factor][1][index]
            if linear <= 0 or not math.isclose(10 * math.log10(linear), db, abs_tol=5e-5):
                raise ValueError(f"{factor} disagrees with {figure} at frequency index {index}")
            row[figure.lower() + "_db"] = db
        rows.append(row)
    stability = (
        summarize_sampled_stability(*(complex_traces[signal] for signal in ("s11", "s21", "s12", "s22")))
        if s12_real else None
    )
    return rows, stability


def read_ocean_vdd_current(report_path: Path) -> float:
    lines = report_path.read_text(encoding="utf-8").splitlines()
    current_lines = [line for line in lines if line.startswith("vdd_current=")]
    if len(current_lines) != 1:
        raise ValueError("OCEAN report must contain exactly one vdd_current")
    try:
        current = float(current_lines[0].split("=", 1)[1])
    except ValueError as exc:
        raise ValueError("invalid OCEAN vdd_current") from exc
    if not math.isfinite(current) or current >= 0:
        raise ValueError("OCEAN supply current must flow out of VDD")
    return -current * 1e3


def read_ocean_device_op(
    path: Path, *, expected_psf: str, instances: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    if (not instances or len(set(instances)) != len(instances)
            or any(re.fullmatch(r"M[1-9][0-9]*", name) is None for name in instances)):
        raise ValueError("OCEAN operating-point instance list is invalid")
    lines = path.read_text(encoding="utf-8").splitlines()
    expected_keys = {f"{instance}:{field}" for instance in instances for field in _CASCODE_OP_FIELDS}
    if len(lines) != len(expected_keys) + 1 or lines[0] != f"source_result={expected_psf}":
        raise ValueError("OCEAN operating-point source or field count differs")
    values: dict[str, float] = {}
    for line in lines[1:]:
        key, separator, text = line.partition("=")
        if not separator or key not in expected_keys or key in values:
            raise ValueError("OCEAN operating-point field is invalid or duplicated")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("OCEAN operating-point value is not numeric") from exc
        if not math.isfinite(value):
            raise ValueError("OCEAN operating-point value is nonfinite")
        values[key] = value
    if set(values) != expected_keys:
        raise ValueError("OCEAN operating-point fields are incomplete")
    return {
        instance: {field: values[f"{instance}:{field}"] for field in _CASCODE_OP_FIELDS}
        for instance in instances
    }


def read_ocean_cascode_op(path: Path, *, expected_psf: str) -> dict[str, dict[str, float]]:
    return read_ocean_device_op(path, expected_psf=expected_psf, instances=("M1", "M2"))
