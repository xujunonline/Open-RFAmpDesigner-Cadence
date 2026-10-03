from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from orfadc.cadence.compression_metrics import extract_p1db
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.hb_metrics import extract_hb_fundamental_power, extract_sp_s21_at_frequency
from orfadc.experiments.run_hb_diagnostic import _OUTPUT_NODE


_INPUT_TONE = re.compile(
    r"^PORT1 \([^\r\n)]+\) port r=50 num=1 type=sine dbm=([-+0-9.eE]+) freq=([-+0-9.eE]+)(?=\r?$)",
    re.MULTILINE,
)
_CSV_FIELDS = (
    "point_index", "run_id", "pin_dbm", "pout_dbm", "gain_db",
    "small_signal_s21_db", "hb_minus_s21_db",
)


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("symlinked sweep metadata is not accepted")

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON value: {value}")

    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(payload, dict):
        raise ValueError("sweep metadata must be a JSON object")
    return payload


def _close(actual: object, expected: float, label: str) -> None:
    if type(expected) not in {int, float} or not math.isfinite(expected):
        raise ValueError(f"HB sweep {label} has an invalid expected value")
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError(f"HB sweep {label} disagrees with raw results")


def audit_hb_sweep(sweep_dir: Path) -> dict:
    """Re-extract an archived diagnostic sweep without modifying its evidence."""
    if not sweep_dir.is_dir() or sweep_dir.is_symlink():
        raise ValueError("sweep directory must exist and must not be a symlink")
    config = _read_json(sweep_dir / "sweep_config.json")
    summary = _read_json(sweep_dir / "summary.json")
    powers = config.get("input_powers_dbm")
    if (
        config.get("schema_version") != 1
        or summary.get("schema_version") != 1
        or not isinstance(powers, list)
        or not 4 <= len(powers) <= 12
        or any(type(power) not in {int, float} or not math.isfinite(power) or not -100 <= power <= 0
               for power in powers)
        or any(right <= left for left, right in zip(powers, powers[1:]))
    ):
        raise ValueError("invalid HB sweep configuration")
    frequency_ghz = config.get("frequency_ghz")
    if type(frequency_ghz) not in {int, float} or not math.isfinite(frequency_ghz) or not 0.1 <= frequency_ghz <= 20:
        raise ValueError("invalid HB sweep frequency")
    if (
        type(config.get("harmonics")) is not int or not 1 <= config["harmonics"] <= 7
        or any(type(config.get(key)) not in {int, float} or not math.isfinite(config[key])
               for key in ("rd_ohm", "vbias_v"))
    ):
        raise ValueError("invalid HB sweep passive or bias configuration")
    if (
        summary.get("status") not in {"ok", "quality_warning", "unbracketed"}
        or summary.get("simulation_status") != "ok"
        or summary.get("source") != "cadence_spectre"
        or summary.get("circuit_class") != "active_common_source_smoke"
        or summary.get("not_lna_result") is not True
        or summary.get("spec_pass") is not None
        or summary.get("run_id") != sweep_dir.name
        or summary.get("input_powers_dbm") != powers
        or summary.get("points_completed") != len(powers)
        or summary.get("failures") != []
        or summary.get("point_run_ids") != [f"point_{index:02d}" for index in range(len(powers))]
        or summary.get("metrics") != summary.get("compression")
    ):
        raise ValueError("HB sweep summary has incomplete or inconsistent provenance")

    csv_path = sweep_dir / "power_sweep.csv"
    if csv_path.is_symlink():
        raise ValueError("symlinked HB sweep CSV is not accepted")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(_CSV_FIELDS):
            raise ValueError("HB sweep CSV columns disagree with the contract")
        csv_rows = list(reader)
    if len(csv_rows) != len(powers):
        raise ValueError("HB sweep CSV row count disagrees with the configuration")

    reconstructed = []
    for index, power in enumerate(powers):
        run_dir = sweep_dir / f"point_{index:02d}"
        if run_dir.is_symlink():
            raise ValueError("symlinked HB point directory is not accepted")
        point = read_evidenced_metrics(run_dir)
        manifest = _read_json(run_dir / "evidence_manifest.json")
        entries = manifest.get("artifacts")
        required = {"metrics": "metrics.json", "netlist": "netlist.scs",
                    "spectre_log": "spectre.log", "hb_fd_raw": "hb.fd.pss_hb",
                    "sp_raw": "sp.sp"}
        if not isinstance(entries, dict) or any(
            not isinstance(entries.get(key), dict) or entries[key].get("path") != filename
            for key, filename in required.items()
        ):
            raise ValueError(f"HB point {index} raw data are not in the verified manifest")
        parameters = point.get("parameters")
        if (
            point.get("status") != "hb_fundamental_extracted"
            or point.get("source") != "cadence_spectre"
            or point.get("simulation_status") != "ok"
            or point.get("circuit_class") != "active_common_source_smoke"
            or point.get("not_lna_result") is not True
            or point.get("spec_pass") is not None
            or point.get("run_id") != run_dir.name
            or not isinstance(parameters, dict)
        ):
            raise ValueError(f"HB point {index} is not verified diagnostic evidence")
        for key, expected in (
            ("input_dbm", power), ("rd_ohm", config.get("rd_ohm")),
            ("vbias_v", config.get("vbias_v")), ("frequency_ghz", frequency_ghz),
            ("harmonics", config.get("harmonics")),
        ):
            _close(parameters.get(key), expected, f"point {index} {key}")
        netlist = (run_dir / "netlist.scs").read_text(encoding="utf-8")
        outputs = _OUTPUT_NODE.findall(netlist)
        tones = _INPUT_TONE.findall(netlist)
        if len(outputs) != 1 or len(tones) != 1:
            raise ValueError(f"HB point {index} has ambiguous port reference planes")
        _close(float(tones[0][0]), power, f"point {index} netlist power")
        _close(float(tones[0][1]), frequency_ghz * 1e9, f"point {index} netlist frequency")
        fundamental = extract_hb_fundamental_power(
            run_dir / "hb.fd.pss_hb", output_node=outputs[0], fundamental_hz=frequency_ghz * 1e9,
        )
        s21_db = extract_sp_s21_at_frequency(run_dir / "sp.sp", frequency_ghz * 1e9)
        gain_db = fundamental["output_power_dbm"] - power
        raw = {
            "pin_dbm": power,
            "pout_dbm": fundamental["output_power_dbm"],
            "gain_db": gain_db,
            "small_signal_s21_db": s21_db,
            "hb_minus_s21_db": gain_db - s21_db,
        }
        measurements = point.get("metrics")
        if not isinstance(measurements, dict):
            raise ValueError(f"HB point {index} has no stored metrics")
        for key, expected in (
            ("output_power_dbm", raw["pout_dbm"]),
            ("power_gain_db", raw["gain_db"]),
            ("small_signal_s21_db", raw["small_signal_s21_db"]),
            ("hb_minus_s21_db", raw["hb_minus_s21_db"]),
        ):
            _close(measurements.get(key), expected, f"point {index} {key}")
        csv_row = csv_rows[index]
        if csv_row["point_index"] != str(index) or csv_row["run_id"] != run_dir.name:
            raise ValueError(f"HB point {index} CSV identity disagrees with the run")
        for key, expected in raw.items():
            try:
                value = float(csv_row[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"HB point {index} CSV has invalid {key}") from exc
            _close(value, expected, f"point {index} CSV {key}")
        reconstructed.append(raw)

    compression = extract_p1db(reconstructed, linear_points=3)
    recorded = summary.get("compression")
    if not isinstance(recorded, dict) or compression["status"] != summary["status"]:
        raise ValueError("HB sweep compression status disagrees with raw data")
    for key, expected in compression.items():
        if key in {"ip1db_dbm", "op1db_dbm", "small_signal_gain_db"} and expected is not None:
            _close(recorded.get(key), expected, f"compression {key}")
        elif recorded.get(key) != expected:
            raise ValueError(f"HB sweep compression {key} disagrees with raw data")
    return {
        "status": "verified",
        "run_id": sweep_dir.name,
        "points_verified": len(reconstructed),
        "compression": compression,
        "not_lna_result": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of an archived OA common-source HB sweep")
    parser.add_argument("sweep_dir", type=Path)
    args = parser.parse_args()
    try:
        report = audit_hb_sweep(args.sweep_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"HB sweep audit failed: {type(exc).__name__}: {exc}")
    print(f"status={report['status']} points={report['points_verified']}")
    print(f"compression={report['compression']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
