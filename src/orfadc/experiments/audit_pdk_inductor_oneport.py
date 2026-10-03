from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.passive_quality import oneport_impedance, summarize_inductor_oneport
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ARTIFACTS = {
    "metrics": "metrics.json", "run_status": "run_status.json",
    "netlist": "netlist.scs", "remote_netlist": "remote_netlist.scs",
    "ade_companion": "ade_e.scs", "wrapper": "wrapper.scs",
    "remote_wrapper": "remote_wrapper.scs", "spectre_log": "spectre.log",
    "sp_raw": "sp.sp", "stdout": "stdout.log", "stderr": "stderr.log",
    "waveforms": "quality.csv",
}
_COLUMNS = ("freq_hz", "s11_real", "s11_imag", "z_real_ohm", "z_imag_ohm", "q", "l_effective_h")


def extract_pdk_inductor_oneport(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("PDK one-port archive must be an ordinary directory")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    variant = status.get("geometry_variant", "default")
    if variant not in {"default", "w7_property_only"} or status.get("cdf_callback_validated") is True:
        raise ValueError("PDK one-port geometry provenance is unsupported")
    source = (run_dir / "netlist.scs").read_bytes()
    if (
        status.get("status") != "simulation_ok"
        or status.get("spectre_returncode") != 0
        or status.get("physical_qualification") is not False
        or status.get("geometry_sweep_verified") is not False
        or status.get("spec_pass", "missing") is not None
        or hashlib.sha256(source).hexdigest() != status.get("oa_netlist_sha256")
        or status.get("oa_netlist_sha256_after") != status.get("oa_netlist_sha256")
        or source != (run_dir / "remote_netlist.scs").read_bytes()
        or (run_dir / "wrapper.scs").read_bytes() != (run_dir / "remote_wrapper.scs").read_bytes()
        or not (run_dir / "ade_e.scs").is_file()
    ):
        raise ValueError("PDK one-port source snapshot or run status disagrees")
    source_text = source.decode("utf-8")
    if (
        len(re.findall(r"^L1 \([^\s()]+ 0 0\) [A-Za-z][A-Za-z0-9_]*\b", source_text, re.MULTILINE)) != 1
        or len(re.findall(r"^PORT1 \([^\s()]+ 0\) port r=50 num=1\b", source_text, re.MULTILINE)) != 1
        or 'include "ade_e.scs"' not in source_text
    ):
        raise ValueError("PDK one-port netlist structure is not the expected default instance")
    if variant == "w7_property_only" and not re.search(r"^L1 \([^\n]+\) [^\n]+\bw=7u\b", source_text, re.MULTILINE):
        raise ValueError("PDK one-port width property did not propagate")
    wrapper = (run_dir / "wrapper.scs").read_text(encoding="utf-8")
    wrapper_match = re.fullmatch(
        r'simulator lang=spectre\ninclude "([^"\n]+/input\.scs)"\n'
        r'sp sp ports=\[PORT1\] start=500M stop=30G lin=590\n', wrapper,
    )
    if wrapper_match is None:
        raise ValueError("PDK one-port wrapper contains an unexpected analysis")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    completion = re.search(r"spectre completes with (\d+) errors?, (\d+) warnings?", log)
    if (
        completion is None or int(completion[1]) != 0
        or not re.search(r"Total time required for sp analysis `sp'", log)
        or not re.search(r"^Reading file:\s+" + re.escape(wrapper_match[1]) + r"$", log, re.MULTILINE)
        or not re.search(r"^Reading file:\s+\S+/ade_e\.scs$", log, re.MULTILINE)
    ):
        raise ValueError("PDK one-port Spectre completion or source loading is missing")
    frequency, reflection = parse_complex_trace(run_dir / "sp.sp", "s11")
    if (
        len(frequency) != 591
        or not math.isclose(frequency[0], 0.5e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 30e9, rel_tol=1e-12)
    ):
        raise ValueError("PDK one-port frequency grid is incomplete")
    rows = []
    for sample, gamma in zip(frequency, reflection, strict=True):
        impedance = oneport_impedance(gamma, 50)
        rows.append({
            "freq_hz": sample, "s11_real": gamma.real, "s11_imag": gamma.imag,
            "z_real_ohm": impedance.real, "z_imag_ohm": impedance.imag,
            "q": impedance.imag / impedance.real,
            "l_effective_h": impedance.imag / (2 * math.pi * sample),
        })
    screen = summarize_inductor_oneport(
        frequency, reflection, reference_ohm=50,
        band_low_hz=8e9, band_high_hz=12e9,
        minimum_q=15, minimum_srf_ratio=1.2,
    )
    payload = {
        "schema_version": 1, "status": "pdk_default_oneport_measured_with_warnings"
        if int(completion[2]) else "pdk_default_oneport_measured",
        "simulation_status": "ok", "source": "cadence_spectre",
        "source_run_kind": "oa_default_pdk_spiral_direct_spectre",
        "circuit_class": "passive_oneport", "model_kind": "authorized_pdk_default_spiral",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "analysis": ["sp"], "oneport_reference_ohm": 50.0,
        "physical_qualification": False, "coupling_qualification": False,
        "geometry_sweep_verified": False,
        "scope": "Default PDK spiral one-port SP response; no geometry, corner, EM or PEX qualification",
        "points": len(rows), "spectre_warning_count": int(completion[2]),
        "spectre_warning_codes": sorted(set(re.findall(r"WARNING \(([A-Z0-9-]+)\)", log))),
        "oa_netlist_sha256": status["oa_netlist_sha256"],
        "metrics": screen,
        "threshold_provenance": "project teaching screen Q>=15 and SRF>=1.2x band edge, not a paper or PDK requirement",
    }
    if variant == "w7_property_only":
        payload.update({
            "status": "pdk_property_perturbation_measured_with_warnings"
            if int(completion[2]) else "pdk_property_perturbation_measured",
            "source_run_kind": "oa_property_perturbation_direct_spectre",
            "model_kind": "authorized_pdk_spiral_property_perturbation",
            "scope": "One w property perturbation with no CDF callback or PCell validation",
            "geometry_variant": variant, "cdf_callback_validated": False,
        })
    validate_metrics_payload(payload)
    return rows, payload


def finalize_pdk_inductor_oneport(run_dir: Path) -> dict:
    _require_private_path(run_dir)
    rows, payload = extract_pdk_inductor_oneport(run_dir)
    with (run_dir / "quality.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(run_dir / "metrics.json", payload)
    write_evidence_manifest(run_dir, _ARTIFACTS)
    audit_pdk_inductor_oneport(run_dir)
    return payload


def audit_pdk_inductor_oneport(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    if any(manifest["artifacts"].get(key, {}).get("path") != path for key, path in _ARTIFACTS.items()):
        raise ValueError("PDK one-port evidence lacks required artifacts")
    rows, rebuilt = extract_pdk_inductor_oneport(run_dir)
    if saved != rebuilt:
        raise ValueError("PDK one-port metrics differ from raw Spectre data")
    with (run_dir / "quality.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("PDK one-port CSV columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(item[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for item, row in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("PDK one-port CSV differs from raw Spectre data")
    return {"status": "verified", "run_id": run_dir.name,
            "physical_qualification": False, "not_lna_result": True}


def compare_pdk_inductor_width_pair(default_dir: Path, variant_dir: Path) -> dict:
    audit_pdk_inductor_oneport(default_dir)
    audit_pdk_inductor_oneport(variant_dir)
    default = read_evidenced_metrics(default_dir)
    variant = read_evidenced_metrics(variant_dir)
    if (
        default["source_run_kind"] != "oa_default_pdk_spiral_direct_spectre"
        or variant["source_run_kind"] != "oa_property_perturbation_direct_spectre"
        or variant.get("geometry_variant") != "w7_property_only"
        or variant.get("cdf_callback_validated") is not False
    ):
        raise ValueError("PDK one-port pair has incompatible provenance")
    source_a = (default_dir / "netlist.scs").read_text(encoding="utf-8")
    source_b = (variant_dir / "netlist.scs").read_text(encoding="utf-8")

    def circuit_lines(source: str, expected_width: str) -> list[str]:
        lines = [line for line in source.splitlines() if not line.startswith("//")]
        width_lines = [index for index, line in enumerate(lines) if line.startswith("L1 (")]
        if len(width_lines) != 1 or not re.search(r"\bw=" + expected_width + r"\b", lines[width_lines[0]]):
            raise ValueError("PDK one-port width pair lacks the expected width")
        lines[width_lines[0]] = re.sub(r"\bw=" + expected_width + r"\b", "w=WIDTH", lines[width_lines[0]])
        return lines

    if circuit_lines(source_a, "6u") != circuit_lines(source_b, "7u"):
        raise ValueError("PDK one-port netlists differ beyond the width property")
    frequency_a, reflection_a = parse_complex_trace(default_dir / "sp.sp", "s11")
    frequency_b, reflection_b = parse_complex_trace(variant_dir / "sp.sp", "s11")
    if frequency_a != frequency_b:
        raise ValueError("PDK one-port width pair uses different frequency grids")
    maximum_delta = max(abs(left - right) for left, right in zip(reflection_a, reflection_b, strict=True))
    if maximum_delta <= 1e-6:
        raise ValueError("PDK one-port width change did not measurably affect model response")
    return {
        "status": "verified", "default_run_id": default_dir.name,
        "variant_run_id": variant_dir.name,
        "maximum_complex_s11_delta": maximum_delta,
        "minimum_q_default": default["metrics"]["minimum_q_in_band"],
        "minimum_q_variant": variant["metrics"]["minimum_q_in_band"],
        "cdf_callback_validated": False, "physical_qualification": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit an authorized private default PDK spiral one-port run")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--compare-to", type=Path)
    args = parser.parse_args()
    if args.finalize and args.compare_to is not None:
        parser.error("--finalize and --compare-to are mutually exclusive")
    if args.compare_to is not None:
        result = compare_pdk_inductor_width_pair(args.run_dir, args.compare_to)
        print(f"status={result['status']} maximum_complex_s11_delta={result['maximum_complex_s11_delta']:.9g}")
        return 0
    result = finalize_pdk_inductor_oneport(args.run_dir) if args.finalize else audit_pdk_inductor_oneport(args.run_dir)
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
