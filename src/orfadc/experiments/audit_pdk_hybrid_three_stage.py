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
    "touchstone": "pdk_hybrid_v3.s2p",
}


def validate_hybrid_topology(netlist: str) -> None:
    if (
        len(re.findall(r"^M[1-6] \([^\n]+\) \S+\s", netlist, re.MULTILINE)) != 6
        or len(re.findall(r"^K(?:12|23|3) mutual_inductor\b", netlist, re.MULTILINE)) != 3
        or len(re.findall(r"^CN[23][PN] \(", netlist, re.MULTILINE)) != 4
        or "PORT1 (in 0) port r=50 num=1 type=sine" not in netlist
        or "PORT2 (outp outn) port r=1787 num=2 type=sine" not in netlist
        or "CL (outp outn) capacitor c=62f" not in netlist
        or "saveOptions options save=allpub" not in netlist
    ):
        raise ValueError("hybrid three-stage topology or mixed-reference load differs")
    for name in ("M1", "M2", "M3", "M4", "M5", "M6"):
        if len(re.findall(rf"^{name} \(", netlist, re.MULTILINE)) != 1:
            raise ValueError("hybrid three-stage MOS inventory differs")


def extract_pdk_hybrid_three_stage(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("hybrid run must be an ordinary directory")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    source = (run_dir / "netlist.scs").read_bytes()
    wrapper = (run_dir / "wrapper.scs").read_bytes()
    if (
        status.get("status") != "simulation_ok"
        or status.get("source") != "cadence_spectre"
        or status.get("spectre_returncode") != 0
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
        or status.get("physical_qualification") is not False
        or status.get("cdf_callback_validated") is not False
        or status.get("passive_model_kind") != "ideal_lumped_and_mutual_inductor"
        or type(status.get("host_available_gib_before")) not in {int, float}
        or status["host_available_gib_before"] < 2.66
        or status.get("oa_netlist_sha256") != hashlib.sha256(source).hexdigest()
        or status.get("oa_netlist_sha256_after") != status["oa_netlist_sha256"]
        or status.get("downloads") != {
            name: True for name in ("spectre.log", "dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp", "pdk_hybrid_v3.s2p")
        }
        or (run_dir / "remote_netlist.scs").read_bytes() != source
        or (run_dir / "remote_wrapper.scs").read_bytes() != wrapper
    ):
        raise ValueError("hybrid source snapshots or remote run status differ")
    netlist = source.decode("utf-8")
    validate_hybrid_topology(netlist)
    wrapper_text = wrapper.decode("ascii").replace("\r\n", "\n")
    if (
        not re.search(r'^include "[^"\n]+/input\.scs"$', wrapper_text, re.MULTILINE)
        or len(re.findall(r"^dcOp dc$", wrapper_text, re.MULTILINE)) != 1
        or len(re.findall(r"^dcOpInfo info what=oppoint where=rawfile$", wrapper_text, re.MULTILINE)) != 1
        or len(re.findall(r"^sp sp start=8G stop=12G lin=160 ports=\[PORT1 PORT2\]", wrapper_text, re.MULTILINE)) != 1
        or "donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport" not in wrapper_text
    ):
        raise ValueError("hybrid wrapper analyses differ")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if (
        not re.search(r"spectre completes with 0 errors,\s*5 warnings", log)
        or len(re.findall(r"WARNING \(SFE-1131\)", log)) != 5
        or "SPECTRE-25" in log
    ):
        raise ValueError("hybrid Spectre warning profile or completion differs")

    touchstone = parse_touchstone_2port(run_dir / "pdk_hybrid_v3.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("hybrid Touchstone grid or port references differ")
    frequency = None
    sparams = {}
    max_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", signal)
        if frequency is None:
            frequency = grid
        elif grid != frequency:
            raise ValueError("hybrid S-parameter frequency grids differ")
        sparams[signal] = values
        for sample_frequency, value, row in zip(grid, values, touchstone, strict=True):
            if not math.isclose(sample_frequency, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("hybrid Touchstone frequency grid differs")
            max_touchstone_delta = max(
                max_touchstone_delta,
                abs(value - complex(row[f"{signal}_real"], row[f"{signal}_imag"])),
            )
    if (
        frequency is None or len(frequency) != 161
        or not math.isclose(frequency[0], 8e9, rel_tol=1e-12)
        or not math.isclose(frequency[-1], 12e9, rel_tol=1e-12)
        or max_touchstone_delta > 1e-8
    ):
        raise ValueError("hybrid S-parameter data incomplete or inconsistent")
    noise_path = run_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    if any(kinds.get(name) != kind for name, kind in (
        ("NF", "dB"), ("NFmin", "dB"), ("F", "Noise factor"), ("Fmin", "Noise factor"),
    )):
        raise ValueError("hybrid noise trace units differ")
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
            raise ValueError("hybrid noise factor disagrees with noise figure")
    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    if not math.isfinite(current_ma) or current_ma <= 0:
        raise ValueError("hybrid supply current is invalid")
    devices = {}
    for index in range(1, 7):
        instance = f"M{index}"
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance=instance, struct_type="bsim4")
        fields = ("ids", "vgs", "vds", "vdsat", "vth", "gm", "gds", "region")
        devices[instance] = {key: op[key] for key in fields}
        if any(not math.isfinite(devices[instance][key]) for key in fields) or any(
            devices[instance][key] <= 0 for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds")
        ) or devices[instance]["vds"] <= devices[instance]["vdsat"]:
            raise ValueError("hybrid MOS operating point is invalid")
    if (
        not math.isclose(devices["M1"]["ids"], devices["M2"]["ids"], rel_tol=1e-3)
        or not math.isclose(sum(devices[f"M{i}"]["ids"] for i in range(2, 7)), current_ma / 1e3, rel_tol=1e-4)
    ):
        raise ValueError("hybrid MOS currents disagree with supply KCL")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.1 * current_ma,
    }
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "pdk_active_ideal_passive_three_stage_probe",
        "circuit_class": "pdk_hybrid_three_stage_probe", "model_kind": "authorized_pdk_private",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "authorized PDK active devices with ideal passives; not a qualified LNA or paper result",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "load_capacitance_ff": 62.0, "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": metrics, "points": len(rows),
        "stability": summarize_sampled_stability(*(sparams[name] for name in ("s11", "s21", "s12", "s22"))),
        "device_op": devices, "maximum_touchstone_psfascii_complex_delta": max_touchstone_delta,
        "host_available_gib_before": status["host_available_gib_before"],
        "physical_qualification": False, "cdf_callback_validated": False,
        "spectre_warning_count": 5,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_pdk_hybrid_three_stage(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != name
           for key, name in _ARTIFACTS.items()):
        raise ValueError("hybrid evidence lacks required artifacts")
    rows, rebuilt = extract_pdk_hybrid_three_stage(run_dir)
    if saved != rebuilt:
        raise ValueError("hybrid metrics differ from raw Spectre archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("hybrid waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(stored[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for stored, row in zip(stored_rows, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("hybrid waveform CSV differs from raw Spectre archives")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a private PDK-active ideal-passive three-stage probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_pdk_hybrid_three_stage(args.run_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_pdk_hybrid_three_stage(args.run_dir)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
