from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orfadc.agents.manager import Manager
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec(id="S1", fc_ghz=10.0, fbw_ratio=0.2, power_ma=10.0,
                gain_db=10.0, nf_max_db=3.0, ip1db_min_dbm=-15.0)


def test_manager_search_evaluate_refine_stop_without_claiming_pass(tmp_path: Path) -> None:
    manager = Manager(max_searches=1, max_evaluations=1)
    assert manager.next_action() == "SearchCandidates"
    candidates = manager.search_candidates(_spec(), seed=0)
    assert len(candidates) == 1
    assert manager.next_action() == "EvaluateCandidate"
    candidate = manager.pop_candidate()
    assert manager.next_action() == "AwaitEvaluation"
    result = manager.record_result(candidate, tmp_path / "missing_run", _spec())
    assert result.status == "needs_evaluation"
    assert manager.next_action() == "Stop"
    assert [entry["action"] for entry in manager.trace] == [
        "SearchCandidates", "EvaluateCandidate", "RefineCandidate"
    ]
    assert manager.trace[-1]["status"] == "needs_evaluation"
    json.dumps(manager.trace)
    with pytest.raises(RuntimeError, match="evaluation slot"):
        manager.pop_candidate()


def test_manager_budget_and_duplicate_candidates() -> None:
    class DuplicateSearcher:
        def search(self, spec: Spec, seed: int) -> list[Candidate]:
            return [
                Candidate(candidate_id="same", spec_id=spec.id, seed=seed,
                          power_ratio_list=[0.4, 0.3, 0.3]),
                Candidate(candidate_id="same", spec_id=spec.id, seed=seed,
                          power_ratio_list=[0.4, 0.3, 0.3]),
            ]

    manager = Manager(searcher=DuplicateSearcher(), max_searches=2, max_evaluations=1)
    assert len(manager.search_candidates(_spec())) == 1
    assert manager.search_candidates(_spec()) == []
    assert manager.searches_used == 2
    assert len(manager.queue) == 1
    assert manager.search_candidates(_spec()) == []
    assert manager.pop_candidate().candidate_id == "same"
    assert manager.next_action() == "AwaitEvaluation"


def test_manager_rejects_wrong_context_and_invalid_budgets(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="budgets"):
        Manager(max_searches=True)
    with pytest.raises(ValueError, match="seed"):
        Manager().search_candidates(_spec(), seed=-1)
    manager = Manager()
    candidate = manager.search_candidates(_spec())[0]
    manager.pop_candidate()
    wrong = Candidate(candidate_id=candidate.candidate_id, spec_id="S1", seed=0,
                      power_ratio_list=[0.4, 0.3, 0.3])
    with pytest.raises(ValueError, match="awaiting"):
        manager.record_result(wrong, tmp_path, _spec())


def test_manager_rejects_searcher_context_mismatch() -> None:
    class InvalidSearcher:
        def search(self, spec: Spec, seed: int) -> list[Candidate]:
            return [Candidate(candidate_id="wrong", spec_id="S2", seed=seed,
                              power_ratio_list=[0.4, 0.3, 0.3])]

    manager = Manager(searcher=InvalidSearcher())
    with pytest.raises(ValueError, match="mismatched context"):
        manager.search_candidates(_spec())
    assert manager.searches_used == 0


def test_manager_binds_spec_and_seed_after_valid_search() -> None:
    manager = Manager(max_searches=2)
    manager.search_candidates(_spec(), seed=0)
    with pytest.raises(ValueError, match="mix spec/seed"):
        manager.search_candidates(_spec(), seed=1)
    with pytest.raises(ValueError, match="mix spec/seed"):
        manager.search_candidates(
            Spec(id="S2", fc_ghz=10.0, fbw_ratio=0.2, power_ma=10.0,
                 gain_db=10.0, nf_max_db=3.0, ip1db_min_dbm=-15.0),
            seed=0,
        )
    assert manager.searches_used == 1


def test_manager_rejects_non_list_searcher_output() -> None:
    class GeneratorSearcher:
        def search(self, spec: Spec, seed: int):
            yield Candidate(candidate_id="c1", spec_id=spec.id, seed=seed,
                            power_ratio_list=[0.4, 0.3, 0.3])

    manager = Manager(searcher=GeneratorSearcher())
    with pytest.raises(ValueError, match="candidate list"):
        manager.search_candidates(_spec())
    assert manager.searches_used == 0
    assert manager.context is None


def test_manager_trace_snapshot_is_exclusive_and_path_free(tmp_path: Path) -> None:
    manager = Manager()
    manager.search_candidates(_spec())
    candidate = manager.pop_candidate()
    manager.record_result(candidate, tmp_path / "missing", _spec())
    run_dir = tmp_path / "trace_run"
    run_dir.mkdir()
    path = manager.save_trace(run_dir)
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == 1
    assert snapshot["run_id"] is None
    assert snapshot["spec_id"] == "S1" and snapshot["seed"] == 0
    assert snapshot["next_action"] == "Stop"
    assert len(snapshot["events"]) == 3
    assert str(tmp_path) not in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        manager.save_trace(run_dir)


def test_manager_trace_run_id_requires_matching_evidence_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run001"
    run_dir.mkdir()
    payload = {
        "schema_version": 1, "status": "mkdir_failed", "simulation_status": "unknown",
        "circuit_class": "passive_twoport", "not_lna_result": True,
        "spec_pass": None, "run_id": "run001",
    }
    (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    write_evidence_manifest(run_dir, {"metrics": "metrics.json"})
    assert json.loads(Manager().save_trace(run_dir).read_text(encoding="utf-8"))["run_id"] == "run001"

    mismatched = tmp_path / "run002"
    mismatched.mkdir()
    (mismatched / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    write_evidence_manifest(mismatched, {"metrics": "metrics.json"})
    with pytest.raises(ValueError, match="run_id"):
        Manager().save_trace(mismatched)
    assert not (mismatched / "agent_trace.json").exists()


def test_manager_rejects_evidenced_run_for_changed_candidate_parameters(tmp_path: Path) -> None:
    spec = _spec()
    manager = Manager()
    manager.search_candidates(spec)
    candidate = manager.pop_candidate()
    run_dir = tmp_path / "run002"
    run_dir.mkdir()
    changed = candidate.to_dict()
    changed["power_ratio_list"] = [0.5, 0.25, 0.25]
    payload = {
        "schema_version": 1, "status": "mkdir_failed", "simulation_status": "unknown",
        "circuit_class": "active_lna", "not_lna_result": False,
        "spec_pass": None, "run_id": run_dir.name, "candidate": changed,
        "spec": asdict(spec), "seed": candidate.seed, "timeout_seconds": 60,
    }
    (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "candidate.json").write_text(json.dumps(changed), encoding="utf-8")
    write_evidence_manifest(run_dir, {"metrics": "metrics.json", "candidate": "candidate.json"})
    with pytest.raises(ValueError, match="does not match"):
        manager.record_result(candidate, run_dir, spec)
    assert candidate.candidate_id in manager.pending
    manager.record_evaluation_failure(candidate, "invalid_run_directory")
    assert manager.trace[-1]["action"] == "EvaluationFailed"


def test_manager_rejects_unsafe_candidate_id() -> None:
    class UnsafeSearcher:
        def search(self, spec: Spec, seed: int) -> list[Candidate]:
            return [Candidate(candidate_id="../escape", spec_id=spec.id, seed=seed,
                              power_ratio_list=[0.4, 0.3, 0.3])]

    with pytest.raises(ValueError, match="mismatched context"):
        Manager(searcher=UnsafeSearcher()).search_candidates(_spec())


def test_manager_journal_is_exclusive_and_requires_empty_trace(tmp_path: Path) -> None:
    manager = Manager()
    journal = manager.enable_journal(tmp_path)
    assert journal.name == "agent_events.jsonl"
    with pytest.raises(ValueError, match="before the first"):
        manager.enable_journal(tmp_path)
    manager.search_candidates(_spec())
    manager.close_journal()
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[0])["action"] == "SearchCandidates"
    with pytest.raises(ValueError, match="before the first"):
        manager.enable_journal(tmp_path)
