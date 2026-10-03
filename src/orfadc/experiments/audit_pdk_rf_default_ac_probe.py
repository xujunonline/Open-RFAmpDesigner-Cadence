from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_hybrid_ac_probe import (
    _COLUMNS, _NODES, _STEPS, ac_voltage_steps,
)
from orfadc.experiments.audit_pdk_hybrid_three_stage import validate_hybrid_topology
from orfadc.experiments.audit_pdk_rf_default_three_stage import (
    _check_creation, default_rf_geometry, validate_oa_source_loaded,
)
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "remote_netlist": "remote_netlist.scs", "ade_companion": "ade_e.scs",
    "wrapper": "wrapper.scs", "remote_wrapper": "remote_wrapper.scs",
    "run_status": "run_status.json", "spectre_log": "spectre.log",
    "stdout": "stdout.log", "stderr": "stderr.log", "ac_raw": "ac.ac",
}


def extract_pdk_rf_default_ac_probe(run_dir: Path, create_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("AC probe must be an ordinary directory")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    source = (run_dir / "netlist.scs").read_bytes()
    companion = (run_dir / "ade_e.scs").read_bytes()
    wrapper = (run_dir / "wrapper.scs").read_bytes()
    oa_hash = _check_creation(create_dir, source, companion)
    if (
        status.get("status") != "simulation_ok"
        or status.get("source") != "cadence_spectre"
        or status.get("spectre_returncode") != 0
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or status.get("probe_kind") != "parallel_ideal_ac_source"
        or status.get("cdf_parameters_default") is not True
        or status.get("cdf_callback_validated") is not False
        or type(status.get("host_available_gib_before")) not in {int, float}
        or status["host_available_gib_before"] < 2.66
        or status.get("oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("oa_netlist_sha256_after") != status["oa_netlist_sha256"]
        or status.get("downloads") != {"spectre.log": True, "ac.ac": True}
        or (run_dir / "remote_netlist.scs").read_bytes() != source
        or (run_dir / "remote_wrapper.scs").read_bytes() != wrapper
    ):
        raise ValueError("AC probe source snapshots or remote run status differ")
    netlist = source.decode("utf-8")
    validate_hybrid_topology(netlist)
    geometry = default_rf_geometry(netlist)
    wrapper_text = wrapper.decode("ascii").replace("\r\n", "\n")
    if (
        not re.search(r'^include "[^"\n]+/input\.scs"$', wrapper_text, re.MULTILINE)
        or len(re.findall(r"^VPROBE \(in 0\) vsource dc=0 mag=1$", wrapper_text, re.MULTILINE)) != 1
        or len(re.findall(r"^ac ac start=8G stop=12G lin=160$", wrapper_text, re.MULTILINE)) != 1
        or len(wrapper_text.splitlines()) != 4
    ):
        raise ValueError("AC probe wrapper is not the single-source internal-node diagnostic")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    validate_oa_source_loaded(create_dir, wrapper_text, log)
    if (
        not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("AC probe Spectre warning profile or completion differs")
    traces = {name: parse_complex_trace(run_dir / "ac.ac", name) for name in _NODES}
    frequency = traces["in"][0]
    if any(traces[name][0] != frequency for name in _NODES) or (
        len(frequency) != 161
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
    ):
        raise ValueError("AC probe frequency grids differ or are incomplete")
    rows = [
        {"freq_hz": sample, **ac_voltage_steps({name: traces[name][1][index] for name in _NODES})}
        for index, sample in enumerate(frequency)
    ]
    center = rows[80]
    if not math.isclose(center["freq_hz"], 10e9, rel_tol=1e-12):
        raise ValueError("AC probe does not include 10 GHz center")
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "pdk_rf_default_internal_ac_probe",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "parallel ideal AC source internal-node diagnostic; voltage ratios are not S21 or LNA pass metrics",
        "analysis": ["ac"], "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": {f"{name}_voltage_db_at_10ghz": center[name] for name in (*_STEPS, "overall_voltage_db")},
        "points": len(rows), "host_available_gib_before": status["host_available_gib_before"],
        "oa_create_run_id": create_dir.name, "oa_schematic_sha256": oa_hash,
        "default_geometry_signature_sha256": hashlib.sha256("|".join(geometry).encode("utf-8")).hexdigest(),
        "cdf_parameters_default": True, "physical_qualification": False, "cdf_callback_validated": False,
        "spectre_warning_count": 5,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_rf_default_ac_probe(run_dir: Path, create_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    entries = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8")).get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("AC probe evidence lacks required artifacts")
    rows, rebuilt = extract_pdk_rf_default_ac_probe(run_dir, create_dir)
    if saved != rebuilt:
        raise ValueError("AC probe metrics differ from raw Spectre archive")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("AC probe waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(stored[name]), row[name], rel_tol=1e-10, abs_tol=1e-12)
        for stored, row in zip(stored_rows, rows, strict=True) for name in _COLUMNS
    ):
        raise ValueError("AC probe waveform CSV differs from raw Spectre archive")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private default-RF-device internal-node AC probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--create-dir", required=True, type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_pdk_rf_default_ac_probe(args.run_dir, args.create_dir)
        if (args.run_dir / "metrics.json").exists() or (args.run_dir / "waveforms.csv").exists():
            raise FileExistsError("refusing to overwrite AC probe result")
        with (args.run_dir / "waveforms.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        write_json(args.run_dir / "metrics.json", payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_rf_default_ac_probe(args.run_dir, args.create_dir)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
