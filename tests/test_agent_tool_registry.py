from __future__ import annotations

import pytest

from orfadc.agents.searcher import Searcher
from orfadc.agents.tool_registry import AgentToolRegistry
from orfadc.schemas import Candidate, Spec


def _spec() -> Spec:
    return Spec(id="S1", fc_ghz=10, fbw_ratio=0.2, power_ma=10,
                gain_db=10, nf_max_db=3, ip1db_min_dbm=-15)


def _candidate() -> Candidate:
    return Candidate(candidate_id="S1_seed0_search0", spec_id="S1", seed=0,
                     power_ratio_list=[0.4, 0.3, 0.3], active_params={"stages": []})


def test_registry_exposes_only_four_paper_tools() -> None:
    assert AgentToolRegistry.tool_names() == (
        "active_sizing", "impedance_matching", "band_planning", "fullchain_eval",
    )


def test_active_sizing_is_budgeted_and_explicitly_unverified() -> None:
    result = AgentToolRegistry(_spec()).invoke({
        "tool": "active_sizing",
        "arguments": {"power_ratio_list": [0.4, 0.3, 0.3], "total_current_ma": 10},
    })
    assert result["status"] == "needs_verified_active_lookup"
    assert [item["current_ma"] for item in result["stages"]] == pytest.approx([4, 3, 3])
    assert result["not_lna_result"] is True and result["spec_pass"] is None
    assert all(item["lookup_status"] == "missing" for item in result["stages"])
    assert Searcher().search(_spec())[0].status == "needs_verified_active_lookup"


@pytest.mark.parametrize("tool_call", [
    {"tool": "shell", "arguments": {}},
    {"tool": [], "arguments": {}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [0.4, 0.3, 0.3],
                                           "total_current_ma": 10, "netlist": "bad"}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [0.4, 0.3, 0.3],
                                           "total_current_ma": 11}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [0.4, 0.3],
                                           "total_current_ma": 10}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [True, 0.3, 0.3],
                                           "total_current_ma": 10}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [0.4, 0.3, 0.3],
                                           "total_current_ma": float("nan")}},
    {"tool": "active_sizing", "arguments": {"power_ratio_list": [1e308, 1e308, 1e308],
                                           "total_current_ma": 10}},
])
def test_registry_rejects_unknown_tools_and_untrusted_parameters(tool_call: dict) -> None:
    with pytest.raises(ValueError):
        AgentToolRegistry(_spec()).invoke(tool_call)


def test_stage_tools_cannot_consume_llm_supplied_metrics_or_run_paths() -> None:
    registry = AgentToolRegistry(_spec())
    candidate = _candidate()
    for name, args in (
        ("impedance_matching", {"candidate_id": candidate.candidate_id, "nf_headroom_db": 0.2}),
        ("band_planning", {"candidate_id": candidate.candidate_id, "gain_require_list": [4, 3, 3]}),
        ("fullchain_eval", {"candidate_id": candidate.candidate_id}),
    ):
        result = registry.invoke({"tool": name, "arguments": args}, candidate=candidate)
        assert result["spec_pass"] is None
        assert result["not_lna_result"] is True
        assert "metrics" not in result and "stage2_cost" not in result
        with pytest.raises(ValueError, match="argument keys"):
            registry.invoke({"tool": name, "arguments": {**args, "s11_db": -100}}, candidate=candidate)
    with pytest.raises(ValueError, match="matching trusted candidate"):
        registry.invoke({"tool": "fullchain_eval", "arguments": {"candidate_id": "other"}}, candidate=candidate)


@pytest.mark.parametrize("headroom", [float("inf"), -0.1, 6.1, True])
def test_matching_policy_rejects_bad_headroom(headroom: object) -> None:
    candidate = _candidate()
    with pytest.raises(ValueError):
        AgentToolRegistry(_spec()).invoke({
            "tool": "impedance_matching",
            "arguments": {"candidate_id": candidate.candidate_id, "nf_headroom_db": headroom},
        }, candidate=candidate)
