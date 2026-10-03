from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from orfadc.agents.model_call_evidence import ModelCallEvidence, audit_model_calls
from orfadc.agents.executor import execute_manager, execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.llm_manager import LLMManagerPolicy
from orfadc.agents.llm_searcher import LLMSearcher
from orfadc.agents.llm_refiner import LLMRefiner
from orfadc.agents.manager import Manager
from orfadc.agents.openai_transport import OpenAIResponsesTransport
from orfadc.agents.searcher import Searcher
from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.schemas import Spec


@pytest.fixture
def trace_dir():
    with tempfile.TemporaryDirectory(prefix="model_calls_", dir=_PRIVATE_ROOT.resolve()) as directory:
        trace = Path(directory)
        (trace / "agent_events.jsonl").write_bytes(b'{"action":"RunStarted"}\n')
        yield trace


def _response():
    return SimpleNamespace(
        status="completed", output_text='{"action":"EvaluateCandidate"}',
        model="mock-model-1",
        usage=SimpleNamespace(
            input_tokens=120, output_tokens=30, total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=10),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )


def test_transport_persists_intent_before_fake_request_and_audits_result(trace_dir: Path) -> None:
    evidence = ModelCallEvidence(trace_dir, role="Manager")

    class FakeResponses:
        def create(self, **kwargs):
            assert len(list((trace_dir / "model_calls").glob("*.intent.json"))) == 1
            assert not list((trace_dir / "model_calls").glob("*.result.json"))
            return _response()

    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
    )
    assert transport.complete(system_prompt="private instructions", user_prompt="private circuit", timeout_seconds=5)
    report = audit_model_calls(trace_dir)
    assert report["attempts"] == report["completed"] == 1
    assert report["pending_call_ids"] == []
    assert report["pricing_counts_reported"] is True
    assert report["calls"][0]["role"] == "Manager"
    assert report["calls"][0]["event"]["cache_write_input_tokens"] == 10
    assert "private" not in json.dumps(report)
    (trace_dir / "agent_events.jsonl").write_bytes(
        b'{"action":"RunStarted"}\n{"action":"QueuePriority"}\n'
    )
    assert audit_model_calls(trace_dir)["completed"] == 1


def test_failed_fake_request_records_unknown_usage_not_exception_body(trace_dir: Path) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            raise RuntimeError("private server body")

    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1",
        usage_evidence=ModelCallEvidence(trace_dir, role="Searcher"),
    )
    with pytest.raises(RuntimeError, match="private server body"):
        transport.complete(system_prompt="private", user_prompt="private", timeout_seconds=5)
    report = audit_model_calls(trace_dir)
    assert report["attempts"] == report["completed"] == 1
    assert report["calls"][0]["event"]["outcome"] == "transport_error"
    assert report["calls"][0]["event"]["total_tokens"] is None
    assert report["pricing_counts_reported"] is False
    assert "private" not in json.dumps(report)


def test_result_is_write_once_for_the_same_call_id(trace_dir: Path) -> None:
    evidence = ModelCallEvidence(trace_dir, role="Manager")
    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=SimpleNamespace(create=lambda **_: _response())),
        model="mock-model-1", usage_evidence=evidence,
    )
    transport.complete(system_prompt="x", user_prompt="y", timeout_seconds=5)
    call = audit_model_calls(trace_dir)["calls"][0]
    with pytest.raises(FileExistsError):
        evidence.finish(call["call_id"], call["event"])
    assert audit_model_calls(trace_dir)["completed"] == 1


def test_intent_write_failure_prevents_model_request(trace_dir: Path) -> None:
    class FailingEvidence:
        def begin(self, model_requested):
            raise OSError("metadata disk unavailable")

    class FakeResponses:
        called = False

        def create(self, **kwargs):
            self.called = True
            return _response()

    responses = FakeResponses()
    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=responses), model="mock-model-1",
        usage_evidence=FailingEvidence(),
    )
    with pytest.raises(OSError, match="metadata disk unavailable"):
        transport.complete(system_prompt="x", user_prompt="y", timeout_seconds=5)
    assert responses.called is False


def test_interrupted_intent_is_explicitly_pending(trace_dir: Path) -> None:
    evidence = ModelCallEvidence(trace_dir, role="Refiner")
    empty_report = audit_model_calls(trace_dir)
    assert empty_report["attempts"] == 0
    assert empty_report["pricing_counts_reported"] is False
    call_id = evidence.begin("mock-model-1")
    report = audit_model_calls(trace_dir)
    assert report["attempts"] == 1
    assert report["completed"] == 0
    assert report["pending_call_ids"] == [call_id]
    assert report["pricing_counts_reported"] is False
    with pytest.raises(RuntimeError, match="unresolved model call"):
        evidence.begin("mock-model-1")
    assert len(list((trace_dir / "model_calls").glob("*.intent.json"))) == 1


def test_concurrent_begin_creates_at_most_one_unresolved_call(trace_dir: Path) -> None:
    evidence = ModelCallEvidence(trace_dir, role="Manager")
    barrier = Barrier(2)

    def attempt() -> tuple[str, str]:
        barrier.wait(timeout=5)
        try:
            return "started", evidence.begin("mock-model-1")
        except RuntimeError as exc:
            return "rejected", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [task.result(timeout=10) for task in [pool.submit(attempt) for _ in range(2)]]
    assert sorted(item[0] for item in outcomes) == ["rejected", "started"]
    report = audit_model_calls(trace_dir)
    assert report["attempts"] == 1
    assert report["pending_call_ids"] == [next(value for status, value in outcomes if status == "started")]


def test_missing_journal_prevents_model_dispatch(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Searcher")
    with pytest.raises(ValueError, match="journal"):
        evidence.begin("mock-model-1")
    assert not list((trace_dir / "model_calls").glob("*.intent.json"))


def test_malformed_journal_prevents_model_dispatch(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").write_bytes(b'{"action":')
    evidence = ModelCallEvidence(trace_dir, role="Searcher")
    with pytest.raises(ValueError, match="journal"):
        evidence.begin("mock-model-1")


def test_real_manager_executor_can_inject_audited_fake_model_before_run_started(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Manager")

    class FakeResponses:
        def create(self, **kwargs):
            assert (trace_dir / "agent_events.jsonl").is_file()
            payload = vars(_response())
            payload["output_text"] = '{"action":"EvaluateCandidate","candidate_id":"S1_seed0_search1"}'
            return SimpleNamespace(**payload)

    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
    )
    manager = Manager(
        Searcher([[0.4, 0.3, 0.3], [0.3, 0.4, 0.3]]),
        priority_policy=LLMManagerPolicy(transport), max_searches=1, max_evaluations=1,
    )
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    outcome = execute_manager(manager, spec, lambda _: trace_dir / "missing", trace_dir)
    assert outcome.status == "budget_exhausted"
    report = audit_model_calls(trace_dir)
    assert report["attempts"] == report["completed"] == 1
    assert report["calls"][0]["role"] == "Manager"
    assert any(event["action"] == "QueuePriority" and event["source"] == "model"
               for event in manager.trace)
    audit = inspect_journal(trace_dir)
    assert audit.model_call_bindings_verified is True
    assert audit.model_call_bindings == ((
        report["calls"][0]["call_id"], "S1_seed0_search1", None, "model",
    ),)
    with pytest.raises(RuntimeError, match="terminal agent journal"):
        evidence.begin("mock-model-1")


def test_terminal_journal_rejects_unreferenced_manager_intent(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Manager")
    manager = Manager(Searcher([[0.4, 0.3, 0.3]]), max_searches=1, max_evaluations=1)
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)

    def evaluator(_):
        evidence.begin("mock-model-1")
        return trace_dir / "missing"

    execute_manager(manager, spec, evaluator, trace_dir)
    with pytest.raises(ValueError, match="unbound Manager model call"):
        inspect_journal(trace_dir)


@pytest.mark.parametrize("mode,expected_action", [
    ("valid", "SearchCandidates"), ("invalid", "SearchFailed"),
    ("transport_error", "SearchFailed"), ("result_write_error", "SearchFailed"),
])
def test_searcher_model_call_binds_success_or_failure(
    trace_dir: Path, mode: str, expected_action: str,
) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Searcher")
    if mode == "result_write_error":
        def fail_finish(call_id, event):
            raise OSError("private local result write failure")

        evidence.finish = fail_finish

    class FakeResponses:
        def create(self, **kwargs):
            if mode == "transport_error":
                raise RuntimeError("private model error")
            payload = vars(_response())
            payload["output_text"] = (
                '{"tool":"active_sizing","arguments":'
                '{"power_ratio_list":[0.4,0.3,0.3],"total_current_ma":9}}'
                if mode in {"valid", "result_write_error"} else "invalid json"
            )
            return SimpleNamespace(**payload)

    searcher = LLMSearcher(OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
    ))
    manager = Manager(searcher, max_searches=1, max_evaluations=1)
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    outcome = execute_manager(manager, spec, lambda _: trace_dir / "missing", trace_dir)
    assert outcome.status == ("budget_exhausted" if mode == "valid" else "search_failed")
    report = audit_model_calls(trace_dir)
    audit = inspect_journal(trace_dir)
    assert audit.search_call_bindings_verified is True
    assert len(audit.search_call_bindings) == 1
    call_id, candidate_ids, action = audit.search_call_bindings[0]
    assert action == expected_action
    assert call_id in ({call["call_id"] for call in report["calls"]} | set(report["pending_call_ids"]))
    assert len(candidate_ids) == (1 if mode == "valid" else 0)
    assert audit.candidate_snapshots_verified is True
    if mode == "result_write_error":
        assert report["completed"] == 0 and report["pending_call_ids"] == [call_id]
    else:
        assert report["completed"] == 1
    if mode == "valid":
        events_path = trace_dir / "agent_events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        next(event for event in events if event["action"] == "SearchCandidates")["model_call_id"] = "0" * 32
        events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        with pytest.raises(ValueError, match="model call"):
            inspect_journal(trace_dir)


@pytest.mark.parametrize("mode,expected_status", [
    ("valid", "retry_stage3"), ("invalid", "retry_stage2"),
    ("transport_error", "retry_stage2"), ("result_write_error", "retry_stage2"),
])
def test_refiner_call_binds_mock_failure_candidate_and_run(
    trace_dir: Path, mode: str, expected_status: str,
) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Refiner")
    if mode == "result_write_error":
        def fail_finish(call_id, event):
            raise OSError("private local result write failure")

        evidence.finish = fail_finish

    class FakeResponses:
        def create(self, **kwargs):
            if mode == "transport_error":
                raise RuntimeError("private model failure")
            payload = vars(_response())
            payload["output_text"] = '{"action":"retry_stage3"}' if mode in {
                "valid", "result_write_error",
            } else "invalid json"
            return SimpleNamespace(**payload)

    refiner = LLMRefiner(OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
    ))
    manager = Manager(Searcher(), refiner=refiner, max_searches=1, max_evaluations=1)
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    observed: list[tuple[str, str]] = []

    def evaluator(candidate):
        run_dir = trace_dir / "mock_run"
        run_dir.mkdir()
        low, high = spec.band_edges_ghz
        payload = {
            "schema_version": 1, "status": "ok", "simulation_status": "ok",
            "source": "cadence_spectre", "circuit_class": "active_lna",
            "not_lna_result": False, "spec_pass": False, "run_id": run_dir.name,
            "analysis": ["dc", "sp", "noise", "compression"],
            "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
            "frequency_band_ghz": {"low": low, "high": high},
            "units": {"s11_db": "dB", "s21_db": "dB", "nf_db": "dB",
                      "ip1db_dbm": "dBm", "power_ma": "mA"},
            "metrics": {"s11_db": -15.0, "s21_db": 8.0, "nf_db": 4.0,
                        "ip1db_dbm": -10.0, "power_ma": 5.0},
            "spec": asdict(spec), "candidate": candidate.to_dict(), "seed": candidate.seed,
            "timeout_seconds": 300,
        }
        (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
        (run_dir / "candidate.json").write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
        (run_dir / "netlist.scs").write_text("simulator lang=spectre\n", encoding="utf-8")
        (run_dir / "spectre.log").write_text(
            "MOCK TEST FIXTURE ONLY\nspectre completes with 0 errors\n", encoding="utf-8",
        )
        write_evidence_manifest(run_dir, {
            "metrics": "metrics.json", "candidate": "candidate.json",
            "netlist": "netlist.scs", "spectre_log": "spectre.log",
        })
        observed.append((candidate.candidate_id, run_dir.name))
        return run_dir

    execute_manager(manager, spec, evaluator, trace_dir)
    assert len(observed) == 1, manager.trace
    report = audit_model_calls(trace_dir)
    audit = inspect_journal(trace_dir)
    assert audit.refiner_call_bindings_verified is True
    assert audit.refiner_call_bindings == ((
        report["calls"][0]["call_id"] if mode != "result_write_error" else report["pending_call_ids"][0],
        observed[0][0], observed[0][1], expected_status,
    ),)
    assert manager.trace[-2]["action"] == "RefineCandidate"
    assert manager.trace[-2]["status"] == expected_status
    assert report["completed"] == (0 if mode == "result_write_error" else 1)
    if mode == "valid":
        events_path = trace_dir / "agent_events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        next(event for event in events if event["action"] == "RefineCandidate")["model_call_id"] = "0" * 32
        events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        with pytest.raises(ValueError, match="model call"):
            inspect_journal(trace_dir)


def test_terminal_journal_rejects_unconsumed_refiner_intent(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Refiner")
    manager = Manager(Searcher(), max_searches=1, max_evaluations=1)

    def evaluator(_):
        evidence.begin("mock-model-1")
        raise RuntimeError("mock evaluator failure")

    execute_manager(manager, Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0), evaluator, trace_dir)
    with pytest.raises(ValueError, match="unbound Refiner model call"):
        inspect_journal(trace_dir)


@pytest.mark.parametrize("mode,expected_outcome", [
    ("valid", "completed"), ("invalid", "completed"),
    ("transport_error", "transport_error"), ("result_write_error", None),
])
def test_planned_manager_call_binds_candidate_and_run_id(
    trace_dir: Path, mode: str, expected_outcome: str | None,
) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Manager")
    if mode == "result_write_error":
        def fail_finish(call_id, event):
            raise OSError("local evidence result unavailable")

        evidence.finish = fail_finish

    class FakeResponses:
        def create(self, **kwargs):
            if mode == "transport_error":
                raise RuntimeError("private response failure")
            payload = vars(_response())
            payload["output_text"] = (
                '{"action":"EvaluateCandidate","candidate_id":"S1_seed0_search1"}'
                if mode in {"valid", "result_write_error"} else "invalid json"
            )
            return SimpleNamespace(**payload)

    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
    )
    manager = Manager(
        Searcher([[0.4, 0.3, 0.3], [0.3, 0.4, 0.3]]),
        priority_policy=LLMManagerPolicy(transport), max_searches=1, max_evaluations=1,
    )
    spec = Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)
    planned: list[tuple[str, str]] = []

    def evaluator(candidate, run_id):
        planned.append((candidate.candidate_id, run_id))
        return trace_dir / run_id

    execute_manager_planned(manager, spec, evaluator, trace_dir)
    assert len(planned) == 1
    expected_source = "model" if mode == "valid" else "fallback"
    expected_candidate = "S1_seed0_search1" if mode == "valid" else "S1_seed0_search0"
    assert planned[0][0] == expected_candidate
    report = audit_model_calls(trace_dir)
    audit = inspect_journal(trace_dir)
    assert audit.model_call_bindings_verified is True
    assert audit.model_call_bindings == ((
        report["calls"][0]["call_id"] if expected_outcome else report["pending_call_ids"][0],
        expected_candidate, planned[0][1], expected_source,
    ),)
    if expected_outcome is None:
        assert report["completed"] == 0 and len(report["pending_call_ids"]) == 1
    else:
        assert report["calls"][0]["event"]["outcome"] == expected_outcome


def test_manager_journal_rejects_wrong_model_call_reference(trace_dir: Path) -> None:
    (trace_dir / "agent_events.jsonl").unlink()
    evidence = ModelCallEvidence(trace_dir, role="Manager")

    class FakeResponses:
        def create(self, **kwargs):
            payload = vars(_response())
            payload["output_text"] = '{"action":"EvaluateCandidate","candidate_id":"S1_seed0_search1"}'
            return SimpleNamespace(**payload)

    manager = Manager(
        Searcher([[0.4, 0.3, 0.3], [0.3, 0.4, 0.3]]),
        priority_policy=LLMManagerPolicy(OpenAIResponsesTransport(
            SimpleNamespace(responses=FakeResponses()), model="mock-model-1", usage_evidence=evidence,
        )), max_searches=1, max_evaluations=1,
    )
    execute_manager(
        manager, Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0),
        lambda _: trace_dir / "missing", trace_dir,
    )
    events_path = trace_dir / "agent_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    priority = next(event for event in events if event["action"] == "QueuePriority")
    priority["model_call_id"] = "0" * 32
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    with pytest.raises(ValueError, match="model call"):
        inspect_journal(trace_dir)


@pytest.mark.parametrize("mutation", [
    "intent_hash", "event_text", "model", "journal_rewrite", "prefix_order",
    "bad_timestamp",
])
def test_audit_rejects_changed_source(trace_dir: Path, mutation: str) -> None:
    evidence = ModelCallEvidence(trace_dir, role="Manager")
    transport = OpenAIResponsesTransport(
        SimpleNamespace(responses=SimpleNamespace(create=lambda **_: _response())),
        model="mock-model-1", usage_evidence=evidence,
    )
    transport.complete(system_prompt="x", user_prompt="y", timeout_seconds=5)
    call_id = audit_model_calls(trace_dir)["calls"][0]["call_id"]
    result_path = trace_dir / "model_calls" / f"{call_id}.result.json"
    intent_path = trace_dir / "model_calls" / f"{call_id}.intent.json"
    if mutation == "intent_hash":
        payload = json.loads(intent_path.read_text(encoding="ascii"))
        payload["role"] = "Searcher"
        intent_path.write_text(json.dumps(payload), encoding="ascii")
    elif mutation == "journal_rewrite":
        (trace_dir / "agent_events.jsonl").write_bytes(b'{"action":"Stop"}\n')
    else:
        payload = json.loads(result_path.read_text(encoding="ascii"))
        if mutation == "event_text":
            payload["event"]["prompt"] = "injected"
        elif mutation == "prefix_order":
            import hashlib

            payload["agent_journal_sha256_after"] = hashlib.sha256(b"").hexdigest()
        elif mutation == "bad_timestamp":
            payload["completed_at_utc"] = "not a timestamp"
        else:
            payload["event"]["model_requested"] = "another-model"
        result_path.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(ValueError):
        audit_model_calls(trace_dir)


def test_external_trace_path_and_unknown_role_are_rejected(trace_dir: Path) -> None:
    with pytest.raises(ValueError, match="private"):
        ModelCallEvidence(Path.cwd(), role="Searcher")
    with pytest.raises(ValueError, match="role"):
        ModelCallEvidence(trace_dir, role="Simulator")
    with pytest.raises(ValueError, match="unavailable"):
        ModelCallEvidence(trace_dir / ".." / trace_dir.name, role="Searcher")
