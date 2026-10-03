from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.cadence.passive_quality import oneport_impedance
from orfadc.cadence.psfascii_reader import parse_complex_trace
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_inductor_oneport import audit_pdk_inductor_oneport
from orfadc.experiments.audit_pdk_rf_default_three_stage import audit_pdk_rf_default_three_stage
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_KEYS = ("c_outer_ff", "c_inner_ff", "l_middle_nh", "l_inner_nh")
_LOWER = (10.0, 10.0, 0.1, 0.1)
_UPPER = (1000.0, 1000.0, 10.0, 10.0)
_SEED = 17
_RANDOM_BUDGET = 12_288
_LOCAL_BUDGET = 4_096


def predict_ladder_s11(
    frequency_hz: list[float], load_impedance: list[complex], params: dict[str, float],
) -> list[complex]:
    if len(frequency_hz) != len(load_impedance) or not frequency_hz:
        raise ValueError("ladder source frequency and impedance arrays must align")
    if set(params) != set(_KEYS) or any(
        type(params[key]) not in {float, int} or not math.isfinite(params[key])
        or not low <= params[key] <= high
        for key, low, high in zip(_KEYS, _LOWER, _UPPER, strict=True)
    ):
        raise ValueError("ladder parameters exceed the bounded ideal search domain")
    c_outer = params["c_outer_ff"] * 1e-15
    c_inner = params["c_inner_ff"] * 1e-15
    l_middle = params["l_middle_nh"] * 1e-9
    l_inner = params["l_inner_nh"] * 1e-9
    reflections = []
    for frequency, load in zip(frequency_hz, load_impedance, strict=True):
        if frequency <= 0 or load.real <= 0:
            raise ValueError("ladder requires a positive-frequency, passive input load")
        omega = 2 * math.pi * frequency
        inner_shunt = 1 / (1 / load + 1j * omega * c_inner)
        inner_series = inner_shunt + 1j * omega * l_inner
        middle_shunt = 1 / (1 / inner_series + 1 / (1j * omega * l_middle))
        port_impedance = middle_shunt + 1 / (1j * omega * c_outer)
        gamma = (port_impedance - 50.0) / (port_impedance + 50.0)
        if not math.isfinite(abs(gamma)):
            raise ValueError("ladder predicted a nonfinite reflection coefficient")
        reflections.append(gamma)
    return reflections


def _draw_log_uniform(rng: random.Random) -> dict[str, float]:
    return {key: math.exp(rng.uniform(math.log(low), math.log(high)))
            for key, low, high in zip(_KEYS, _LOWER, _UPPER, strict=True)}


def _mutate(rng: random.Random, best: dict[str, float], scale: float) -> dict[str, float]:
    return {key: min(high, max(low, value * math.exp(rng.gauss(0, scale))))
            for key, low, high in zip(_KEYS, _LOWER, _UPPER, strict=True)
            for value in (best[key],)}


def search_ladder(
    frequency_hz: list[float], load_impedance: list[complex], *,
    seed: int = _SEED, random_budget: int = _RANDOM_BUDGET,
    local_budget: int = _LOCAL_BUDGET,
) -> tuple[dict[str, float], list[dict[str, float]]]:
    if (
        type(seed) is not int or seed < 0 or type(random_budget) is not int
        or type(local_budget) is not int or random_budget < 1024
        or local_budget < 1024 or random_budget % 1024 or local_budget % 1024
    ):
        raise ValueError("ladder search needs fixed positive 1024-point budget blocks")
    rng = random.Random(seed)
    best: dict[str, float] | None = None
    best_worst = math.inf
    trace = []
    total = random_budget + local_budget
    for index in range(total):
        if index < random_budget:
            proposed = _draw_log_uniform(rng)
        else:
            assert best is not None
            fraction = (index - random_budget) / local_budget
            proposed = _mutate(rng, best, 0.35 * (1 - fraction) + 0.03)
        worst = max(abs(value) for value in predict_ladder_s11(frequency_hz, load_impedance, proposed))
        if worst < best_worst:
            best, best_worst = proposed, worst
        if (index + 1) % 1024 == 0:
            trace.append({"evaluations": index + 1, "best_worst_s11_db": 20 * math.log10(best_worst)})
    assert best is not None
    return best, trace


def _csv_bytes(rows: list[dict], fieldnames: tuple[str, ...]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def build_pdk_rf_input_ladder_search(
    active_dir: Path, create_dir: Path, spiral_dir: Path, run_id: str,
) -> tuple[dict, bytes, bytes]:
    for path in (active_dir, create_dir, spiral_dir):
        _require_private_path(path)
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("ladder search run ID is unsafe")
    audit_pdk_rf_default_three_stage(active_dir, create_dir)
    audit_pdk_inductor_oneport(spiral_dir)
    active = read_evidenced_metrics(active_dir)
    spiral = read_evidenced_metrics(spiral_dir)
    if (
        active.get("not_lna_result") is not True
        or spiral.get("source_run_kind") != "oa_default_pdk_spiral_direct_spectre"
        or spiral.get("physical_qualification") is not False
    ):
        raise ValueError("ladder search source provenance differs")
    frequency, reflection = parse_complex_trace(active_dir / "sp.sp", "s11")
    if len(frequency) != 161 or frequency[0] != 8e9 or frequency[-1] != 12e9:
        raise ValueError("ladder search needs the original full 8-12 GHz grid")
    load = [oneport_impedance(value, 50.0) for value in reflection]
    best, trace = search_ladder(frequency, load)
    predicted = predict_ladder_s11(frequency, load, best)
    predicted_rows = [{
        "freq_hz": sample, "freq_ghz": sample / 1e9,
        "predicted_s11_db": 20 * math.log10(abs(value)),
        "measured_baseline_s11_db": 20 * math.log10(abs(original)),
    } for sample, value, original in zip(frequency, predicted, reflection, strict=True)]
    source_paths = {"active": active_dir, "create": create_dir, "spiral": spiral_dir}
    report = {
        "schema_version": 1, "status": "ideal_ladder_search_recorded",
        "simulation_status": "unknown", "source": "cadence_spectre_archives",
        "circuit_class": "pdk_rf_default_input_ladder_search",
        "model_kind": "authorized_pdk_private", "not_lna_result": True,
        "spec_pass": None, "run_id": run_id,
        "scope": "ideal four-element input ladder optimized on audited S11; candidate not yet simulated",
        "source_run_ids": {name: path.name for name, path in source_paths.items()},
        "source_record_sha256": {name: hashlib.sha256((path / (
            "run_status.json" if name == "create" else "evidence_manifest.json"
        )).read_bytes()).hexdigest() for name, path in source_paths.items()},
        "seed": _SEED, "random_budget": _RANDOM_BUDGET,
        "local_budget": _LOCAL_BUDGET, "total_evaluations": _RANDOM_BUDGET + _LOCAL_BUDGET,
        "component_bounds": {key: [low, high] for key, low, high in zip(_KEYS, _LOWER, _UPPER, strict=True)},
        "best_ideal_parameters": best,
        "predicted_worst_s11_db": max(row["predicted_s11_db"] for row in predicted_rows),
        "measured_baseline_worst_s11_db": max(row["measured_baseline_s11_db"] for row in predicted_rows),
        "default_spiral_effective_l_nh_at_10ghz": spiral["metrics"]["effective_l_at_center_h"] * 1e9,
        "default_spiral_minimum_q_8_to_12ghz": spiral["metrics"]["minimum_q_in_band"],
        "physical_qualification": False, "no_candidate_simulated": True,
    }
    validate_metrics_payload(report)
    return report, _csv_bytes(trace, ("evaluations", "best_worst_s11_db")), _csv_bytes(
        predicted_rows, ("freq_hz", "freq_ghz", "predicted_s11_db", "measured_baseline_s11_db"),
    )


def write_pdk_rf_input_ladder_search(
    active_dir: Path, create_dir: Path, spiral_dir: Path, output_dir: Path,
) -> dict:
    _require_private_path(output_dir)
    report, trace, waveforms = build_pdk_rf_input_ladder_search(
        active_dir, create_dir, spiral_dir, output_dir.name,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "metrics.json", report)
    (output_dir / "search_trace.csv").write_bytes(trace)
    (output_dir / "predicted_waveforms.csv").write_bytes(waveforms)
    write_evidence_manifest(output_dir, {
        "metrics": "metrics.json", "trace": "search_trace.csv", "waveforms": "predicted_waveforms.csv",
    })
    return report


def audit_pdk_rf_input_ladder_search(report_dir: Path) -> dict:
    _require_private_path(report_dir)
    if not report_dir.is_dir() or report_dir.is_symlink():
        raise ValueError("ladder search archive is missing or unsafe")
    saved = read_evidenced_metrics(report_dir)
    ids = saved.get("source_run_ids")
    if (
        not isinstance(ids, dict) or set(ids) != {"active", "create", "spiral"}
        or any(not isinstance(value, str) or _RUN_ID.fullmatch(value) is None for value in ids.values())
    ):
        raise ValueError("ladder search source IDs are invalid")
    rebuilt, trace, waveforms = build_pdk_rf_input_ladder_search(
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / ids["active"],
        _PRIVATE_ROOT / "pdk_three_stage_fixed" / ids["create"],
        _PRIVATE_ROOT / "passive_quality_reference" / ids["spiral"],
        report_dir.name,
    )
    if (
        saved != rebuilt
        or (report_dir / "search_trace.csv").read_bytes() != trace
        or (report_dir / "predicted_waveforms.csv").read_bytes() != waveforms
    ):
        raise ValueError("ladder search differs from the reaudited source or deterministic search")
    return {"status": "verified", "evaluations": rebuilt["total_evaluations"],
            "no_candidate_simulated": True, "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Search a bounded ideal input ladder from audited PDK RF S11")
    parser.add_argument("--active-dir", type=Path)
    parser.add_argument("--create-dir", type=Path)
    parser.add_argument("--spiral-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_input_ladder_search")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_pdk_rf_input_ladder_search(args.audit_dir)
        print(f"status={result['status']} evaluations={result['evaluations']} no_candidate_simulated=true")
        return 0
    if any(path is None for path in (args.active_dir, args.create_dir, args.spiral_dir)):
        parser.error("active, create, and spiral source archives are required")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = args.output_root / run_id
    report = write_pdk_rf_input_ladder_search(args.active_dir, args.create_dir, args.spiral_dir, output_dir)
    result = audit_pdk_rf_input_ladder_search(output_dir)
    print(f"status={result['status']} predicted_worst_s11_db={report['predicted_worst_s11_db']:.3f} "
          f"output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
