from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii, require_same_frequency_grid, summarize_noise
from orfadc.cadence.psfascii_reader import (
    magnitude_db, parse_complex_trace, parse_dc_values, parse_scalar_trace,
    parse_struct_values, parse_trace_kinds,
)
from orfadc.cadence.stability_metrics import summarize_sampled_stability
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.experiments.audit_pdk_hybrid_three_stage import validate_hybrid_topology
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "remote_netlist": "remote_netlist.scs", "ade_companion": "ade_e.scs",
    "wrapper": "wrapper.scs", "remote_wrapper": "remote_wrapper.scs",
    "run_status": "run_status.json", "spectre_log": "spectre.log",
    "stdout": "stdout.log", "stderr": "stderr.log", "dc_raw": "dcOp.dc",
    "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
    "touchstone": "rf_default_three_stage.s2p",
}


def default_rf_geometry(netlist: str) -> tuple[str, str, str, str]:
    entries = re.findall(
        r"^M[1-6] \([^\n]+\) (\S+) lr=(\S+) wr=(\S+) nr=(\S+)",
        netlist, re.MULTILINE,
    )
    if len(entries) != 6 or len(set(entries)) != 1:
        raise ValueError("RF device default geometry must agree across six instances")
    return entries[0]


def _check_creation(create_dir: Path, source: bytes, companion: bytes) -> str:
    if not create_dir.is_dir() or create_dir.is_symlink():
        raise ValueError("RF device OA creation archive must be an ordinary directory")
    created = json.loads((create_dir / "run_status.json").read_text(encoding="utf-8"))
    script = (create_dir / "create_rf_default_three_stage.ocn").read_bytes()
    if (
        created.get("status") != "oa_netlist_ok"
        or created.get("source") != "cadence_ocean_user_library"
        or created.get("pdk_write") is not False
        or created.get("callback_invoked") is not False
        or created.get("ocean_returncode") != 0
        or created.get("script_sha256") != hashlib.sha256(script).hexdigest()
        or (create_dir / "remote_script.ocn").read_bytes() != script
        or created.get("oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or (create_dir / "input.scs").read_bytes() != source
        or (create_dir / "ade_e.scs").read_bytes() != companion
        or (create_dir / "sch.oa").stat().st_size == 0
        or "check_return=(0 0)" not in (create_dir / "schematic_report.txt").read_text(encoding="utf-8")
        or "save_return=t instances=58 nets=26" not in (create_dir / "schematic_report.txt").read_text(encoding="utf-8")
        or "status=ok" not in (create_dir / "netlist_report.txt").read_text(encoding="utf-8")
        or len(re.findall(rb'mosMaster "M[1-6]" nil list\(', script)) != 6
    ):
        raise ValueError("RF device OA source, default properties, or creation report differs")
    return hashlib.sha256((create_dir / "sch.oa").read_bytes()).hexdigest()


def validate_oa_source_loaded(create_dir: Path, wrapper: str, log: str) -> None:
    report = (create_dir / "netlist_report.txt").read_text(encoding="utf-8")
    match = re.fullmatch(r'netlist_result="(/[^"\n]+/input\.scs)"\nstatus=ok\n?', report)
    if match is None:
        raise ValueError("OA creation report lacks an unambiguous netlist path")
    source_path = match[1]
    companion_path = source_path.rsplit("/", 1)[0] + "/ade_e.scs"
    if (
        wrapper.splitlines().count(f'include "{source_path}"') != 1
        or len(re.findall(r"^Reading file:\s+" + re.escape(source_path) + r"$", log, re.MULTILINE)) != 1
        or len(re.findall(r"^Reading file:\s+" + re.escape(companion_path) + r"$", log, re.MULTILINE)) != 1
    ):
        raise ValueError("Spectre did not load the OA source and companion from the creation report")


def extract_pdk_rf_default_three_stage(run_dir: Path, create_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("RF default run must be an ordinary directory")
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
        or status.get("physical_qualification") is not False
        or status.get("cdf_callback_validated") is not False
        or status.get("cdf_parameters_default") is not True
        or status.get("passive_model_kind") != "ideal_lumped_and_mutual_inductor"
        or type(status.get("host_available_gib_before")) not in {int, float}
        or status["host_available_gib_before"] < 2.66
        or status.get("oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("oa_netlist_sha256_after") != status["oa_netlist_sha256"]
        or status.get("downloads") != {
            name: True for name in (
                "spectre.log", "dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp",
                "rf_default_three_stage.s2p",
            )
        }
        or (run_dir / "remote_netlist.scs").read_bytes() != source
        or (run_dir / "remote_wrapper.scs").read_bytes() != wrapper
    ):
        raise ValueError("RF default remote source snapshots or run status differ")
    netlist = source.decode("utf-8")
    validate_hybrid_topology(netlist)
    geometry = default_rf_geometry(netlist)
    wrapper_text = wrapper.decode("ascii").replace("\r\n", "\n")
    if (
        not re.search(r'^include "[^"\n]+/input\.scs"$', wrapper_text, re.MULTILINE)
        or len(re.findall(r"^dcOp dc$", wrapper_text, re.MULTILINE)) != 1
        or len(re.findall(r"^dcOpInfo info what=oppoint where=rawfile$", wrapper_text, re.MULTILINE)) != 1
        or len(re.findall(r"^sp sp start=8G stop=12G lin=160 ports=\[PORT1 PORT2\]", wrapper_text, re.MULTILINE)) != 1
        or "donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport" not in wrapper_text
    ):
        raise ValueError("RF default Spectre wrapper analyses differ")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    validate_oa_source_loaded(create_dir, wrapper_text, log)
    if (
        not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("RF default Spectre warning profile or completion differs")

    touchstone = parse_touchstone_2port(run_dir / "rf_default_three_stage.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("RF default Touchstone references differ")
    frequency = None
    sparams = {}
    max_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", signal)
        if frequency is None:
            frequency = grid
        elif grid != frequency:
            raise ValueError("RF default S-parameter frequency grids differ")
        sparams[signal] = values
        for sample_frequency, value, row in zip(grid, values, touchstone, strict=True):
            if not math.isclose(sample_frequency, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("RF default Touchstone frequency grid differs")
            max_touchstone_delta = max(
                max_touchstone_delta,
                abs(value - complex(row[f"{signal}_real"], row[f"{signal}_imag"])),
            )
    if (
        frequency is None or len(frequency) != 161 or max_touchstone_delta > 1e-8
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
    ):
        raise ValueError("RF default SP grid incomplete or inconsistent")
    noise_path = run_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    if any(kinds.get(name) != kind for name, kind in (
        ("NF", "dB"), ("NFmin", "dB"), ("F", "Noise factor"), ("Fmin", "Noise factor"),
    )):
        raise ValueError("RF default noise units differ")
    noise = noise_rows_from_psfascii(noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin")
    rows = [
        {
            "freq_hz": sample, "freq_ghz": sample / 1e9,
            **{f"{signal}_db": magnitude_db([sparams[signal][index]])[0]
               for signal in ("s11", "s21", "s22")},
            "nf_db": float(noise[index]["nf_db"]), "nfmin_db": float(noise[index]["nfmin_db"]),
        }
        for index, sample in enumerate(frequency)
    ]
    require_same_frequency_grid(noise, rows)
    for factor, db in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        grid, values = parse_scalar_trace(noise_path, factor)
        if grid != frequency or any(
            value <= 0 or not math.isclose(10 * math.log10(value), row[db], abs_tol=1e-6)
            for value, row in zip(values, rows, strict=True)
        ):
            raise ValueError("RF default noise factor disagrees with noise figure")
    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    if current_ma <= 0 or not math.isfinite(current_ma):
        raise ValueError("RF default supply current invalid")
    devices = {}
    for index in range(1, 7):
        name = f"M{index}"
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance=name, struct_type="bsim4")
        fields = ("ids", "vgs", "vds", "vdsat", "vth", "gm", "gds", "region")
        devices[name] = {key: op[key] for key in fields}
        if any(not math.isfinite(op[key]) for key in fields) or any(
            op[key] <= 0 for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds")
        ) or op["vds"] <= op["vdsat"]:
            raise ValueError("RF default MOS operating point invalid")
    if (
        not math.isclose(devices["M1"]["ids"], devices["M2"]["ids"], rel_tol=5e-3)
        or not math.isclose(sum(devices[f"M{i}"]["ids"] for i in range(2, 7)), current_ma / 1e3, rel_tol=1e-3)
    ):
        raise ValueError("RF default MOS currents disagree with supply KCL")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.1 * current_ma,
    }
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "pdk_rf_default_ideal_passive_three_stage_probe",
        "circuit_class": "pdk_rf_default_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "default RF active devices with ideal passives; not a qualified LNA or paper result",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "load_capacitance_ff": 62.0, "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": metrics, "points": len(rows),
        "stability": summarize_sampled_stability(*(sparams[name] for name in ("s11", "s21", "s12", "s22"))),
        "device_op": devices, "maximum_touchstone_psfascii_complex_delta": max_touchstone_delta,
        "host_available_gib_before": status["host_available_gib_before"],
        "oa_create_run_id": create_dir.name, "oa_schematic_sha256": oa_hash,
        "default_geometry_signature_sha256": hashlib.sha256("|".join(geometry).encode("utf-8")).hexdigest(),
        "cdf_parameters_default": True, "physical_qualification": False,
        "cdf_callback_validated": False, "spectre_warning_count": 5,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_rf_default_three_stage(run_dir: Path, create_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    entries = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8")).get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("RF default evidence lacks required artifacts")
    rows, rebuilt = extract_pdk_rf_default_three_stage(run_dir, create_dir)
    if saved != rebuilt:
        raise ValueError("RF default metrics differ from raw Spectre archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("RF default waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(stored[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for stored, row in zip(stored_rows, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("RF default waveform CSV differs from raw Spectre archive")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private default-RF-device three-stage probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--create-dir", required=True, type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_pdk_rf_default_three_stage(args.run_dir, args.create_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_rf_default_three_stage(args.run_dir, args.create_dir)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
