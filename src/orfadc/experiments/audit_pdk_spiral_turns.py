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
from orfadc.experiments.audit_pdk_inductor_oneport import audit_pdk_inductor_oneport
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_spiral_turns import render_spiral_turns_netlist, render_spiral_turns_wrapper
from orfadc.metric_contract import validate_metrics_payload


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COLUMNS = ("freq_hz", "s11_real", "s11_imag", "z_real_ohm", "z_imag_ohm", "q", "l_effective_h")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "quality.csv", "run_status": "run_status.json",
    "netlist": "netlist.scs", "wrapper": "wrapper.scs", "ade_companion": "ade_e.scs",
    "remote_netlist": "remote_netlist.scs", "remote_wrapper": "remote_wrapper.scs",
    "remote_companion": "remote_ade_e.scs", "spectre_log": "spectre.log",
    "sp_raw": "sp.sp", "stdout": "stdout.log", "stderr": "stderr.log",
}


def extract_pdk_spiral_turns(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("spiral turns archive is missing or unsafe")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    source_id = status.get("source_run_id")
    turns = status.get("turns")
    if not isinstance(source_id, str) or _RUN_ID.fullmatch(source_id) is None:
        raise ValueError("spiral turns source ID is invalid")
    source_dir = _PRIVATE_ROOT / "passive_quality_reference" / source_id
    audit_pdk_inductor_oneport(source_dir)
    source_status = json.loads((source_dir / "run_status.json").read_text(encoding="utf-8"))
    if source_status.get("geometry_variant", "default") != "default":
        raise ValueError("spiral turns source is not the default standard instance")
    source = (source_dir / "netlist.scs").read_bytes()
    derived = render_spiral_turns_netlist(source, turns)
    wrapper = render_spiral_turns_wrapper()
    companion = (source_dir / "ade_e.scs").read_bytes()
    expected_downloads = dict.fromkeys((
        "spectre.log", "sp.sp", "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs",
    ), True)
    if (
        status.get("status") != "simulation_recorded"
        or status.get("run_id") != run_dir.name
        or status.get("spectre_returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("source_manifest_sha256") != hashlib.sha256(
            (source_dir / "evidence_manifest.json").read_bytes(),
        ).hexdigest()
        or status.get("source_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("derived_netlist_sha256") != hashlib.sha256(derived).hexdigest()
        or status.get("wrapper_sha256") != hashlib.sha256(wrapper).hexdigest()
        or status.get("downloads") != expected_downloads
        or any(status.get(key) is not False for key in (
            "pdk_write", "user_oa_write", "cdf_callback_validated",
            "geometry_sweep_verified", "physical_qualification",
        ))
        or status.get("not_lna_result") is not True or status.get("spec_pass") is not None
        or any((run_dir / name).read_bytes() != expected for name, expected in (
            ("netlist.scs", derived), ("remote_netlist.scs", derived),
            ("wrapper.scs", wrapper), ("remote_wrapper.scs", wrapper),
            ("ade_e.scs", companion), ("remote_ade_e.scs", companion),
        ))
    ):
        raise ValueError("spiral turns source, derived netlist, or status differs")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    loaded = {}
    for name in ("wrapper", "netlist", "ade_e"):
        paths = re.findall(r"(?m)^Reading file:\s+(/[^\s]+/" + name + r"\.scs)$", log)
        if len(paths) != 1:
            raise ValueError("spiral turns Spectre log lacks a source file")
        loaded[name] = paths[0].rsplit("/", 1)[0]
    if (
        len(set(loaded.values())) != 1
        or not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("spiral turns Spectre warning or source profile differs")
    frequency, reflection = parse_complex_trace(run_dir / "sp.sp", "s11")
    if (
        len(frequency) != 591 or not math.isclose(frequency[0], 0.5e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 30e9, rel_tol=1e-12)
    ):
        raise ValueError("spiral turns frequency grid is incomplete")
    rows = []
    for sample, gamma in zip(frequency, reflection, strict=True):
        impedance = oneport_impedance(gamma, 50.0)
        rows.append({
            "freq_hz": sample, "s11_real": gamma.real, "s11_imag": gamma.imag,
            "z_real_ohm": impedance.real, "z_imag_ohm": impedance.imag,
            "q": impedance.imag / impedance.real,
            "l_effective_h": impedance.imag / (2 * math.pi * sample),
        })
    screen = summarize_inductor_oneport(
        frequency, reflection, reference_ohm=50.0,
        band_low_hz=8e9, band_high_hz=12e9,
        minimum_q=15.0, minimum_srf_ratio=1.2,
    )
    base_freq, base_reflection = parse_complex_trace(source_dir / "sp.sp", "s11")
    if frequency != base_freq:
        raise ValueError("spiral turns and default source grids differ")
    maximum_delta = max(abs(left - right) for left, right in zip(reflection, base_reflection, strict=True))
    if maximum_delta <= 1e-6:
        raise ValueError("spiral turns netlist change had no measurable response")
    payload = {
        "schema_version": 1, "status": "pdk_turns_property_probe_measured_with_warnings",
        "simulation_status": "ok", "source": "cadence_spectre",
        "source_run_kind": "oa_netlist_copy_nr_property_perturbation",
        "circuit_class": "passive_oneport", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "Direct Spectre nr property sensitivity from a default OA netlist copy; no new OA or physical qualification",
        "analysis": ["sp"], "oneport_reference_ohm": 50.0, "points": len(rows),
        "turns_property": turns, "source_run_id": source_id,
        "source_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(derived).hexdigest(),
        "maximum_complex_s11_delta_from_default": maximum_delta,
        "metrics": screen,
        "spectre_warning_count": 5, "spectre_warning_codes": ["SFE-1131"],
        "threshold_provenance": "project teaching screen Q>=15 and SRF>=1.2x band edge; not a PDK geometry rule",
        "physical_qualification": False, "coupling_qualification": False,
        "geometry_sweep_verified": False, "cdf_callback_validated": False,
        "host_available_gib_before": status["host_available_gib_before"],
    }
    validate_metrics_payload(payload)
    return rows, payload


def finalize_pdk_spiral_turns(run_dir: Path) -> dict:
    rows, payload = extract_pdk_spiral_turns(run_dir)
    with (run_dir / "quality.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(run_dir / "metrics.json", payload)
    write_evidence_manifest(run_dir, _ARTIFACTS)
    audit_pdk_spiral_turns(run_dir)
    return payload


def audit_pdk_spiral_turns(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    if any(manifest["artifacts"].get(key, {}).get("path") != path for key, path in _ARTIFACTS.items()):
        raise ValueError("spiral turns archive lacks a source or raw artifact")
    rows, rebuilt = extract_pdk_spiral_turns(run_dir)
    if saved != rebuilt:
        raise ValueError("spiral turns metrics differ from raw Spectre data")
    with (run_dir / "quality.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("spiral turns waveform columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(item[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for item, row in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("spiral turns waveform CSV differs from raw Spectre data")
    return {"status": "verified", "run_id": run_dir.name,
            "physical_qualification": False, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private PDK spiral turns probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = finalize_pdk_spiral_turns(args.run_dir) if args.finalize else audit_pdk_spiral_turns(args.run_dir)
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
