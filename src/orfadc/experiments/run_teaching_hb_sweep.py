from __future__ import annotations

import argparse
import csv
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.cadence.compression_metrics import extract_p1db
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_teaching_hb import render_teaching_hb_netlist, run_teaching_hb
from orfadc.metric_contract import validate_metrics_payload


def run_teaching_hb_sweep(
    config_path: Path, sweep_dir: Path, *, input_powers_dbm: list[float],
    frequency_ghz: float = 10.0, harmonics: int = 7, vbias_v: float = 0.65,
) -> dict:
    _require_private_path(sweep_dir)
    if (
        not isinstance(input_powers_dbm, list) or not 4 <= len(input_powers_dbm) <= 12
        or any(type(power) not in {int, float} or not math.isfinite(power) or not -100 <= power <= 0
               for power in input_powers_dbm)
        or any(right <= left for left, right in zip(input_powers_dbm, input_powers_dbm[1:]))
    ):
        raise ValueError("teaching HB sweep needs 4..12 increasing powers in -100..0 dBm")
    if type(vbias_v) not in {int, float} or not math.isfinite(vbias_v) or not 0.5 <= vbias_v <= 0.7:
        raise ValueError("teaching VBIAS must be finite and within 0.5..0.7 V")
    render_teaching_hb_netlist(
        input_powers_dbm[0], frequency_ghz=frequency_ghz, harmonics=harmonics, vbias_v=vbias_v,
    )
    sweep_dir.mkdir(parents=True, exist_ok=False)
    write_json(sweep_dir / "sweep_config.json", {
        "schema_version": 1, "input_powers_dbm": input_powers_dbm,
        "frequency_ghz": frequency_ghz, "harmonics": harmonics, "vbias_v": vbias_v,
        "scope": "MOS1 teaching model only; not a foundry LNA or paper result",
    })
    rows = []
    failures = []
    for index, power in enumerate(input_powers_dbm):
        run_dir = sweep_dir / f"point_{index:02d}"
        try:
            result = run_teaching_hb(
                config_path, run_dir, input_dbm=power,
                frequency_ghz=frequency_ghz, harmonics=harmonics, vbias_v=vbias_v,
            )
            verified = read_evidenced_metrics(run_dir)
            if verified != result:
                raise ValueError("teaching HB point differs from verified evidence")
            if result["status"] != "hb_fundamental_extracted":
                failures.append({"point_index": index, "pin_dbm": float(power),
                                 "failure_type": "backend_status", "backend_status": result["status"]})
                break
            if (
                result.get("simulation_status") != "ok"
                or result.get("source") != "cadence_spectre"
                or result.get("circuit_class") != "teaching_mos1_common_source"
                or result.get("not_lna_result") is not True
                or result.get("spec_pass") is not None
                or result["parameters"] != {"input_dbm": power, "frequency_ghz": frequency_ghz,
                                              "harmonics": harmonics, "vbias_v": vbias_v}
            ):
                raise ValueError("teaching HB point provenance or settings changed")
            metrics = result["metrics"]
            rows.append({
                "point_index": index,
                "run_id": run_dir.name,
                "pin_dbm": float(power),
                "pout_dbm": metrics["output_power_dbm"],
                "gain_db": metrics["power_gain_db"],
                "small_signal_s21_db": metrics["small_signal_s21_db"],
                "hb_minus_s21_db": metrics["hb_minus_s21_db"],
            })
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            failures.append({"point_index": index, "pin_dbm": float(power),
                             "failure_type": type(exc).__name__})
            break
    if rows:
        with (sweep_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    compression = None
    status = "incomplete" if failures else "unknown"
    if not failures:
        try:
            compression = extract_p1db(rows, linear_points=3)
        except ValueError:
            status = "invalid_linear_reference"
        else:
            status = compression["status"]
    summary = {
        "schema_version": 1,
        "status": status,
        "simulation_status": "ok" if not failures else "unknown",
        "source": "cadence_spectre" if not failures else None,
        "circuit_class": "teaching_mos1_common_source",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": sweep_dir.name,
        "scope": "MOS1 teaching HB power sweep; not a foundry LNA result",
        "analysis": ["dc", "sp", "noise", "hb"],
        "input_powers_dbm": input_powers_dbm,
        "vbias_v": vbias_v,
        "points_completed": len(rows),
        "point_run_ids": [row["run_id"] for row in rows],
        "failures": failures,
        "compression": compression,
        "metrics": compression,
    }
    validate_metrics_payload(summary)
    write_json(sweep_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sequential Cadence HB sweep for the public MOS1 teaching LNA")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--sweep-root", type=Path, default=_PRIVATE_ROOT / "teaching_hb_sweeps")
    parser.add_argument("--frequency-ghz", type=float, default=10.0)
    parser.add_argument("--harmonics", type=int, default=7)
    parser.add_argument("--vbias-v", type=float, default=0.65)
    parser.add_argument("--powers-dbm", type=float, nargs="+", required=True)
    args = parser.parse_args()
    sweep_dir = args.sweep_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        summary = run_teaching_hb_sweep(
            args.config, sweep_dir, input_powers_dbm=args.powers_dbm,
            frequency_ghz=args.frequency_ghz, harmonics=args.harmonics, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={summary['status']} points={summary['points_completed']} output={sweep_dir.resolve()}")
    return 0 if summary["status"] in {"ok", "quality_warning", "unbracketed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
