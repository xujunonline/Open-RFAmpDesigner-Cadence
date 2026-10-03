from __future__ import annotations

import argparse
import csv
import math
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.metric_contract import validate_metrics_payload
from orfadc.tools.mcr_lumped import SymmetricParallelMCR, lumped_mcr_response, symmetric_parallel_mcr
from orfadc.tools.mcr_model import MCRParameters, paper_equation_3


MIN_HOST_AVAILABLE_GIB = 2.66
MAX_NORMALIZED_CALIBRATION_ERROR = 1e-6


def render_mcr_netlist(model: SymmetricParallelMCR, start_hz: float, stop_hz: float, points: int) -> str:
    if not isinstance(model, SymmetricParallelMCR):
        raise TypeError("model must be SymmetricParallelMCR")
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in (start_hz, stop_hz)):
        raise ValueError("frequency bounds must be finite")
    if start_hz <= 0 or stop_hz <= start_hz or type(points) is not int or not 2 <= points <= 401:
        raise ValueError("require increasing positive frequency bounds and 2..401 points")
    return (
        "simulator lang=spectre\n"
        "// Ideal passive diagnostic only; not the paper's physical MCR or an LNA.\n"
        "IEXC (0 n1) isource dc=0 mag=1\n"
        f"L1 (n1 0) inductor l={model.inductance_h:.17g}\n"
        f"L2 (n2 0) inductor l={model.inductance_h:.17g}\n"
        f"K12 mutual_inductor coupling={model.coupling_k:.17g} ind1=L1 ind2=L2\n"
        f"R1 (n1 0) resistor r={model.resistance_ohm:.17g}\n"
        f"R2 (n2 0) resistor r={model.resistance_ohm:.17g}\n"
        f"C1 (n1 0) capacitor c={model.capacitance_f:.17g}\n"
        f"C2 (n2 0) capacitor c={model.capacitance_f:.17g}\n"
        "simulatorOptions options save=allpub\n"
        f"ac ac start={start_hz:.17g} stop={stop_hz:.17g} lin={points - 1}\n"
    )


def compare_mcr_trace(
    model: SymmetricParallelMCR,
    n1: tuple[list[float], list[complex]],
    n2: tuple[list[float], list[complex]],
    *,
    start_hz: float,
    stop_hz: float,
    points: int,
) -> tuple[list[dict[str, float]], dict[str, float]]:
    frequencies, v1 = n1
    other_frequencies, v2 = n2
    if len(frequencies) != points or frequencies != other_frequencies or len(v1) != points or len(v2) != points:
        raise ValueError("MCR traces have incomplete or mismatched frequency axes")
    omega0 = 1 / math.sqrt(model.inductance_h * model.capacitance_f)
    q0 = omega0 * model.resistance_ohm * model.capacitance_f
    paper_params = MCRParameters(
        coupling_k=model.coupling_k,
        omega0_rad_s=omega0,
        q0=q0,
        source_resistance_ohm=model.resistance_ohm,
        output_resistance_ohm=model.resistance_ohm,
        source_capacitance_f=model.capacitance_f,
        gm_s=1.0,  # Z21 is independent of gm; this comparison excludes I11 and V(s).
    )
    rows: list[dict[str, float]] = []
    for index, (frequency, input_v, output_v) in enumerate(zip(frequencies, v1, v2, strict=True)):
        expected_frequency = start_hz + (stop_hz - start_hz) * index / (points - 1)
        if not math.isclose(frequency, expected_frequency, rel_tol=1e-9, abs_tol=1e-3):
            raise ValueError("Spectre frequency grid disagrees with requested linear sweep")
        if any(not math.isfinite(part) for value in (input_v, output_v) for part in (value.real, value.imag)):
            raise ValueError("nonfinite Spectre MCR trace")
        if input_v == 0:
            raise ValueError("zero input voltage makes admittance undefined")
        analytic = lumped_mcr_response(frequency, model)
        paper = paper_equation_3(frequency, paper_params)
        expected_v1 = 1 / analytic.input_admittance_s
        rows.append({
            "freq_hz": frequency,
            "v1_real_ohm": input_v.real,
            "v1_imag_ohm": input_v.imag,
            "v2_real_ohm": output_v.real,
            "v2_imag_ohm": output_v.imag,
            "yin_real_s": (1 / input_v).real,
            "yin_imag_s": (1 / input_v).imag,
            "analytic_yin_real_s": analytic.input_admittance_s.real,
            "analytic_yin_imag_s": analytic.input_admittance_s.imag,
            "analytic_z21_real_ohm": analytic.transfer_impedance_ohm.real,
            "analytic_z21_imag_ohm": analytic.transfer_impedance_ohm.imag,
            "paper_z21_real_ohm": paper.z21_ohm.real,
            "paper_z21_imag_ohm": paper.z21_ohm.imag,
            "v1_error_ohm": abs(input_v - expected_v1),
            "z21_error_ohm": abs(output_v - analytic.transfer_impedance_ohm),
            "paper_z21_error_ohm": abs(output_v - paper.z21_ohm),
        })
    scale_v1 = max(abs(1 / lumped_mcr_response(f, model).input_admittance_s) for f in frequencies)
    scale_z21 = max(abs(lumped_mcr_response(f, model).transfer_impedance_ohm) for f in frequencies)
    summary = {
        "max_v1_error_ohm": max(row["v1_error_ohm"] for row in rows),
        "max_z21_error_ohm": max(row["z21_error_ohm"] for row in rows),
        "max_paper_z21_error_ohm": max(row["paper_z21_error_ohm"] for row in rows),
        "max_v1_error_normalized": max(row["v1_error_ohm"] for row in rows) / scale_v1,
        "max_z21_error_normalized": max(row["z21_error_ohm"] for row in rows) / max(scale_z21, 1e-12),
        "max_paper_z21_error_normalized": max(row["paper_z21_error_ohm"] for row in rows) / max(scale_z21, 1e-12),
    }
    return rows, summary


def run_mcr_calibration(
    config_path: Path,
    output_dir: Path,
    *,
    f0_ghz: float = 30.0,
    q0: float = 3.0,
    capacitance_ff: float = 100.0,
    coupling_k: float = 0.4,
    start_ghz: float = 20.0,
    stop_ghz: float = 40.0,
    points: int = 41,
) -> dict:
    model = symmetric_parallel_mcr(2 * math.pi * f0_ghz * 1e9, q0, capacitance_ff * 1e-15, coupling_k)
    start_hz, stop_hz = start_ghz * 1e9, stop_ghz * 1e9
    netlist = render_mcr_netlist(model, start_hz, stop_hz, points)
    available = available_physical_memory_gb()
    if available < MIN_HOST_AVAILABLE_GIB:
        raise RuntimeError(f"host physical-memory gate failed: {available:.3f} GiB < {MIN_HOST_AVAILABLE_GIB:.2f} GiB")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_text(netlist, encoding="ascii")
    runner = RemoteRunner(load_remote_config(config_path))
    run_id = output_dir.name
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"mcr_cal_{uuid4().hex[:12]}")
    payload = {
        "schema_version": 1,
        "status": "unknown",
        "simulation_status": "unknown",
        "circuit_class": "ideal_passive_mcr",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": run_id,
        "scope": "project-chosen ideal symmetric parallel RLC coupling calibration",
        "analysis": ["ac"],
        "timeout_seconds": runner.config.command_timeout_seconds,
        "parameters": {"f0_ghz": f0_ghz, "q0": q0, "capacitance_ff": capacitance_ff, "coupling_k": coupling_k,
                       "start_ghz": start_ghz, "stop_ghz": stop_ghz, "points": points,
                       "inductance_h": model.inductance_h, "resistance_ohm": model.resistance_ohm,
                       "mutual_inductance_h": model.mutual_inductance_h},
        "host_available_gib_before": available,
    }

    def finish(status: str, *, simulation_status: str = "unknown", error: str | None = None) -> dict:
        payload["status"] = status
        payload["simulation_status"] = simulation_status
        if error:
            payload["error"] = error
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        artifacts = {key: filename for key, filename in {
            "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
            "ac_raw": "ac.ac", "comparison_csv": "comparison.csv",
            "stdout": "spectre.stdout.log", "stderr": "spectre.stderr.log",
        }.items() if (output_dir / filename).is_file()}
        write_evidence_manifest(output_dir, artifacts)
        return payload

    created = runner.ensure_remote_dir(remote_dir)
    if not created.ok:
        return finish("mkdir_failed", error=f"returncode={created.returncode}")
    uploaded = runner.upload(output_dir / "netlist.scs", str(PurePosixPath(remote_dir) / "netlist.scs"))
    if not uploaded.ok:
        return finish("upload_failed", error=f"returncode={uploaded.returncode}")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "-format", "psfascii", "-raw", "psf", "+log", "spectre.log", "netlist.scs"],
        cwd=remote_dir,
    )
    (output_dir / "spectre.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(result.stderr, encoding="utf-8")
    log_download = runner.download(str(PurePosixPath(remote_dir) / "spectre.log"), output_dir / "spectre.log")
    if not result.ok:
        return finish("spectre_failed", simulation_status="failed", error=f"returncode={result.returncode}")
    if not log_download.ok:
        return finish("log_download_failed", error=f"returncode={log_download.returncode}")
    raw_download = runner.download(str(PurePosixPath(remote_dir) / "psf/ac.ac"), output_dir / "ac.ac")
    if not raw_download.ok:
        return finish("raw_download_failed", error=f"returncode={raw_download.returncode}")
    try:
        log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
        if "spectre completes with 0 errors" not in log:
            raise ValueError("Spectre log lacks clean completion marker")
        rows, summary = compare_mcr_trace(
            model,
            parse_complex_trace(output_dir / "ac.ac", "n1"),
            parse_complex_trace(output_dir / "ac.ac", "n2"),
            start_hz=start_hz,
            stop_hz=stop_hz,
            points=points,
        )
        with (output_dir / "comparison.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError, ZeroDivisionError) as exc:
        return finish("result_parse_failed", error=str(exc))
    payload["source"] = "cadence_spectre"
    payload["metrics"] = summary
    payload["points"] = len(rows)
    payload["units"] = {"max_v1_error_ohm": "ohm", "max_z21_error_ohm": "ohm",
                        "max_paper_z21_error_ohm": "ohm", "max_v1_error_normalized": "1",
                        "max_z21_error_normalized": "1", "max_paper_z21_error_normalized": "1"}
    payload["calibration_pass"] = all(
        math.isfinite(summary[key]) and summary[key] <= MAX_NORMALIZED_CALIBRATION_ERROR
        for key in ("max_v1_error_normalized", "max_z21_error_normalized", "max_paper_z21_error_normalized")
    )
    return finish("ok" if payload["calibration_pass"] else "model_mismatch", simulation_status="ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate ideal symmetric parallel RLC model against Spectre AC")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--f0-ghz", type=float, default=30.0)
    parser.add_argument("--q0", type=float, default=3.0)
    parser.add_argument("--capacitance-ff", type=float, default=100.0)
    parser.add_argument("--coupling-k", type=float, default=0.4)
    parser.add_argument("--start-ghz", type=float, default=20.0)
    parser.add_argument("--stop-ghz", type=float, default=40.0)
    parser.add_argument("--points", type=int, default=41)
    args = parser.parse_args()
    output = args.output or Path("results/runs/mcr_calibration") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    )
    try:
        payload = run_mcr_calibration(args.config, output, f0_ghz=args.f0_ghz, q0=args.q0,
                                      capacitance_ff=args.capacitance_ff, coupling_k=args.coupling_k,
                                      start_ghz=args.start_ghz, stop_ghz=args.stop_ghz, points=args.points)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"status={payload['status']}")
    print(f"output={output.resolve()}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
