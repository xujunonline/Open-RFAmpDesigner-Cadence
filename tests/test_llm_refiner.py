from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents.llm_refiner import LLMRefiner
import orfadc.agents.llm_refiner as refiner_module
from orfadc.agents.manager import Manager
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.schemas import Candidate, Spec


class FakeModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def _candidate() -> Candidate:
    return Candidate("S1_seed0_c0", "S1", 0, [0.4, 0.3, 0.3])


def _failed_payload(candidate: Candidate, spec: Spec, *, run_id: str = "mock_run") -> dict:
    low, high = spec.band_edges_ghz
    return {
        "schema_version": 1, "status": "ok", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "active_lna",
        "not_lna_result": False, "spec_pass": False, "run_id": run_id,
        "analysis": ["dc", "sp", "noise", "compression"],
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        "frequency_band_ghz": {"low": low, "high": high},
        "units": {"s11_db": "dB", "s21_db": "dB", "nf_db": "dB",
                  "ip1db_dbm": "dBm", "power_ma": "mA"},
        "metrics": {"s11_db": -15.0, "s21_db": 8.0, "nf_db": 4.0,
                    "ip1db_dbm": -10.0, "power_ma": 5.0},
        "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
        "timeout_seconds": 300, "private_netlist_path": "never-send-to-model",
    }


def test_model_chooses_only_from_recomputed_failures_without_raw_data() -> None:
    model = FakeModel('{"action":"retry_stage3"}')
    candidate, spec = _candidate(), _spec()
    candidate.active_params["private_data"] = "never-send-to-model"
    payload = _failed_payload(candidate, spec)
    payload["total_violation"] = 0.0
    refined = LLMRefiner(model, timeout_seconds=7).refine(candidate, payload, spec)
    assert refined.status == "retry_stage3"
    prompt = json.loads(model.calls[0]["user_prompt"])
    assert prompt["allowed_actions"] == ["retry_stage2", "retry_stage3"]
    assert prompt["violations"]["nf_violation"] == 1.0
    assert prompt["violations"]["gain_violation"] == 2.0
    assert "never-send-to-model" not in model.calls[0]["user_prompt"]
    assert model.calls[0]["timeout_seconds"] == 7
    assert refined.sim_result is None


@pytest.mark.parametrize("response", [
    '{"action":"accepted"}', '{"action":"retry_stage1"}',
    '{"action":"retry_stage3","spec_pass":true}',
    '{"action":"retry_stage3","action":"retry_stage3"}',
    '```json\n{"action":"retry_stage3"}\n```',
    '{"action":NaN}', None, " " * 1025, TimeoutError("offline"),
])
def test_invalid_model_decision_falls_back_to_deterministic_rule(response: object) -> None:
    model = FakeModel(response)
    result = LLMRefiner(model).refine(_candidate(), _failed_payload(_candidate(), _spec()), _spec())
    assert result.status == "retry_stage2"
    assert result.notes[0] == "Model refinement unavailable or invalid; deterministic rule used."
    assert len(model.calls) == 1


def test_incomplete_or_nonfailing_result_never_reaches_model() -> None:
    model = FakeModel('{"action":"retry_stage2"}')
    refiner = LLMRefiner(model)
    candidate, spec = _candidate(), _spec()
    incomplete = _failed_payload(candidate, spec)
    incomplete["analysis"].remove("compression")
    assert refiner.refine(candidate, incomplete, spec).status == "needs_evaluation"
    passing = _failed_payload(_candidate(), spec)
    passing["metrics"].update(nf_db=2.0, s21_db=15.0)
    assert refiner.refine(_candidate(), passing, spec).status == "needs_evaluation"
    assert model.calls == []


def test_prompt_read_failure_does_not_reuse_prior_model_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PriorCallModel:
        def last_call_id(self) -> str:
            return "b" * 32

        def complete(self, **kwargs) -> str:
            raise AssertionError("request must not be sent")

    monkeypatch.setattr(refiner_module, "_PROMPT_PATH", tmp_path / "missing_prompt.md")
    candidate, spec = _candidate(), _spec()
    refiner = LLMRefiner(PriorCallModel())
    assert refiner.refine(candidate, _failed_payload(candidate, spec), spec).status == "retry_stage2"
    assert refiner.last_call_id() is None


def test_manager_injects_model_refiner_for_mock_failure_only(tmp_path: Path) -> None:
    model = FakeModel('{"action":"retry_stage3"}')
    spec = _spec()
    manager = Manager(refiner=LLMRefiner(model), max_searches=1, max_evaluations=1)
    candidate = manager.search_candidates(spec)[0]
    assert manager.pop_candidate() is candidate
    run_dir = tmp_path / "mock_run"
    run_dir.mkdir()
    payload = _failed_payload(candidate, spec)
    (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "candidate.json").write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
    (run_dir / "netlist.scs").write_text("simulator lang=spectre\n", encoding="utf-8")
    (run_dir / "spectre.log").write_text("spectre completes with 0 errors\n", encoding="utf-8")
    write_evidence_manifest(run_dir, {
        "metrics": "metrics.json", "candidate": "candidate.json",
        "netlist": "netlist.scs", "spectre_log": "spectre.log",
    })
    assert manager.record_result(candidate, run_dir, spec).status == "retry_stage3"
    assert manager.trace[-1]["action"] == "RefineCandidate"
    assert manager.trace[-1]["status"] == "retry_stage3"
    assert manager.next_action() == "Stop"
    assert len(model.calls) == 1


def test_actual_diagnostic_archive_is_not_fullchain_model_input() -> None:
    run_dir = (_PRIVATE_ROOT / "S1" / "seed0" / "S1_seed0_oa_diag" / "20260927T010857Z_d04f3583")
    if not run_dir.is_dir():
        pytest.skip("private diagnostic Cadence archive is unavailable")
    payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    model = FakeModel('{"action":"retry_stage2"}')
    candidate = Candidate(**payload["candidate"])
    result = LLMRefiner(model).refine_from_run(candidate, run_dir, Spec(**payload["spec"]))
    assert result.status == "needs_evaluation"
    assert model.calls == []
