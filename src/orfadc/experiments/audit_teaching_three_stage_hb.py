from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.hb_metrics import (
    extract_hb_differential_fundamental_power, extract_hb_input_available_power,
    extract_sp_s21_at_frequency,
)
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii, require_same_frequency_grid, summarize_noise
from orfadc.cadence.psfascii_reader import (
    magnitude_db, parse_complex_trace, parse_dc_values, parse_struct_values,
)
from orfadc.cadence.stability_metrics import summarize_sampled_stability
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage_hb
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv",
    "netlist": "netlist.scs", "remote_netlist": "remote_netlist.scs",
    "public_model": "teaching_mos1_model.scs", "remote_model": "remote_teaching_mos1_model.scs",
    "spectre_log": "spectre.log", "stdout": "stdout.log", "stderr": "stderr.log",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info",
    "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
    "hb_fd_raw": "hb.fd.pss_hb", "hb_fi_raw": "hb.fi.pss_hb",
    "hb_td_raw": "hb.td.pss_hb", "touchstone": "teaching_three_stage_probe.s2p",
}


def _parameters(netlist: str) -> tuple[float, float, float, int]:
    input_match = re.search(
        r"^PORT1 \(in 0\) port r=50 num=1 type=sine dbm=([-+0-9.eE]+) freq=([-+0-9.eE]+)$",
        netlist, re.MULTILINE,
    )
    secondary_match = re.search(
        r"^L3S \(outp outn\) inductor l=([-+0-9.eE]+)n$", netlist, re.MULTILINE,
    )
    hb_match = re.search(
        r"^hb hb fundfreqs=\[([-+0-9.eE]+)\] maxharms=\[([0-9]+)\] annotate=status$",
        netlist, re.MULTILINE,
    )
    if not input_match or not secondary_match or not hb_match:
        raise ValueError("three-stage HB parameters are incomplete")
    power = float(input_match[1])
    frequency_ghz = float(input_match[2]) / 1e9
    secondary = float(secondary_match[1])
    harmonics = int(hb_match[2])
    if (not -100 <= power <= 0
            or not math.isclose(float(hb_match[1]), frequency_ghz * 1e9, rel_tol=1e-12)
            or "PORT2 (outp outn) port r=1787 num=2 type=dc" not in netlist):
        raise ValueError("three-stage HB is not a bounded mixed-reference probe")
    return power, secondary, frequency_ghz, harmonics


def extract_teaching_three_stage_hb(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("three-stage HB archive must be an ordinary directory")
    netlist_bytes = (run_dir / "netlist.scs").read_bytes()
    power, secondary, frequency_ghz, harmonics = _parameters(netlist_bytes.decode("ascii"))
    expected = render_teaching_three_stage_hb(
        power, output_secondary_nh=secondary, frequency_ghz=frequency_ghz,
        harmonics=harmonics,
    )
    if (netlist_bytes != expected or (run_dir / "remote_netlist.scs").read_bytes() != expected
            or (run_dir / "teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()
            or (run_dir / "remote_teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()):
        raise ValueError("three-stage HB inputs differ from public or remotely executed sources")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if (not re.search(r"spectre completes with 0 errors,\s*0 warnings", log)
            or not re.search(r"^Reading file:\s+\S+/netlist\.scs$", log, re.MULTILINE)
            or "SPECTRE-25" in log):
        raise ValueError("three-stage HB Spectre log is not clean")
    hb_raw = (run_dir / "hb.fd.pss_hb").read_text(encoding="utf-8", errors="replace")
    if not re.search(rf'^"harms"\s+{harmonics}$', hb_raw.split("TYPE", 1)[0], re.MULTILINE):
        raise ValueError("three-stage HB harmonic order differs")
    hb = extract_hb_differential_fundamental_power(
        run_dir / "hb.fd.pss_hb", fundamental_hz=frequency_ghz * 1e9,
    )
    actual_input_dbm = extract_hb_input_available_power(
        run_dir / "hb.fd.pss_hb", fundamental_hz=frequency_ghz * 1e9,
    )
    if not math.isclose(actual_input_dbm, power, rel_tol=0, abs_tol=0.01):
        raise ValueError("three-stage HB input power differs from its netlist source")
    sp_s21_db = extract_sp_s21_at_frequency(run_dir / "sp.sp", frequency_ghz * 1e9)
    power_gain_db = hb["output_power_dbm"] - power
    delta = power_gain_db - sp_s21_db
    if power <= -50 and abs(delta) > 0.01:
        raise ValueError("three-stage low-drive HB power gain disagrees with SP S21")
    touchstone = parse_touchstone_2port(run_dir / "teaching_three_stage_probe.s2p")
    if len(touchstone) != 161 or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        for row in touchstone
    ):
        raise ValueError("three-stage HB Touchstone port references differ")
    frequency = None
    sparams = {}
    maximum_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", signal)
        if frequency is None:
            frequency = grid
        elif grid != frequency:
            raise ValueError("three-stage HB SP grids differ")
        sparams[signal] = values
        for sample, value, row in zip(grid, values, touchstone, strict=True):
            if not math.isclose(sample, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("three-stage HB Touchstone frequency differs")
            maximum_touchstone_delta = max(
                maximum_touchstone_delta,
                abs(value - complex(row[f"{signal}_real"], row[f"{signal}_imag"])),
            )
    if (frequency is None or len(frequency) != 161 or frequency[0] != 8e9
            or frequency[-1] != 12e9 or maximum_touchstone_delta > 1e-8):
        raise ValueError("three-stage HB small-signal traces are incomplete")
    noise = noise_rows_from_psfascii(run_dir / "sp.noise.sp", nf_signal="NF", nf_unit="db", nfmin_signal="NFmin")
    rows = [{
        "freq_hz": sample, "freq_ghz": sample / 1e9,
        **{f"{name}_db": magnitude_db([sparams[name][index]])[0]
           for name in ("s11", "s21", "s22")},
        "nf_db": float(noise[index]["nf_db"]), "nfmin_db": float(noise[index]["nfmin_db"]),
    } for index, sample in enumerate(frequency)]
    require_same_frequency_grid(noise, rows)
    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    if not math.isfinite(current_ma) or current_ma <= 0:
        raise ValueError("three-stage HB supply current is invalid")
    devices = {}
    for index in range(1, 7):
        name = f"M{index}"
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance=name, struct_type="mos1")
        devices[name] = {key: op[key] for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds", "cgs", "cgd")}
        if (any(not math.isfinite(value) for value in devices[name].values())
                or op["vds"] <= op["vdsat"]):
            raise ValueError("three-stage HB MOS operating point is invalid")
    if not math.isclose(sum(devices[f"M{i}"]["ids"] for i in range(2, 7)), current_ma / 1e3, rel_tol=1e-4):
        raise ValueError("three-stage HB supply/device currents disagree")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.2 * current_ma,
        **hb, "input_available_power_dbm": power, "power_gain_db": power_gain_db,
        "small_signal_s21_db": sp_s21_db, "hb_minus_s21_db": delta,
    }
    payload = {
        "schema_version": 1,
        "status": "hb_low_drive_verified" if power <= -50 else "hb_drive_probe_verified",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "source_run_kind": ("teaching_mos1_three_stage_hb_low_drive" if power <= -50
                            else "teaching_mos1_three_stage_hb_drive_probe"),
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": ("public MOS1 low-drive differential HB; no compression-point claim"
                  if power <= -50 else "public MOS1 differential HB drive probe; no qualified LNA claim"),
        "analysis": ["dc", "op_info", "sp", "noise", "hb"], "points": 161,
        "parameters": {"input_dbm": power, "output_secondary_nh": secondary,
                       "frequency_ghz": frequency_ghz, "harmonics": harmonics},
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "metrics": metrics, "device_op": devices,
        "stability": summarize_sampled_stability(*(sparams[name] for name in ("s11", "s21", "s12", "s22"))),
        "maximum_touchstone_psfascii_complex_delta": maximum_touchstone_delta,
    }
    validate_metrics_payload(payload)
    return rows, payload


def audit_teaching_three_stage_hb(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts", {})
    if any(not isinstance(entries.get(key), dict) or entries[key].get("path") != relative
           for key, relative in _ARTIFACTS.items()):
        raise ValueError("three-stage HB evidence lacks required artifacts")
    rows, rebuilt = extract_teaching_three_stage_hb(run_dir)
    if saved != rebuilt:
        raise ValueError("three-stage HB metrics differ from raw Spectre output")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("three-stage HB waveform columns differ")
        stored = list(reader)
    if len(stored) != len(rows) or any(
        not math.isclose(float(item[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for item, row in zip(stored, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("three-stage HB waveform CSV differs from raw Spectre output")
    return {"status": "verified", "run_id": run_dir.name, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a public MOS1 three-stage low-drive HB probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_teaching_three_stage_hb(args.run_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_teaching_three_stage_hb(args.run_dir)
    print(f"status={result['status']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
