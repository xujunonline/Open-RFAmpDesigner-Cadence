from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.ocean_ascii import read_ocean_cascode_op
from orfadc.experiments.extract_ocean_oa import extract_ocean_oa


_PUBLIC_MODEL = Path(__file__).resolve().parents[3] / "circuit/spectre/teaching_mos1_model.scs"
_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_REQUIRED = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "ade_companion": "ade_e.scs", "ocn_report": "ocnprint/report.txt",
    "spectre_log": "spectre.out", "ocean_log": "ocean.log",
    "public_model": "teaching_mos1_model.scs", "oa_schematic": "oa_view/sch.oa",
    "schematic_check": "schematic_check.txt", "ocean_run_report": "ocean_run_report.txt",
    "ocean_export_report": "ocean_export_report.txt", "export_script": "export_ocean.ocn",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp",
    "noise_raw": "sp.noise.sp",
    **{f"ocn_{signal}_{part}": f"ocnprint/{signal}_{part}.txt"
       for signal in ("s11", "s21", "s12", "s22") for part in ("real", "imag")},
    **{f"ocn_{signal.lower()}": f"ocnprint/{signal}.txt"
       for signal in ("NF", "NFmin", "F", "Fmin")},
}


def _close(actual: object, expected: float, name: str) -> None:
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-8, abs_tol=1e-10
    ):
        raise ValueError(f"teaching OA {name} disagrees with raw OCEAN data")


def _check_inductive_topology(
    netlist: str, *, damped: bool = False, cascode: bool = False, vcas_v: float = 0.95,
) -> None:
    mos = re.findall(r"^M1 \((\S+) (\S+) (\S+) 0\) n_teach w=300u l=100n$", netlist, re.MULTILINE)
    if len(mos) != 1:
        raise ValueError("inductive OA M1 geometry or body connection differs")
    m1_drain, gate, source = mos[0]
    drain = m1_drain
    casgate = None
    if cascode:
        upper = re.findall(r"^M2 \((\S+) (\S+) (\S+) 0\) n_teach w=300u l=100n$", netlist, re.MULTILINE)
        if len(upper) != 1 or upper[0][2] != m1_drain:
            raise ValueError("cascode OA M2 geometry, body, or M1 drain connection differs")
        drain, casgate, _ = upper[0]
    cin = re.findall(rf"^CIN \((\S+) (\S+)\) capacitor c=5p$", netlist, re.MULTILINE)
    if len(cin) != 1:
        raise ValueError("inductive OA input capacitor is missing")
    input_node, rf_input = cin[0]
    rbias = re.findall(rf"^RBIAS \({re.escape(gate)} (\S+)\) resistor r=100k$", netlist, re.MULTILINE)
    if len(rbias) != 1:
        raise ValueError("inductive OA gate bias connection differs")
    bias = rbias[0]
    vdd_match = re.findall(r"^VDD \((\S+) 0\) vsource dc=1\.2 type=dc$", netlist, re.MULTILINE)
    output_match = re.findall(r"^PORT2 \((\S+) 0\) port r=50 num=2 type=sine$", netlist, re.MULTILINE)
    if len(vdd_match) != 1 or len(output_match) != 1:
        raise ValueError("inductive OA supply or output port differs")
    vdd, output = vdd_match[0], output_match[0]
    nodes = (drain, gate, source, input_node, rf_input, bias, vdd, output)
    if cascode:
        nodes = (*nodes, m1_drain, casgate)
    if len(set(nodes)) != len(nodes) or "0" in nodes:
        raise ValueError("inductive OA internal nodes must remain distinct")
    expected = (
        f"PORT1 ({input_node} 0) port r=50 num=1 type=sine",
        f"VBIAS ({bias} 0) vsource dc=0.65 type=dc",
        f"LG ({rf_input} {gate}) inductor l=1n",
        f"LS ({source} 0) inductor l=240p",
    )
    if any(netlist.count(line) != 1 for line in expected):
        raise ValueError("inductive OA connection or device value differs")
    if cascode:
        bias_match = re.findall(
            rf"^VCAS \({re.escape(casgate)} 0\) vsource dc=([0-9.eE+-]+) type=dc$",
            netlist, re.MULTILINE,
        )
        if len(bias_match) != 1 or not math.isclose(float(bias_match[0]), vcas_v, rel_tol=0, abs_tol=1e-12):
            raise ValueError("inductive OA cascode bias connection or value differs")
    if damped:
        values = (
            (rf"^LD \({re.escape(vdd)} {re.escape(drain)}\) inductor l=([0-9.eE+-]+)n$", 1.68809309279457),
            (rf"^COUT \({re.escape(drain)} {re.escape(output)}\) capacitor c=([0-9.eE+-]+)f$", 225.079079039277),
            (rf"^RDAMP \({re.escape(vdd)} {re.escape(drain)}\) resistor r=([0-9.eE+-]+)$", 150.0),
        )
        for pattern, target in values:
            matches = re.findall(pattern, netlist, re.MULTILINE)
            if len(matches) != 1 or not math.isclose(float(matches[0]), target, rel_tol=1e-10):
                raise ValueError("damped OA connection or device value differs")
    elif any(netlist.count(line) != 1 for line in (
        f"LD ({vdd} {drain}) inductor l=2n",
        f"COUT ({drain} {output}) capacitor c=5p",
    )):
        raise ValueError("inductive OA connection or device value differs")
    devices = set(re.findall(r"^([A-Z][A-Z0-9_]*) \(", netlist, re.MULTILINE))
    expected_devices = {"M1", "PORT1", "PORT2", "VDD", "VBIAS", "RBIAS", "CIN", "COUT", "LG", "LS", "LD"}
    if devices != expected_devices | ({"RDAMP"} if damped else set()) | ({"M2", "VCAS"} if cascode else set()):
        raise ValueError("inductive OA has missing or additional devices")


def audit_teaching_oa(run_dir: Path) -> dict:
    """Read-only check of the OA MOS1 schematic, OCEAN and Spectre archive."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("teaching OA run directory must be an ordinary directory")
    saved = read_evidenced_metrics(run_dir)
    topology = saved.get("teaching_topology", "flat")
    precision = saved.get("ocn_precision_digits", 6)
    vcas_v = saved.get("teaching_vcas_v", 0.95)
    if topology not in {"flat", "inductive", "damped", "cascode"}:
        raise ValueError("unknown teaching OA topology")
    if type(precision) is not int or precision not in {6, 15}:
        raise ValueError("unknown OCEAN export precision")
    if (type(vcas_v) not in {int, float} or not math.isfinite(vcas_v)
            or not 0.8 <= vcas_v <= 1.1 or (topology != "cascode" and vcas_v != 0.95)):
        raise ValueError("invalid teaching OA cascode bias")
    if (
        saved.get("run_id") != run_dir.name
        or saved.get("status") != "ok_with_warnings"
        or saved.get("simulation_status") != "ok"
        or saved.get("source") != "cadence_spectre"
        or saved.get("source_run_kind") != {
            "flat": "teaching_mos1_oa_ocean_classic_batch",
            "inductive": "teaching_mos1_inductive_oa_ocean_classic_batch",
            "damped": "teaching_mos1_damped_oa_ocean_classic_batch",
            "cascode": "teaching_mos1_cascode_oa_ocean_classic_batch",
        }[topology]
        or saved.get("model_kind") != "teaching_model"
        or saved.get("circuit_class") != {
            "flat": "teaching_mos1_common_source",
            "inductive": "teaching_mos1_inductive_common_source",
            "damped": "teaching_mos1_damped_common_source",
            "cascode": "teaching_mos1_cascode",
        }[topology]
        or saved.get("not_lna_result") is not True
        or saved.get("spec_pass") is not None
        or saved.get("analysis") != ["dc", "sp", "noise"]
        or saved.get("frequency_band_ghz") != {"low": 8.0, "high": 12.0}
    ):
        raise ValueError("archive is not a completed public teaching OA diagnostic")
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict) or any(
        not isinstance(entries.get(key), dict) or entries[key].get("path") != name
        for key, name in _REQUIRED.items()
    ):
        raise ValueError("teaching OA evidence lacks required artifacts")
    export_script = (run_dir / "export_ocean.ocn").read_text(encoding="utf-8")
    op_exported = saved.get("oa_device_op_exported", False)
    expects_op = topology == "cascode" and "device_op.txt" in export_script
    if type(op_exported) is not bool or op_exported != expects_op:
        raise ValueError("cascode OCEAN operating-point export contract differs")
    if op_exported and (
        not isinstance(entries.get("device_op"), dict)
        or entries["device_op"].get("path") != "ocnprint/device_op.txt"
    ):
        raise ValueError("cascode OCEAN operating-point evidence is missing")
    if (run_dir / "teaching_mos1_model.scs").read_bytes() != _PUBLIC_MODEL.read_bytes():
        raise ValueError("archived MOS1 model differs from the public teaching model")
    check = (run_dir / "schematic_check.txt").read_text(encoding="utf-8")
    if "check_return=(0 0)" not in check or "save_return=t" not in check:
        raise ValueError("schematic Check and Save evidence is missing")
    netlist = (run_dir / "netlist.scs").read_text(encoding="ascii")
    includes = re.findall(r'^include "([^"]+)"$', netlist, re.MULTILINE)
    if len(includes) != 2 or "ade_e.scs" not in includes or not any(
        path.endswith("/teaching_mos1_model.scs") for path in includes
    ):
        raise ValueError("OA netlist does not reference the expected teaching model")
    expected_lines = (
        "M1 (net4 net2 0 0) n_teach w=300u l=100n",
        "PORT1 (net1 0) port r=50 num=1 type=sine",
        "PORT2 (net5 0) port r=50 num=2 type=sine",
        "VBIAS (net3 0) vsource dc=0.55 type=dc",
        "VDD (net6 0) vsource dc=1.2 type=dc",
        "RBIAS (net2 net3) resistor r=1Meg",
        "RD (net6 net4) resistor r=100",
        "CIN (net1 net2) capacitor c=10p",
        "COUT (net4 net5) capacitor c=10p",
    )
    if topology == "flat":
        if any(netlist.count(line) != 1 for line in expected_lines):
            raise ValueError("OA netlist topology or device parameters differ from checked schematic")
    else:
        _check_inductive_topology(netlist, damped=topology in {"damped", "cascode"},
                                  cascode=topology == "cascode", vcas_v=vcas_v)
    spectre_log = (run_dir / "spectre.out").read_text(encoding="utf-8")
    if not re.search(r"spectre completes with 0 errors,\s*0 warnings", spectre_log):
        raise ValueError("teaching OA Spectre log has errors or warnings")
    model_include = next(path for path in includes if path.endswith("/teaching_mos1_model.scs"))
    if f"Reading file:  {model_include}" not in spectre_log:
        raise ValueError("Spectre did not report loading the declared teaching model")
    report = (run_dir / "ocean_run_report.txt").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r'run_result="([^"]+)"', report)
    header = next(line.strip() for line in (run_dir / "ocnprint/s11_real.txt").read_text(encoding="utf-8").splitlines() if line.strip())
    if match is None or f'?resultsDir "{match[1]}/psf"' not in header:
        raise ValueError("exported traces are not bound to this OCEAN run directory")
    if op_exported:
        op = read_ocean_cascode_op(run_dir / "ocnprint/device_op.txt", expected_psf=f"{match[1]}/psf")
        for instance in ("M1", "M2"):
            device = op[instance]
            if (any(device[field] <= 0 for field in ("id", "vgs", "vds", "vdsat", "gm", "gds", "cgs"))
                    or device["cgd"] < 0 or device["vds"] <= device["vdsat"]):
                raise ValueError("cascode OCEAN operating point is physically inconsistent")
        if (
            not math.isclose(op["M1"]["vgs"], 0.65, rel_tol=0, abs_tol=1e-8)
            or not math.isclose(op["M1"]["vds"] + op["M2"]["vgs"], vcas_v, rel_tol=0, abs_tol=1e-8)
            or not math.isclose(op["M1"]["vds"] + op["M2"]["vds"], 1.2, rel_tol=0, abs_tol=1e-8)
        ):
            raise ValueError("cascode OCEAN operating-point bias differs from netlist")
    rows, recomputed = extract_ocean_oa(
        run_dir / "ocnprint", ocean_log=run_dir / "ocean.log",
        spectre_log=run_dir / "spectre.out", run_id=run_dir.name,
        supply_voltage_v=1.2, low_ghz=8.0, high_ghz=12.0, teaching_model=True,
        teaching_topology=topology,
        ocn_precision_digits=precision,
    )
    if topology in {"damped", "cascode"} and (
        len(rows) != 161
        or not math.isclose(rows[0]["freq_ghz"], 8.0, rel_tol=0, abs_tol=1e-8)
        or not math.isclose(rows[-1]["freq_ghz"], 12.0, rel_tol=0, abs_tol=1e-8)
    ):
        raise ValueError("damped OA sweep does not cover both 8-12 GHz band edges")
    if (saved.get("points") != len(rows) or saved.get("stability") != recomputed["stability"]
            or ("stability_quality" in saved and saved["stability_quality"] != recomputed["stability_quality"])):
        raise ValueError("teaching OA point count or stability disagrees with raw traces")
    for key, expected in recomputed["metrics"].items():
        _close(saved.get("metrics", {}).get(key), expected, key)
    if op_exported and not math.isclose(
        op["M1"]["id"] * 1e3, recomputed["metrics"]["supply_current_ma"],
        rel_tol=1e-6, abs_tol=1e-8,
    ):
        raise ValueError("cascode OCEAN operating-point current disagrees with VDD")
    csv_path = run_dir / "waveforms.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked teaching OA waveform CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("teaching OA waveform columns differ")
        csv_rows = list(reader)
    if len(csv_rows) != len(rows):
        raise ValueError("teaching OA waveform row count differs")
    for index, (saved_row, raw_row) in enumerate(zip(csv_rows, rows, strict=True)):
        for key in _COLUMNS:
            try:
                value = float(saved_row[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"teaching OA CSV {key} is invalid") from exc
            _close(value, raw_row[key], f"CSV row {index} {key}")
    result = {"status": "verified", "run_id": run_dir.name, "points_verified": len(rows),
              "metrics": recomputed["metrics"], "not_lna_result": True,
              "stability_quality": recomputed["stability_quality"]}
    if op_exported:
        result["device_op"] = op
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of a public MOS1 OA/OCEAN run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = audit_teaching_oa(args.run_dir)
    print(f"status={result['status']} points={result['points_verified']} "
          f"stability_quality={result['stability_quality']} run_id={result['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
