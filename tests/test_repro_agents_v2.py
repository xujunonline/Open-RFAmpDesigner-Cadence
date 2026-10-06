"""docs/131: v2 ReAct agents, offline with the scripted transport (normal run, invalid actions,
budget exhaustion, LLM interruption, call cap) and the bench/MCP switches."""
from __future__ import annotations

import json

import pytest

from orfadc.repro import agents_v2 as V
from orfadc.repro import bench
from orfadc.repro.agents import DesignSession
from orfadc.repro.llm import V2_SPLIT_RANGE

SPECS = bench.specs()


def _run(script=None, budget=3600.0, spec="S2", **kw):
    return V.run_design_v2(SPECS[spec], 0, budget_equiv_s=budget, transport=V.ScriptedReActTransport(script), **kw)


@pytest.fixture(scope="module")
def s2_run():
    return _run()


def test_s2_end_to_end_scripted(s2_run):
    r = s2_run
    assert r["success"] and r["terminated_reason"] == "spec_met" and r["agent_impl"] == "v2"
    assert r["report"]["success"] and r["design"] is not None and r["sweep"] is not None
    u = r["llm_usage"]
    assert u["calls"] > 0 and u["errors"] == 0 and u["invalid_actions"] == 0
    assert u["fallbacks"] == 0 and u["rule_after_disable"] == 0
    assert set(u["calls_by_role"]) == {"manager", "searcher", "refiner"}
    assert r["n_search"] >= 1 and r["n_refine"] >= 1
    assert all(V2_SPLIT_RANGE[0] <= x <= V2_SPLIT_RANGE[1] for s in r["splits_tried"] for x in s)
    ev = [e for e in r["trace"] if e["event"] == "evaluate"]
    assert ev and ev[-1]["passed"]
    logged = [e for e in r["llm_log"] if "tool" in e]
    assert logged and all({"agent_step", "tool", "observation", "prompt_tokens"} <= set(e) for e in logged)


def test_invalid_actions_are_reported_and_retried():
    r = _run({"manager": ["no tools block here",
                          {"tool": "search_candidates", "args": {"power_ratio_list": [0.12, 0.5, 0.38]}}]}, budget=200)
    assert r["llm_usage"]["invalid_actions"] == 2
    assert r["terminated_reason"] != "invalid_actions" and r["n_search"] >= 1
    errs = [e for e in r["llm_log"] if e.get("tool") == "invalid"]
    assert len(errs) == 2 and "0.15" in errs[1]["observation"]


def test_three_consecutive_invalid_actions_terminate():
    bad = {"tool": "teleport", "args": {}}
    r = _run({"manager": [bad, bad, bad]})
    assert r["terminated_reason"] == "invalid_actions" and not r["success"]
    assert r["llm_usage"]["calls"] == 3 and r["sims"]["hf_total"] == 0


def test_eda_budget_terminates():
    r = _run(budget=60)
    assert r["terminated_reason"] == "eda_budget" and not r["success"]
    assert r["sims"]["equiv_time_s"] >= 60


def test_llm_interruption_terminates_without_rule_fallback():
    r = _run([RuntimeError("network down")] * 3)
    assert r["terminated_reason"] == "llm_unavailable"
    u = r["llm_usage"]
    assert u["errors"] == 3 and u["calls"] == 0 and u["fallbacks"] == 0 and r["sims"]["hf_total"] == 0


def test_llm_interruption_inside_a_sub_agent():
    r = _run({"refiner": [RuntimeError("quota")] * 3})
    assert r["terminated_reason"] == "llm_unavailable" and r["n_search"] >= 1 and r["n_refine"] == 1
    assert r["llm_usage"]["errors"] == 3


def test_llm_call_cap():
    r = _run(max_calls=5)
    assert r["terminated_reason"] == "llm_call_cap" and r["llm_usage"]["calls"] == 5
    assert r["llm_usage"]["disabled_reason"] == "max_calls=5 reached"


def test_prompts_and_validation_share_the_split_range():
    sess = DesignSession(SPECS["S2"])
    brain = V.Brain(V.ScriptedReActTransport())
    mgr = V.ManagerAgent(sess, brain)
    text = mgr.system_prompt()
    assert "0.15..0.7" in text and "{SPLIT_LO}" not in text and "`search_candidates`" in text
    with pytest.raises(V.ActionError, match="0.15"):
        mgr.validate({"tool": "search_candidates", "args": {"power_ratio_list": [0.1, 0.1, 0.8]}})
    with pytest.raises(V.ActionError, match="unknown argument"):
        mgr.validate({"tool": "finish", "args": {"why": "x"}})
    assert mgr.validate({"tool": "search_candidates", "args": {"power_ratio_list": [0.15, 0.15, 0.7]}})[0] == "search_candidates"
    srch = V.SearcherAgent(sess, brain, {}, tried_before=[], splits_log=[])
    assert "0.15..0.7" in srch.system_prompt() and "## Protocol" in srch.system_prompt()


def test_searcher_and_refiner_guard_their_tools():
    sess = DesignSession(SPECS["S2"])
    brain = V.Brain(V.ScriptedReActTransport())
    srch = V.SearcherAgent(sess, brain, {"power_ratio_list": [0.4, 0.3, 0.3]}, tried_before=[[0.35, 0.15, 0.5]],
                           splits_log=[])
    with pytest.raises(V.ActionError, match="active_sizing"):
        srch.t_impedance_matching([0.4, 0.3, 0.3], "crit_large__noncrit_large")
    with pytest.raises(V.ActionError, match="already searched"):
        srch.t_active_sizing([0.35, 0.15, 0.5])
    srch.t_active_sizing([0.4, 0.3, 0.3])
    with pytest.raises(V.ActionError, match="not in"):
        srch.t_impedance_matching([0.4, 0.3, 0.3], "nope")
    c = srch.t_impedance_matching([0.4, 0.3, 0.3], "crit_large__noncrit_large")["cid"]
    with pytest.raises(V.ActionError, match="unknown candidate"):
        srch.t_finish(["C999"])
    ref = V.RefinerAgent(sess, brain, c)
    with pytest.raises(V.ActionError, match="not planned"):
        ref.t_fullchain("D999")
    did = ref.t_band_planning()["did"]
    fc = ref.t_fullchain(did)
    if not fc["pass"]:
        with pytest.raises(V.ActionError, match="success=true"):
            ref.t_finish(True, did)
    rep = ref.t_finish(fc["pass"], did)["report"]
    assert rep["did"] == did and ref.terminated == "finish"


def test_mode2_memory_records_are_labelled(tmp_path):
    r = V.run_design_v2(SPECS["S2"], 0, mode=2, memory_dir=tmp_path, budget_equiv_s=3600,
                        transport=V.ScriptedReActTransport(), pdk=None)
    assert r["success"]                                   # KB retrieval only preloads passing designs
    kb = [json.loads(x) for x in (tmp_path / "kb.jsonl").read_text(encoding="utf-8").splitlines()]
    eb = [json.loads(x) for x in (tmp_path / "eb.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kb and eb and all(x["agent_impl"] == "v2" and x["pdk"] is None for x in kb + eb)
    # the second run preloads from the KB the first one wrote
    r2 = V.run_design_v2(SPECS["S2"], 1, mode=2, memory_dir=tmp_path, budget_equiv_s=600,
                         transport=V.ScriptedReActTransport())
    assert any(e["event"] == "kb_preload" for e in r2["trace"]) and r["agent_impl"] == "v2"


def test_memory_dirs_are_separate():
    names = {bench.default_memory_dir(i, p).name for i in ("v1", "v2") for p in (None, "crn40lp", "crn65lp")}
    assert names == {"repro", "repro_v2", "repro_n65", "repro_v2_n65"}


def test_bench_design_v2_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("ORFADC_AGENT_IMPL", raising=False)
    monkeypatch.setenv("ORFADC_BUDGET_SCALE", "0.2")
    rc = bench.main(["design", "--spec", "S2", "--policy", "scripted", "--agent-impl", "v2", "--out", str(tmp_path)])
    assert rc in (0, 3)
    f = tmp_path / "design_S2_seed0_mode1_scripted_v2_b0.2x.json"
    r = json.loads(f.read_text(encoding="utf-8"))
    assert r["labels"]["agent_impl"] == "v2" and r["agent_impl"] == "v2" and r["terminated_reason"]
    assert r["run_settings"]["llm_max_calls"] == 200 and r["llm_usage"]["calls"] > 0
    with pytest.raises(SystemExit):
        bench.main(["design", "--spec", "S2", "--policy", "rule", "--agent-impl", "v2", "--out", str(tmp_path)])
    monkeypatch.setenv("ORFADC_AGENT_IMPL", "v2")
    with pytest.raises(SystemExit):
        bench.main(["design", "--spec", "S2", "--policy", "rule", "--out", str(tmp_path)])


def test_band_planning_accepts_null_gain_requests():
    """A3 S9s crash: the validator allows null entries in gain_req_list ("null = unconstrained"), so Stage 3
    must skip them instead of failing on float - None."""
    from orfadc.repro import tools as T
    assert T.gain_req_penalty([10.0, 12.0], None) == 0.0
    assert T.gain_req_penalty([10.0, 12.0], [5.0, 8.0, 12.0]) == pytest.approx(0.5)
    assert T.gain_req_penalty([10.0, 12.0], [None, None, 15.0]) == pytest.approx(1.5)
    assert T.gain_req_penalty([10.0, 12.0], [None, None, None]) == 0.0
    sess = DesignSession(SPECS["S2"])
    brain = V.Brain(V.ScriptedReActTransport())
    srch = V.SearcherAgent(sess, brain, {"power_ratio_list": [0.4, 0.3, 0.3]}, tried_before=[], splits_log=[])
    srch.t_active_sizing([0.4, 0.3, 0.3])
    c = srch.t_impedance_matching([0.4, 0.3, 0.3], "crit_large__noncrit_large")["cid"]
    ref = V.RefinerAgent(sess, brain, c)
    assert V.KINDS["gain_list?"][0]([None, 8.0, None])
    assert ref.t_band_planning(gain_user_db=25.0, gain_req_list=[None, 8.0, None])["did"]
