from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.extract_rf_metrics import summarize_sparams
from orfadc.cadence.noise_metrics import noise_rows_from_psfascii, require_same_frequency_grid, summarize_noise
from orfadc.cadence.psfascii_reader import (
    magnitude_db, parse_complex_trace, parse_dc_values, parse_scalar_trace,
    parse_struct_values, parse_trace_kinds,
)
from orfadc.cadence.stability_metrics import rollett_k_and_delta, summarize_sampled_stability
from orfadc.cadence.touchstone import parse_touchstone_2port
from orfadc.cadence.teaching_three_stage_netlist import PUBLIC_MODEL, render_teaching_three_stage
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.metric_contract import validate_metrics_payload
from orfadc.schemas import Candidate, Spec


_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
_ARTIFACTS = {
    "metrics": "metrics.json", "waveforms": "waveforms.csv", "netlist": "netlist.scs",
    "remote_netlist": "remote_teaching_three_stage_probe.scs",
    "public_model": "teaching_mos1_model.scs",
    "remote_model": "remote_teaching_mos1_model.scs",
    "spectre_log": "spectre.log", "stdout": "spectre.stdout.log", "stderr": "spectre.stderr.log",
    "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp",
    "noise_raw": "sp.noise.sp", "touchstone": "teaching_three_stage_probe.s2p",
    "probe_status": "probe_status.json",
}


def extract_teaching_three_stage(run_dir: Path) -> tuple[list[dict[str, float]], dict]:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("three-stage probe directory must be an ordinary directory")
    probe = json.loads((run_dir / "probe_status.json").read_text(encoding="utf-8"))
    output_tune_ff = probe.get("output_tune_ff", 0.0)
    output_secondary_nh = probe.get("output_secondary_nh", 1.0)
    broadband = probe.get("broadband", False)
    candidate_context = probe.get("candidate")
    if (candidate_context is None) != (probe.get("spec") is None):
        raise ValueError("three-stage candidate and spec context must be paired")
    if candidate_context is not None:
        try:
            candidate = Candidate(**candidate_context)
            spec = Spec(**probe["spec"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("three-stage candidate context is malformed") from exc
        if (
            candidate.to_dict() != candidate_context or asdict(spec) != probe["spec"]
            or candidate.spec_id != spec.id or candidate.seed != probe.get("seed")
            or candidate.status != "teaching_three_stage_diagnostic"
            or candidate.notes or candidate.active_params or candidate.power_ratio_list
            or candidate.passive_params != {
                "output_tune_ff": output_tune_ff,
                "output_secondary_nh": output_secondary_nh,
            }
            or candidate.sim_result is not None
            or spec.id != "S1" or spec.band_edges_ghz[0] < 8 or spec.band_edges_ghz[1] > 12
            or probe.get("timeout_seconds") != 180
        ):
            raise ValueError("three-stage candidate differs from the bounded S1 probe")
    expected_netlist = render_teaching_three_stage(
        output_tune_ff=output_tune_ff, output_secondary_nh=output_secondary_nh,
        broadband=broadband,
    )
    if ((run_dir / "netlist.scs").read_bytes() != expected_netlist
            or (run_dir / "remote_teaching_three_stage_probe.scs").read_bytes() != expected_netlist
            or (run_dir / "teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()
            or (run_dir / "remote_teaching_mos1_model.scs").read_bytes() != PUBLIC_MODEL.read_bytes()):
        raise ValueError("three-stage public or remotely executed input differs")
    netlist = (run_dir / "netlist.scs").read_text(encoding="ascii")
    if (
        len(re.findall(r"^M[1-6] \(", netlist, re.MULTILINE)) != 6
        or len(re.findall(r"^K(?:12|23|3) mutual_inductor\b", netlist, re.MULTILINE)) != 3
        or len(re.findall(r"^CN[23][PN] \(", netlist, re.MULTILINE)) != 4
        or "PORT1 (in 0) port r=50 num=1 type=sine" not in netlist
        or "PORT2 (outp outn) port r=1787 num=2 type=sine" not in netlist
        or "CL (outp outn) capacitor c=62f" not in netlist
    ):
        raise ValueError("three-stage topology or mixed-reference load differs")
    recovered = probe.get("dispatch_protocol_version") == 4
    if (((probe.get("spectre_returncode") is not None or
          probe.get("raw_completion_verified") is not True) if recovered else
         probe.get("spectre_returncode") != 0)
            or probe.get("spectre_log_downloaded") is not True
            or type(probe.get("host_available_gib_before")) not in {int, float}
            or probe["host_available_gib_before"] < 2.66):
        raise ValueError("three-stage remote run or resource gate was not verified")
    log = (run_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*0 warnings", log):
        raise ValueError("three-stage Spectre log is not clean")
    if not re.search(r"^Reading file:\s+\S+/teaching_three_stage_probe\.scs$", log, re.MULTILINE):
        raise ValueError("three-stage Spectre did not read the checked netlist")

    touchstone = parse_touchstone_2port(run_dir / "teaching_three_stage_probe.s2p")
    expected_points = 401 if broadband else 161
    expected_low, expected_high = (0.1e9, 20.1e9) if broadband else (8e9, 12e9)
    if (len(touchstone) != expected_points or any(
        row.get("reference_input_ohm") != 50 or row.get("reference_output_ohm") != 1787
        or "reference_ohm" in row for row in touchstone
    )):
        raise ValueError("three-stage Touchstone port references differ")
    frequency = None
    sparams = {}
    maximum_touchstone_delta = 0.0
    for signal in ("s11", "s21", "s12", "s22"):
        grid, values = parse_complex_trace(run_dir / "sp.sp", signal)
        if frequency is None:
            frequency = grid
        elif grid != frequency:
            raise ValueError("three-stage S-parameter frequency grids differ")
        sparams[signal] = values
        for sample_frequency, value, row in zip(grid, values, touchstone, strict=True):
            if not math.isclose(sample_frequency, row["freq_hz"], rel_tol=1e-10, abs_tol=1e-3):
                raise ValueError("three-stage Touchstone and PSFASCII grids differ")
            maximum_touchstone_delta = max(
                maximum_touchstone_delta,
                abs(value - complex(row[f"{signal}_real"], row[f"{signal}_imag"])),
            )
    if (frequency is None or len(frequency) != expected_points
            or maximum_touchstone_delta > 1e-8
            or not math.isclose(frequency[0], expected_low, rel_tol=1e-12)
            or not math.isclose(frequency[-1], expected_high, rel_tol=1e-12)):
        raise ValueError("three-stage S-parameter trace is incomplete or inconsistent")
    noise_path = run_dir / "sp.noise.sp"
    kinds = parse_trace_kinds(noise_path)
    if any(kinds.get(name) != kind for name, kind in (
        ("NF", "dB"), ("NFmin", "dB"), ("F", "Noise factor"), ("Fmin", "Noise factor"),
    )):
        raise ValueError("three-stage noise units are missing or inconsistent")
    noise = noise_rows_from_psfascii(noise_path, nf_signal="NF", nf_unit="db", nfmin_signal="NFmin")
    rows = []
    for index, sample_frequency in enumerate(frequency):
        rows.append({
            "freq_hz": sample_frequency, "freq_ghz": sample_frequency / 1e9,
            **{f"{signal}_db": magnitude_db([sparams[signal][index]])[0]
               for signal in ("s11", "s21", "s22")},
            "nf_db": float(noise[index]["nf_db"]), "nfmin_db": float(noise[index]["nfmin_db"]),
        })
    require_same_frequency_grid(noise, rows)
    for factor, db in (("F", "nf_db"), ("Fmin", "nfmin_db")):
        grid, values = parse_scalar_trace(noise_path, factor)
        if grid != frequency or any(
            value <= 0 or not math.isclose(10 * math.log10(value), row[db], abs_tol=1e-6)
            for value, row in zip(values, rows, strict=True)
        ):
            raise ValueError("three-stage noise factor disagrees with noise figure")
    dc = parse_dc_values(run_dir / "dcOp.dc")
    current_ma = -dc["VDD_SRC:p"] * 1e3
    if not math.isfinite(current_ma) or current_ma <= 0:
        raise ValueError("three-stage VDD current is invalid")
    devices = {}
    for index in range(1, 7):
        instance = f"M{index}"
        op = parse_struct_values(run_dir / "dcOpInfo.info", instance=instance, struct_type="mos1")
        devices[instance] = {key: op[key] for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds", "cgs", "cgd")}
        if any(not math.isfinite(value) for value in devices[instance].values()) or any(
            devices[instance][key] <= 0 for key in ("ids", "vgs", "vds", "vdsat", "gm", "gds", "cgs")
        ) or devices[instance]["cgd"] < 0 or devices[instance]["vds"] <= devices[instance]["vdsat"]:
            raise ValueError("three-stage MOS1 operating point is invalid")
    if (
        not math.isclose(devices["M1"]["ids"], devices["M2"]["ids"], rel_tol=1e-3)
        or not math.isclose(sum(devices[f"M{i}"]["ids"] for i in range(2, 7)), current_ma / 1e3, rel_tol=1e-4)
    ):
        raise ValueError("three-stage MOS1 currents disagree with supply KCL")
    metrics = {
        **summarize_sparams(rows, 8.0, 12.0), **summarize_noise(noise, 8.0, 12.0),
        "supply_current_ma": current_ma, "supply_power_mw": 1.2 * current_ma,
    }
    stability = summarize_sampled_stability(*(sparams[name] for name in ("s11", "s21", "s12", "s22")))
    payload = {
        "schema_version": 1, "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "teaching_mos1_three_stage_direct_spectre",
        "circuit_class": "teaching_mos1_three_stage_probe", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None, "run_id": run_dir.name,
        "scope": "direct Spectre three-stage topology probe with ideal coupling; not a qualified LNA or paper result",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
        "load_capacitance_ff": 62.0, "frequency_band_ghz": {"low": 8.0, "high": 12.0},
        "metrics": metrics, "points": len(rows), "stability": stability,
        "device_op": devices, "maximum_touchstone_psfascii_complex_delta": maximum_touchstone_delta,
        "host_available_gib_before": probe["host_available_gib_before"],
    }
    if broadband:
        samples = [
            (sample / 1e9, *rollett_k_and_delta(*(sparams[name][index] for name in ("s11", "s21", "s12", "s22"))))
            for index, sample in enumerate(frequency)
        ]
        failed = [sample for sample, k, delta in samples if k is None or k <= 1 or delta >= 1]
        inside = [index for index, sample in enumerate(frequency) if 8e9 <= sample <= 12e9]
        outside = [index for index, sample in enumerate(frequency) if sample < 8e9 or sample > 12e9]
        def selected_stability(indices: list[int]) -> dict:
            return summarize_sampled_stability(*(
                [sparams[name][index] for index in indices]
                for name in ("s11", "s21", "s12", "s22")
            ))
        payload["source_run_kind"] = "teaching_mos1_three_stage_broadband_stability_probe"
        payload["scope"] = "public MOS1 0.1-20.1 GHz sampled stability probe; not a qualified LNA"
        payload["frequency_grid_ghz"] = {"low": 0.1, "high": 20.1, "points": expected_points}
        payload["stability_in_band"] = selected_stability(inside)
        payload["stability_out_of_band"] = selected_stability(outside)
        payload["stability_failed_sample_count"] = len(failed)
        payload["first_stability_failure_ghz"] = failed[0] if failed else None
        payload["last_stability_failure_ghz"] = failed[-1] if failed else None
    if output_tune_ff or output_secondary_nh != 1:
        payload["design_parameters"] = {
            **({"output_tune_ff": output_tune_ff} if output_tune_ff else {}),
            **({"output_secondary_nh": output_secondary_nh} if output_secondary_nh != 1 else {}),
        }
    if candidate_context is not None:
        payload.update({
            "candidate": candidate_context, "spec": probe["spec"],
            "seed": candidate.seed, "timeout_seconds": 180,
        })
    validate_metrics_payload(payload)
    return rows, payload


def audit_teaching_three_stage(run_dir: Path) -> dict:
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts", {})
    probe = json.loads((run_dir / "probe_status.json").read_text(encoding="utf-8"))
    protocol = probe.get("dispatch_protocol_version")
    if protocol not in {None, 2, 3, 4} or (protocol is not None and probe.get("candidate") is None):
        raise ValueError("three-stage dispatch protocol version is invalid")
    expected_artifacts = {
        **({key: value for key, value in _ARTIFACTS.items() if key not in {"stdout", "stderr"}}
           if protocol == 4 else _ARTIFACTS),
        **({"candidate": "candidate.json"} if probe.get("candidate") is not None else {}),
        **({"dispatch_plan": "dispatch_plan.json", "remote_identity": "agent_remote.json"}
           if protocol in {2, 3, 4} else {}),
        **({"recovery_provenance": "recovery_provenance.json"} if protocol == 4 else {}),
    }
    if set(entries) != set(expected_artifacts) or any(
        not isinstance(entries.get(key), dict) or entries[key].get("path") != name
        for key, name in expected_artifacts.items()
    ):
        raise ValueError("three-stage probe evidence lacks required artifacts")
    rows, rebuilt = extract_teaching_three_stage(run_dir)
    if protocol in {2, 3, 4}:
        plan = json.loads((run_dir / "dispatch_plan.json").read_text(encoding="utf-8"))
        identity = read_remote_identity_snapshot(run_dir, plan["remote_identity_sha256"])
        candidate = Candidate(**probe["candidate"])
        remote_name = f"teach3_{probe['spec']['id']}_seed{candidate.seed}_{candidate.candidate_id}_{run_dir.name}"
        expected_plan = {
            "schema_version": 1, "run_id": run_dir.name,
            "remote_dir": str(PurePosixPath(identity["remote_root"]) / remote_name),
            "remote_identity_sha256": plan["remote_identity_sha256"],
            "netlist_sha256": hashlib.sha256((run_dir / "netlist.scs").read_bytes()).hexdigest(),
            "model_sha256": hashlib.sha256((run_dir / "teaching_mos1_model.scs").read_bytes()).hexdigest(),
            "candidate": probe["candidate"], "spec": probe["spec"],
            "spectre_timeout_seconds": 180, "spectre_dispatched_by_recovery": False,
        }
        if protocol in {3, 4}:
            expected_plan["host_available_gib_before"] = probe["host_available_gib_before"]
        if plan != expected_plan or json.loads((run_dir / "candidate.json").read_text(
            encoding="utf-8"
        )) != probe["candidate"]:
            raise ValueError("three-stage planned remote dispatch differs from the raw candidate")
        if protocol == 4:
            provenance = json.loads((run_dir / "recovery_provenance.json").read_text(encoding="utf-8"))
            remote_files = {
                "teaching_three_stage_probe.scs": "remote_teaching_three_stage_probe.scs",
                "teaching_mos1_model.scs": "remote_teaching_mos1_model.scs",
                "spectre.log": "spectre.log", "psf/dcOp.dc": "dcOp.dc",
                "psf/dcOpInfo.info": "dcOpInfo.info", "psf/sp.sp": "sp.sp",
                "psf/sp.noise.sp": "sp.noise.sp",
                "teaching_three_stage_probe.s2p": "teaching_three_stage_probe.s2p",
            }
            if (
                not isinstance(provenance, dict)
                or provenance.get("schema_version") != 1
                or provenance.get("mode") != "remote_quiescent_raw"
                or provenance.get("run_id") != run_dir.name
                or provenance.get("remote_identity_sha256") != plan["remote_identity_sha256"]
                or provenance.get("remote_dir_sha256") != hashlib.sha256(
                    plan["remote_dir"].encode("utf-8")
                ).hexdigest()
                or provenance.get("spectre_dispatched_by_recovery") is not False
                or provenance.get("controller_stdout_stderr_captured") is not False
                or probe.get("recovery_mode") != "remote_quiescent_raw"
                or not isinstance(provenance.get("remote_artifacts_sha256"), dict)
                or set(provenance["remote_artifacts_sha256"]) != set(remote_files)
                or any(
                    provenance["remote_artifacts_sha256"][remote] != hashlib.sha256(
                        (run_dir / local).read_bytes()
                    ).hexdigest()
                    for remote, local in remote_files.items()
                )
            ):
                raise ValueError("three-stage recovery provenance differs from the planned dispatch")
    elif (run_dir / "dispatch_plan.json").exists() or (run_dir / "agent_remote.json").exists():
        raise ValueError("legacy three-stage archive has unexpected dispatch files")
    if saved != rebuilt:
        raise ValueError("three-stage metrics differ from raw Spectre archives")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("three-stage waveform columns differ")
        stored_rows = list(reader)
    if len(stored_rows) != len(rows) or any(
        not math.isclose(float(saved_row[key]), row[key], rel_tol=1e-10, abs_tol=1e-12)
        for saved_row, row in zip(stored_rows, rows, strict=True) for key in _COLUMNS
    ):
        raise ValueError("three-stage waveform CSV differs from raw Spectre archives")
    return {"status": "verified", "run_id": run_dir.name, "points": len(rows), "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize or audit a public MOS1 three-stage Spectre probe")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        _require_private_path(args.run_dir)
        rows, payload = extract_teaching_three_stage(args.run_dir)
        write_active_oa_results(args.run_dir, rows, payload)
        write_evidence_manifest(args.run_dir, _ARTIFACTS)
    result = audit_teaching_three_stage(args.run_dir)
    print(f"status={result['status']} points={result['points']} output={args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
