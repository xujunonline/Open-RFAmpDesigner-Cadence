from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

import orfadc.agents.memory as memory_module
from orfadc.agents.llm_searcher import LLMSearcher
from orfadc.agents.memory import VerifiedFailureKB, build_ladder_failure_fact
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.schemas import Spec


_REPORT = _PRIVATE_ROOT / "pdk_rf_ladder_fullchain" / "20260927T111305Z_1748e1d0"


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 30.0, 25.0, 5.0, -25.0)


def _fake_fact() -> dict:
    return {
        "schema_version": 1, "kind": "diagnostic_failure",
        "source_type": "pdk_rf_ladder_fullchain", "run_id": "safe_report",
        "evidence_manifest_sha256": "a" * 64,
        "spec": asdict(_spec()),
        "metrics": {"s11_db": -6.0, "s21_db": -18.0, "s22_db": -0.3,
                    "nf_db": 13.0, "ripple_db": 8.0, "ip1db_dbm": -20.0,
                    "power_ma": 10.0},
        "violations": {"s11_violation": 14.0, "gain_violation": 43.0,
                       "nf_violation": 8.0, "ip1db_violation": 0.0,
                       "power_violation": 0.0},
        "not_lna_result": True, "eligible_for_seed": False,
        "eligible_for_experience": False,
    }


class _Model:
    def __init__(self) -> None:
        self.user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str,
                 timeout_seconds: int) -> str:
        self.user_prompt = user_prompt
        return json.dumps({"tool": "active_sizing", "arguments": {
            "power_ratio_list": [0.4, 0.3, 0.3], "total_current_ma": 20.0,
        }})


def test_real_ladder_fact_requires_full_raw_archive_reaudit() -> None:
    if not _REPORT.is_dir():
        pytest.skip("private RF ladder fullchain source unavailable")
    fact = build_ladder_failure_fact(_REPORT)
    assert fact["kind"] == "diagnostic_failure"
    assert fact["run_id"] == _REPORT.name
    assert fact["eligible_for_seed"] is False
    assert fact["eligible_for_experience"] is False
    assert fact["violations"]["gain_violation"] > 40
    assert set(fact) == {
        "schema_version", "kind", "source_type", "run_id", "evidence_manifest_sha256",
        "spec", "metrics", "violations", "not_lna_result", "eligible_for_seed",
        "eligible_for_experience",
    }


def test_verified_kb_append_retrieve_and_reject_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "_MEMORY_ROOT", tmp_path)
    monkeypatch.setattr(memory_module, "build_ladder_failure_fact", lambda path: _fake_fact())
    kb = VerifiedFailureKB()
    kb.append_ladder_failure(Path("safe_report"))
    with pytest.raises(ValueError, match="already contains"):
        kb.append_ladder_failure(Path("safe_report"))
    assert kb.retrieve_failure_context(_spec()) == [{
        "source_run_id": "safe_report",
        "evidence_status": "verified_diagnostic_failure",
        "spec_id": "S1", "similarity": 1.0,
        "failed_constraints": ["s11", "gain", "nf"],
        "usable_as_successful_seed": False,
        "usable_as_experience": False,
    }]
    assert kb.retrieve_failure_context(Spec("S2", 30, 0.2, 30, 25, 5, -25)) == []


def test_verified_kb_rejects_modified_record_and_duplicate_json_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "_MEMORY_ROOT", tmp_path)
    monkeypatch.setattr(memory_module, "build_ladder_failure_fact", lambda path: _fake_fact())
    kb = VerifiedFailureKB()
    kb.append_ladder_failure(Path("safe_report"))
    record = json.loads(kb.path.read_text(encoding="utf-8"))
    record["metrics"]["s21_db"] = 30.0
    kb.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        kb.retrieve_failure_context(_spec())
    kb.path.write_text('{"run_id":"safe_report","run_id":"safe_report"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate keys"):
        kb.retrieve_failure_context(_spec())


def test_searcher_receives_only_failure_summary_not_private_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "_MEMORY_ROOT", tmp_path)
    monkeypatch.setattr(memory_module, "build_ladder_failure_fact", lambda path: _fake_fact())
    kb = VerifiedFailureKB()
    kb.append_ladder_failure(Path("safe_report"))
    model = _Model()
    candidate = LLMSearcher(model, memory=kb).search(_spec())[0]
    prompt = json.loads(model.user_prompt)
    assert prompt["diagnostic_failure_context"][0]["failed_constraints"] == ["s11", "gain", "nf"]
    assert "metrics" not in prompt["diagnostic_failure_context"][0]
    assert "netlist" not in model.user_prompt.lower()
    assert "model_paths" not in model.user_prompt.lower()
    assert candidate.status == "needs_verified_active_lookup"
    assert candidate.sim_result is None


def test_verified_kb_rejects_symlink_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_module, "_MEMORY_ROOT", tmp_path)
    target = tmp_path / "other.jsonl"
    target.write_text("", encoding="utf-8")
    try:
        (tmp_path / "kb.jsonl").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")
    with pytest.raises(ValueError, match="unsafe"):
        VerifiedFailureKB()
