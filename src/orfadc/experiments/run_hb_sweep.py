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
from orfadc.experiments.run_hb_diagnostic import run_hb_diagnostic
from orfadc.metric_contract import validate_metrics_payload


def run_hb_sweep(
    config_path: Path,
    sweep_dir: Path,
    *,
    template: Path,
    template_sha256: str,
    rd_ohm: float,
    vbias_v: float,
    input_powers_dbm: list[float],
    frequency_ghz: float = 10.0,
    harmonics: int = 7,
) -> dict:
    _require_private_path(sweep_dir)
    if not isinstance(input_powers_dbm, list) or not 4 <= len(input_powers_dbm) <= 12:
        raise ValueError("HB sweep needs 4..12 input powers")
    if any(type(value) not in {int, float} or not math.isfinite(value) or not -100 <= value <= 0
           for value in input_powers_dbm):
        raise ValueError("HB input powers must be finite and within -100..0 dBm")
    if any(right <= left for left, right in zip(input_powers_dbm, input_powers_dbm[1:])):
        raise ValueError("HB input powers must be strictly increasing")
    sweep_dir.mkdir(parents=True, exist_ok=False)
    write_json(sweep_dir / "sweep_config.json", {
        "schema_version": 1,
        "rd_ohm": rd_ohm,
        "vbias_v": vbias_v,
        "input_powers_dbm": input_powers_dbm,
        "frequency_ghz": frequency_ghz,
        "harmonics": harmonics,
        "template_sha256": template_sha256,
        "scope": "active common-source diagnostic, not an LNA specification test",
    })
    rows: list[dict[str, float | str]] = []
    failures: list[dict[str, str | float]] = []
    for index, power in enumerate(input_powers_dbm):
        run_dir = sweep_dir / f"point_{index:02d}"
        try:
            result = run_hb_diagnostic(
                config_path, run_dir, template=template, template_sha256=template_sha256,
                rd_ohm=rd_ohm, vbias_v=vbias_v, input_dbm=power,
                frequency_ghz=frequency_ghz, harmonics=harmonics,
            )
            evidence = read_evidenced_metrics(run_dir)
            if result != evidence:
                raise ValueError("HB point disagrees with verified evidence")
            if result["status"] != "hb_fundamental_extracted":
                failures.append({"point_index": index, "pin_dbm": float(power),
                                 "failure_type": "backend_status", "backend_status": result["status"]})
                break
            parameters = result["parameters"]
            if (
                result.get("source") != "cadence_spectre"
                or result.get("simulation_status") != "ok"
                or result.get("not_lna_result") is not True
                or result.get("spec_pass") is not None
                or parameters["input_dbm"] != power
                or parameters["rd_ohm"] != rd_ohm
                or parameters["vbias_v"] != vbias_v
                or parameters["frequency_ghz"] != frequency_ghz
                or parameters["harmonics"] != harmonics
            ):
                raise ValueError("HB point provenance or settings disagree with sweep")
            measurements = evidence["metrics"]
            rows.append({
                "point_index": index,
                "run_id": run_dir.name,
                "pin_dbm": float(power),
                "pout_dbm": float(measurements["output_power_dbm"]),
                "gain_db": float(measurements["power_gain_db"]),
                "small_signal_s21_db": float(measurements["small_signal_s21_db"]),
                "hb_minus_s21_db": float(measurements["hb_minus_s21_db"]),
            })
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append({"point_index": index, "pin_dbm": float(power),
                             "failure_type": type(exc).__name__})
            break
    if rows:
        with (sweep_dir / "power_sweep.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    compression: dict[str, object] | None = None
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
        "circuit_class": "active_common_source_smoke",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": sweep_dir.name,
        "scope": "diagnostic common-source HB power sweep; not a qualified LNA IP1dB",
        "analysis": ["dc", "sp", "noise", "hb"],
        "input_powers_dbm": input_powers_dbm,
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
    parser = argparse.ArgumentParser(description="Sequential OA common-source HB power sweep")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--sweep-root", type=Path, default=_PRIVATE_ROOT / "hb_sweeps")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    parser.add_argument("--frequency-ghz", type=float, default=10.0)
    parser.add_argument("--harmonics", type=int, default=7)
    parser.add_argument("--powers-dbm", type=float, nargs="+", required=True)
    args = parser.parse_args()
    sweep_dir = args.sweep_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        summary = run_hb_sweep(
            args.config, sweep_dir, template=args.template, template_sha256=args.template_sha256,
            rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
            input_powers_dbm=args.powers_dbm, frequency_ghz=args.frequency_ghz,
            harmonics=args.harmonics,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={summary['status']} points={summary['points_completed']}")
    print(f"sweep_dir={sweep_dir.resolve()}")
    return 0 if summary["status"] in {"ok", "quality_warning", "unbracketed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
