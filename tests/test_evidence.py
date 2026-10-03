from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import (
    build_evidence_manifest,
    read_evidenced_metrics,
    verify_evidence_manifest,
    write_evidence_manifest,
)


def _passive_run(root: Path) -> dict[str, str]:
    root.mkdir()
    payload = {
        "schema_version": 1,
        "status": "ok",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "circuit_class": "passive_twoport",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": "passive-mock-001",
        "metrics": {"s21_db": -3.0},
    }
    (root / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / "netlist.scs").write_text("simulator lang=spectre\n", encoding="utf-8")
    (root / "spectre.log").write_text("spectre completes with 0 errors, 0 warnings\n", encoding="utf-8")
    (root / "sp.sp").write_text("mock raw SP data\n", encoding="utf-8")
    return {"metrics": "metrics.json", "netlist": "netlist.scs",
            "spectre_log": "spectre.log", "sp_raw": "sp.sp"}


def _active_pass(root: Path) -> dict[str, str]:
    files = _passive_run(root)
    payload = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    payload.update(
        circuit_class="active_lna", not_lna_result=False, spec_pass=True,
        run_id="active-mock-001",
        spec={"id": "S1", "gain_db": 10.0, "nf_max_db": 3.0,
              "ip1db_min_dbm": -15.0, "power_ma": 10.0},
        candidate={"candidate_id": "c1", "spec_id": "S1", "seed": 0},
        seed=0, timeout_seconds=300,
        frequency_band_ghz={"low": 9.0, "high": 11.0},
        analysis=["dc", "sp", "noise", "compression"],
        reference_planes={"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        units={"s11_db": "dB", "s21_db": "dB", "nf_db": "dB",
               "ip1db_dbm": "dBm", "power_ma": "mA"},
        metrics={"s11_db": -15.0, "s21_db": 15.0, "nf_db": 2.0,
                 "ip1db_dbm": -10.0, "power_ma": 5.0},
    )
    (root / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / "candidate.json").write_text(json.dumps(payload["candidate"]), encoding="utf-8")
    for name in ("waveforms.csv", "dc.raw", "noise.raw", "compression.raw"):
        (root / name).write_text(f"mock {name}\n", encoding="utf-8")
    files.update(candidate="candidate.json", waveforms="waveforms.csv",
                 dc_raw="dc.raw", noise_raw="noise.raw", compression_raw="compression.raw")
    return files


def test_manifest_roundtrip_and_exclusive_write(tmp_path: Path) -> None:
    run = tmp_path / "run"
    files = _passive_run(run)
    path = write_evidence_manifest(run, files)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert verify_evidence_manifest(run, manifest)["run_id"] == "passive-mock-001"
    assert read_evidenced_metrics(run)["run_id"] == "passive-mock-001"
    with pytest.raises(FileExistsError):
        write_evidence_manifest(run, files)


def test_manifest_detects_tampering_and_mixed_runs(tmp_path: Path) -> None:
    run = tmp_path / "run"
    files = _passive_run(run)
    manifest = build_evidence_manifest(run, files)
    (run / "sp.sp").write_text("changed raw SP data\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        verify_evidence_manifest(run, manifest)
    manifest = build_evidence_manifest(run, files)
    manifest["run_id"] = "another-run"
    with pytest.raises(ValueError, match="run_id disagrees"):
        verify_evidence_manifest(run, manifest)
    manifest["schema_version"] = True
    with pytest.raises(ValueError, match="version"):
        verify_evidence_manifest(run, manifest)


def test_manifest_rejects_path_escape_duplicate_and_unclean_log(tmp_path: Path) -> None:
    run = tmp_path / "run"
    files = _passive_run(run)
    with pytest.raises(ValueError, match="escape"):
        build_evidence_manifest(run, files | {"sp_raw": "../sp.sp"})
    with pytest.raises(ValueError, match="distinct path"):
        build_evidence_manifest(run, files | {"noise_raw": "sp.sp"})
    (run / "spectre.log").write_text("simulation failed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean completion"):
        build_evidence_manifest(run, files)


def test_empty_optional_stderr_is_allowed_but_empty_raw_is_not(tmp_path: Path) -> None:
    run = tmp_path / "run"
    files = _passive_run(run)
    (run / "spectre.stderr.log").write_text("", encoding="utf-8")
    files["stderr_log"] = "spectre.stderr.log"
    assert verify_evidence_manifest(run, build_evidence_manifest(run, files))["status"] == "ok"
    (run / "sp.sp").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty required artifact"):
        build_evidence_manifest(run, files)


def test_fullchain_manifest_requires_all_raw_analyses_and_candidate(tmp_path: Path) -> None:
    run = tmp_path / "run"
    files = _active_pass(run)
    with pytest.raises(ValueError, match="compression_raw"):
        build_evidence_manifest(run, {key: value for key, value in files.items() if key != "compression_raw"})
    assert verify_evidence_manifest(run, build_evidence_manifest(run, files))["spec_pass"] is True
    (run / "candidate.json").write_text('{"candidate_id":"other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="candidate snapshot disagrees"):
        build_evidence_manifest(run, files)


def test_failed_candidate_can_be_archived_without_spectre_output(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    candidate = {"candidate_id": "c1", "spec_id": "S1", "seed": 2}
    payload = {
        "schema_version": 1, "status": "mkdir_failed", "simulation_status": "unknown",
        "circuit_class": "active_lna", "not_lna_result": False, "spec_pass": None,
        "run_id": "failed-mock-001", "spec": {"id": "S1"}, "candidate": candidate,
        "seed": 2, "timeout_seconds": 30,
    }
    (run / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (run / "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
    manifest = build_evidence_manifest(run, {"metrics": "metrics.json", "candidate": "candidate.json"})
    assert verify_evidence_manifest(run, manifest)["simulation_status"] == "unknown"
