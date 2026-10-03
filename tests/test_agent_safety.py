from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from orfadc.agents.refiner import Refiner
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.schemas import Candidate, RunConfig, Spec
from orfadc.tools.fullchain_eval import fullchain_eval


def _candidate() -> Candidate:
    return Candidate(candidate_id="S1_seed0_c0", spec_id="S1", seed=0,
                     power_ratio_list=[0.4, 0.3, 0.3])


def _spec() -> Spec:
    return Spec(id="S1", fc_ghz=10.0, fbw_ratio=0.2, power_ma=10.0,
                gain_db=10.0, nf_max_db=3.0, ip1db_min_dbm=-15.0)


def _evaluated_payload() -> dict:
    candidate = _candidate()
    spec = _spec()
    low, high = spec.band_edges_ghz
    return {
        "schema_version": 1,
        "status": "ok",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "circuit_class": "active_lna",
        "not_lna_result": False,
        "spec_pass": True,
        "run_id": "mock_backend_run_001",
        "analysis": ["dc", "sp", "noise", "compression"],
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        "frequency_band_ghz": {"low": low, "high": high},
        "units": {"s11_db": "dB", "s21_db": "dB", "nf_db": "dB",
                  "ip1db_dbm": "dBm", "power_ma": "mA"},
        "metrics": {"s11_db": -15.0, "s21_db": 15.0, "nf_db": 2.0,
                    "ip1db_dbm": -10.0, "power_ma": 5.0},
        "spec": asdict(spec),
        "candidate": {"candidate_id": candidate.candidate_id,
                      "spec_id": candidate.spec_id, "seed": candidate.seed},
        "seed": candidate.seed,
        "timeout_seconds": 300,
    }


def test_refiner_does_not_accept_missing_or_incomplete_metrics() -> None:
    refiner = Refiner()
    spec = _spec()
    assert refiner.refine(_candidate(), {}, spec).status == "needs_evaluation"
    assert refiner.refine(_candidate(), [], spec).status == "needs_evaluation"
    assert refiner.refine(_candidate(), {"status": "evaluated", "pass": True}, spec).status == "needs_evaluation"
    incomplete = _evaluated_payload()
    incomplete["metrics"].pop("ip1db_dbm")
    incomplete["spec_pass"] = False
    assert refiner.refine(_candidate(), incomplete, spec).status == "needs_evaluation"
    assert refiner.refine(_candidate(), _evaluated_payload(), spec).status == "needs_evaluation"


def test_refiner_recomputes_violations_and_rejects_wrong_context() -> None:
    refiner = Refiner()
    spec = _spec()
    failed_nf = _evaluated_payload()
    failed_nf["metrics"]["nf_db"] = 4.0
    failed_nf["spec_pass"] = False
    failed_nf["total_violation"] = 0.0  # Agent-supplied scores are ignored.
    assert refiner.refine(_candidate(), failed_nf, spec).status == "retry_stage2"

    for update in (
        {"status": "failed"},
        {"source": "llm_claim"},
        {"circuit_class": "active_common_source_smoke", "not_lna_result": True, "spec_pass": None},
        {"analysis": ["dc", "sp", "noise"]},
        {"frequency_band_ghz": {"low": 9.0, "high": 10.0}},
        {"spec_pass": False},
    ):
        assert refiner.refine(_candidate(), _evaluated_payload() | update, spec).status == "needs_evaluation"

    wrong_candidate = _evaluated_payload()
    wrong_candidate["candidate"]["candidate_id"] = "other"
    assert refiner.refine(_candidate(), wrong_candidate, spec).status == "needs_evaluation"
    wrong_spec = _evaluated_payload()
    wrong_spec["spec"]["gain_db"] = 8.0
    assert refiner.refine(_candidate(), wrong_spec, spec).status == "needs_evaluation"


def _write_mock_run(root: Path, payload: dict) -> None:
    root.mkdir()
    (root / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / "candidate.json").write_text(json.dumps(payload["candidate"]), encoding="utf-8")
    (root / "netlist.scs").write_text("simulator lang=spectre\n", encoding="utf-8")
    (root / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="utf-8")
    artifacts = {"metrics": "metrics.json", "candidate": "candidate.json",
                 "netlist": "netlist.scs", "spectre_log": "spectre.log"}
    if payload["spec_pass"] is True:
        for key in ("waveforms", "dc_raw", "sp_raw", "noise_raw", "compression_raw"):
            name = f"{key}.txt"
            (root / name).write_text(f"mock {key}\n", encoding="utf-8")
            artifacts[key] = name
    write_evidence_manifest(root, artifacts)


def test_refiner_reads_failure_from_run_but_never_accepts_hash_only_pass(tmp_path: Path) -> None:
    failed = _evaluated_payload()
    failed["metrics"]["nf_db"] = 4.0
    failed["spec_pass"] = False
    failed_dir = tmp_path / "failed"
    _write_mock_run(failed_dir, failed)
    assert Refiner().refine_from_run(_candidate(), failed_dir, _spec()).status == "retry_stage2"
    (failed_dir / "metrics.json").write_text("{}", encoding="utf-8")
    assert Refiner().refine_from_run(_candidate(), failed_dir, _spec()).status == "needs_evaluation"

    passed_dir = tmp_path / "claimed_pass"
    _write_mock_run(passed_dir, _evaluated_payload())
    assert Refiner().refine_from_run(_candidate(), passed_dir, _spec()).status == "needs_evaluation"
    assert Refiner().refine_from_run(_candidate(), tmp_path / "missing", _spec()).status == "needs_evaluation"


def test_fullchain_template_cannot_report_a_real_pass(tmp_path: Path) -> None:
    result = fullchain_eval({}, {}, tmp_path / "run", RunConfig(work_root=tmp_path, dry_run=False))
    assert result["status"] == "backend_unavailable"
    assert result["backend_status"] == "unavailable"
    assert result["pass"] is False
    assert result["not_lna_result"] is True and result["spec_pass"] is None

    dry = fullchain_eval({}, {}, tmp_path / "dry", RunConfig(work_root=tmp_path, dry_run=True))
    assert dry["status"] == "dry_run" and dry["backend_status"] == "unavailable"
    assert dry["not_lna_result"] is True and dry["spec_pass"] is None
