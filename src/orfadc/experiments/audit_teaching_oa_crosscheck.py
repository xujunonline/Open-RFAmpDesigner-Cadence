from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.ocean_ascii import read_ocnprint_trace, read_ocean_vdd_current
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_teaching_oa import _PUBLIC_MODEL, audit_teaching_oa
from orfadc.experiments.extract_active_oa import extract_active_oa


_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_DIRECT_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "ade_companion": "ade_e.scs", "public_model": "teaching_mos1_model.scs",
    "spectre_log": "spectre.log", "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info",
    "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
}


def compare_samples(
    frequencies: list[float], values: list[float | complex],
    exported_frequencies: list[float], exported_values: list[float | complex],
    *, name: str, value_tolerance: float,
) -> tuple[float, float]:
    if len(frequencies) != len(exported_frequencies) or len(values) != len(exported_values) or len(values) != len(frequencies):
        raise ValueError(f"{name} point counts differ")
    frequency_delta = max(abs(left - right) for left, right in zip(frequencies, exported_frequencies, strict=True))
    if any(not math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-3)
           for left, right in zip(frequencies, exported_frequencies, strict=True)):
        raise ValueError(f"{name} frequency grids differ")
    delta = max(abs(left - right) for left, right in zip(values, exported_values, strict=True))
    if not math.isfinite(delta) or delta > value_tolerance:
        raise ValueError(f"{name} differs between PSFASCII and high-precision OCEAN export")
    return frequency_delta, delta


def audit_teaching_oa_crosscheck(ocean_dir: Path, direct_dir: Path) -> dict:
    if not direct_dir.is_dir() or direct_dir.is_symlink():
        raise ValueError("direct Spectre archive must be an ordinary directory")
    ocean = read_evidenced_metrics(ocean_dir)
    audit_teaching_oa(ocean_dir)
    direct = read_evidenced_metrics(direct_dir)
    manifest = json.loads((direct_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict) or any(
        not isinstance(entries.get(key), dict) or entries[key].get("path") != name
        for key, name in _DIRECT_ARTIFACTS.items()
    ):
        raise ValueError("direct Spectre archive lacks required raw evidence")
    topology = ocean.get("teaching_topology")
    direct_kinds = {
        "inductive": "teaching_mos1_inductive_oa_netlist_direct_spectre",
        "damped": "teaching_mos1_damped_oa_netlist_direct_spectre",
    }
    if topology not in direct_kinds or ocean.get("ocn_precision_digits") != 15:
        raise ValueError("crosscheck requires a 15-digit inductive or damped OA export")
    if (
        direct.get("run_id") != direct_dir.name
        or direct.get("status") != "ok_with_warnings"
        or direct.get("simulation_status") != "ok"
        or direct.get("source") != "cadence_spectre"
        or direct.get("raw_format") != "psfascii"
        or direct.get("source_run_kind") != direct_kinds[topology]
        or direct.get("circuit_class") != ocean.get("circuit_class")
        or direct.get("model_kind") != "teaching_model"
        or direct.get("teaching_topology") != topology
        or direct.get("not_lna_result") is not True
        or direct.get("spec_pass") is not None
        or direct.get("analysis") != ["dc", "sp", "noise"]
        or direct.get("frequency_band_ghz") != ocean.get("frequency_band_ghz")
    ):
        raise ValueError("direct Spectre archive has incompatible provenance")
    for name in ("netlist.scs", "ade_e.scs", "teaching_mos1_model.scs"):
        if (ocean_dir / name).read_bytes() != (direct_dir / name).read_bytes():
            raise ValueError(f"direct and OCEAN {name} differ")
    if (direct_dir / "teaching_mos1_model.scs").read_bytes() != _PUBLIC_MODEL.read_bytes():
        raise ValueError("direct Spectre model differs from public MOS1 model")
    spectre_log = (direct_dir / "spectre.log").read_text(encoding="utf-8")
    if "spectre completes with 0 errors, 0 warnings" not in spectre_log or "SPECTRE-25" in spectre_log:
        raise ValueError("direct Spectre log is not clean")
    model_include = re.findall(r'^include "([^\"]+/teaching_mos1_model\.scs)"$',
                               (direct_dir / "netlist.scs").read_text(encoding="ascii"), re.MULTILINE)
    if len(model_include) != 1 or f"Reading file:  {model_include[0]}" not in spectre_log:
        raise ValueError("direct Spectre did not report loading the archived public model path")
    if (ocean_dir / "spectre.out").read_bytes() == (direct_dir / "spectre.log").read_bytes():
        raise ValueError("crosscheck must use a distinct direct Spectre execution")
    rows, recomputed = extract_active_oa(
        direct_dir, run_id=direct_dir.name, supply_voltage_v=1.2,
        low_ghz=8.0, high_ghz=12.0,
        source_run_kind=direct_kinds[topology],
    )
    if direct.get("points") != len(rows) or direct.get("stability") != recomputed["stability"]:
        raise ValueError("direct Spectre point count or stability differs from raw PSFASCII")
    for key, expected in recomputed["metrics"].items():
        actual = direct.get("metrics", {}).get(key)
        if type(actual) not in {int, float} or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError(f"direct Spectre {key} differs from raw PSFASCII")
    with (direct_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("direct Spectre waveform columns differ")
        saved_rows = list(reader)
    if len(saved_rows) != len(rows):
        raise ValueError("direct Spectre waveform row count differs")
    for saved_row, raw_row in zip(saved_rows, rows, strict=True):
        for key in _COLUMNS:
            try:
                actual = float(saved_row[key])
            except (ValueError, TypeError) as exc:
                raise ValueError("invalid direct Spectre waveform value") from exc
            if not math.isclose(actual, raw_row[key], rel_tol=1e-9, abs_tol=1e-8):
                raise ValueError("direct Spectre waveform CSV differs from raw PSFASCII")

    frequency_delta = 0.0
    complex_deltas = {}
    for signal in ("s11", "s21", "s12", "s22"):
        direct_f, direct_s = parse_complex_trace(direct_dir / "sp.sp", signal)
        real_f, real = read_ocnprint_trace(ocean_dir / "ocnprint" / f"{signal}_real.txt",
                                               header_fragment=f'real(getData("{signal}"')
        imag_f, imag = read_ocnprint_trace(ocean_dir / "ocnprint" / f"{signal}_imag.txt",
                                               header_fragment=f'imag(getData("{signal}"')
        if len(real_f) != len(imag_f) or any(
            not math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-3)
            for left, right in zip(real_f, imag_f, strict=True)
        ):
            raise ValueError(f"{signal} real/imag frequency grids differ")
        frequency_difference, value_difference = compare_samples(
            direct_f, direct_s, real_f, [complex(left, right) for left, right in zip(real, imag, strict=True)],
            name=signal, value_tolerance=1e-8,
        )
        frequency_delta = max(frequency_delta, frequency_difference)
        complex_deltas[signal] = value_difference
    noise_deltas = {}
    for signal in ("NF", "NFmin", "F", "Fmin"):
        direct_f, direct_values = parse_scalar_trace(direct_dir / "sp.noise.sp", signal)
        export_f, export_values = read_ocnprint_trace(
            ocean_dir / "ocnprint" / f"{signal}.txt", header_fragment=f'getData("{signal}"',
        )
        _, delta = compare_samples(
            direct_f, direct_values, export_f, export_values,
            name=signal, value_tolerance=1e-8,
        )
        noise_deltas[signal] = delta
    direct_current = recomputed["metrics"]["supply_current_ma"]
    ocean_current = read_ocean_vdd_current(ocean_dir / "ocnprint/report.txt")
    if not math.isclose(direct_current, ocean_current, rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError("direct and OCEAN supply currents differ")
    if any(
        not math.isclose(value, direct["metrics"][key], rel_tol=1e-8, abs_tol=1e-6)
        for key, value in ocean["metrics"].items()
    ):
        raise ValueError("direct and OCEAN band metrics differ")
    return {
        "status": "verified_crosscheck", "not_lna_result": True, "spec_pass": None,
        "ocean_run_id": ocean_dir.name, "direct_run_id": direct_dir.name,
        "ocean_manifest_sha256": hashlib.sha256((ocean_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "direct_manifest_sha256": hashlib.sha256((direct_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "points": len(rows), "maximum_frequency_delta_hz": frequency_delta,
        "maximum_complex_s_delta": complex_deltas, "maximum_noise_delta": noise_deltas,
        "supply_current_delta_ma": direct_current - ocean_current,
        "stability_quality": ocean["stability_quality"],
        "minimum_k": ocean["stability"]["minimum_k"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Crosscheck a public inductive/damped OA export against independent Spectre")
    parser.add_argument("ocean_dir", type=Path)
    parser.add_argument("direct_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_teaching_oa_crosscheck(args.ocean_dir, args.direct_dir)
    if args.output is not None:
        if args.output.exists():
            parser.error("refusing to overwrite existing crosscheck result")
        write_json(args.output, result)
    print(f"status={result['status']} points={result['points']} minimum_k={result['minimum_k']:.9g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
