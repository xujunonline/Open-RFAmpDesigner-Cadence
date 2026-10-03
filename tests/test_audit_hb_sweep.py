from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from orfadc.cadence.compression_metrics import extract_p1db
from orfadc.cadence.evidence import build_evidence_manifest, write_evidence_manifest
from orfadc.experiments.audit_hb_sweep import audit_hb_sweep


_ARTIFACTS = {
    "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
    "hb_fd_raw": "hb.fd.pss_hb", "sp_raw": "sp.sp",
}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sweep_fixture(root: Path) -> Path:
    sweep = root / "sweep001"
    sweep.mkdir()
    powers = [-60.0, -50.0, -40.0, -10.0, 0.0]
    gains = [2.0, 2.0, 2.0, 1.5, 0.5]
    _write_json(sweep / "sweep_config.json", {
        "schema_version": 1, "input_powers_dbm": powers,
        "rd_ohm": 150.0, "vbias_v": 0.67, "frequency_ghz": 10.0, "harmonics": 7,
    })
    rows = []
    for index, (pin, gain) in enumerate(zip(powers, gains, strict=True)):
        point = sweep / f"point_{index:02d}"
        point.mkdir()
        pout = pin + gain
        watts = 1e-3 * 10 ** (pout / 10)
        voltage = math.sqrt(2 * 50 * watts)
        (point / "hb.fd.pss_hb").write_text(
            'HEADER\n"analysis type" "fd.pss_hb"\n"fundamental" 10000000000\n'
            'TYPE\nVALUE\n"freq" 0\n"out" (0 0)\n"PORT2:p" (0 0)\n'
            f'"freq" 10000000000\n"out" ({voltage:.17g} 0)\n'
            f'"PORT2:p" ({voltage / 50:.17g} 0)\nEND\n', encoding="ascii",
        )
        s21 = 10 ** (gain / 20)
        (point / "sp.sp").write_text(
            f'VALUE\n"freq" 10000000000\n"s21" ({s21:.17g} 0)\nEND\n', encoding="ascii",
        )
        (point / "netlist.scs").write_text(
            f'PORT1 (in 0) port r=50 num=1 type=sine dbm={pin} freq=10000000000\n'
            'PORT2 (out 0) port r=50 num=2 type=dc\n', encoding="ascii",
        )
        (point / "spectre.log").write_text("spectre completes with 0 errors", encoding="ascii")
        _write_json(point / "metrics.json", {
            "schema_version": 1, "status": "hb_fundamental_extracted", "simulation_status": "ok",
            "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
            "not_lna_result": True, "spec_pass": None, "run_id": point.name,
            "parameters": {"input_dbm": pin, "rd_ohm": 150.0, "vbias_v": 0.67,
                           "frequency_ghz": 10.0, "harmonics": 7},
            "metrics": {"output_power_dbm": pout, "power_gain_db": gain,
                        "small_signal_s21_db": gain, "hb_minus_s21_db": 0.0},
        })
        write_evidence_manifest(point, _ARTIFACTS)
        rows.append({
            "point_index": index, "run_id": point.name,
            "pin_dbm": pin, "pout_dbm": pout, "gain_db": gain,
            "small_signal_s21_db": gain, "hb_minus_s21_db": 0.0,
        })
    with (sweep / "power_sweep.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    compression = extract_p1db(rows)
    _write_json(sweep / "summary.json", {
        "schema_version": 1, "status": compression["status"], "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "active_common_source_smoke",
        "not_lna_result": True, "spec_pass": None, "run_id": sweep.name,
        "input_powers_dbm": powers, "points_completed": len(powers),
        "point_run_ids": [row["run_id"] for row in rows], "failures": [],
        "metrics": compression, "compression": compression,
    })
    return sweep


def test_audit_reextracts_all_points_and_compression(tmp_path: Path) -> None:
    report = audit_hb_sweep(_sweep_fixture(tmp_path))
    assert report["status"] == "verified"
    assert report["points_verified"] == 5
    assert report["compression"]["ip1db_dbm"] == pytest.approx(-5)
    assert report["not_lna_result"] is True


def test_audit_rejects_changed_raw_file(tmp_path: Path) -> None:
    sweep = _sweep_fixture(tmp_path)
    raw = sweep / "point_01" / "hb.fd.pss_hb"
    raw.write_text(raw.read_text(encoding="ascii") + "changed", encoding="ascii")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        audit_hb_sweep(sweep)


def test_audit_rejects_rehashed_fabricated_metric(tmp_path: Path) -> None:
    sweep = _sweep_fixture(tmp_path)
    point = sweep / "point_01"
    payload = json.loads((point / "metrics.json").read_text(encoding="utf-8"))
    payload["metrics"]["output_power_dbm"] += 1
    _write_json(point / "metrics.json", payload)
    _write_json(point / "evidence_manifest.json", build_evidence_manifest(point, _ARTIFACTS))
    with pytest.raises(ValueError, match="output_power_dbm disagrees with raw"):
        audit_hb_sweep(sweep)


def test_audit_requires_raw_files_in_hashed_manifest(tmp_path: Path) -> None:
    sweep = _sweep_fixture(tmp_path)
    point = sweep / "point_01"
    manifest_path = point / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["artifacts"]["hb_fd_raw"]
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="raw data are not in the verified manifest"):
        audit_hb_sweep(sweep)


def test_audit_rejects_summary_and_csv_drift(tmp_path: Path) -> None:
    sweep = _sweep_fixture(tmp_path)
    summary_path = sweep / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["compression"]["ip1db_dbm"] += 2
    summary["metrics"]["ip1db_dbm"] += 2
    _write_json(summary_path, summary)
    with pytest.raises(ValueError, match="compression ip1db_dbm"):
        audit_hb_sweep(sweep)
    summary["compression"]["ip1db_dbm"] -= 2
    summary["metrics"]["ip1db_dbm"] -= 2
    _write_json(summary_path, summary)
    csv_path = sweep / "power_sweep.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8").replace("-50.0,-48.0", "-50.0,-47.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="CSV pout_dbm"):
        audit_hb_sweep(sweep)
