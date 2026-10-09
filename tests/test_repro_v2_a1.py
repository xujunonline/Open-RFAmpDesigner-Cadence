"""docs/130 A1: stable design file names, v2 power-ratio range, Spectre cap on the cadence backend."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from orfadc.repro import backend_cadence as BC
from orfadc.repro import bench
from orfadc.repro import tools as T
from orfadc.repro.llm import V1_SPLIT_RANGE, V2_SPLIT_RANGE, _valid_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_repro_cadence_backend import SPECS, FakeRunner, _design  # noqa: E402


# ---------------------------------------------------------------------------
# 1. file naming
# ---------------------------------------------------------------------------

def test_default_settings_keep_v1_names():
    assert bench.design_suffix(backend="surrogate", env={}) == ""
    assert bench.design_suffix(backend="surrogate", llm=True, env={"ORFADC_LLM_MAX_CALLS": "200"}) == ""
    assert bench.design_suffix(backend="cadence", env={}) == "_cadence"
    # crn40lp PDK runs keep their v1 names (report-best is the pdk default)
    assert bench.design_suffix(backend="pdk", pdk="crn40lp", env={"ORFADC_REPORT_BEST": "1"}) == "_pdk"
    assert bench.design_suffix(backend="pdk", pdk=None, env={}) == "_pdk"


def test_non_default_settings_get_stable_suffixes():
    env = {"ORFADC_LLM_MAX_CALLS": "1000", "ORFADC_SPECTRE_MAX_PER_DESIGN": "60", "ORFADC_STAGE2_BACKOFF": "1",
           "ORFADC_BUDGET_SCALE": "1.5"}
    s = bench.design_suffix(backend="pdk", impl="v2", pdk="crn65lp", llm=True, env=env)
    assert s == "_pdk_n65_v2_b1.5x_calls1000_smax60_backoff"
    # the call cap only matters for LLM policies, the Spectre cap only for Spectre backends
    assert bench.design_suffix(backend="surrogate", llm=False, env=env) == "_b1.5x_backoff"
    assert bench.design_suffix(backend="surrogate", env={"ORFADC_REPORT_BEST": "1"}) == "_rb1"
    assert bench.design_suffix(backend="pdk", pdk="crn40lp", env={"ORFADC_REPORT_BEST": "0"}) == "_pdk_rb0"


def test_settings_never_share_a_file_name():
    envs = [{}, {"ORFADC_LLM_MAX_CALLS": "40"}, {"ORFADC_LLM_MAX_CALLS": "1000"}, {"ORFADC_STAGE2_BACKOFF": "1"},
            {"ORFADC_REPORT_BEST": "1"}, {"ORFADC_BUDGET_SCALE": "2"}]
    names = {bench.design_suffix(backend="surrogate", impl=i, llm=True, env=e) for i in ("v1", "v2") for e in envs}
    assert len(names) == 2 * len(envs)


def test_parse_design_name_roundtrip():
    n = bench.parse_design_name("design_S10s_seed3_mode1_claude-cli_v2_calls1000.json")
    assert n == {"spec": "S10s", "seed": 3, "mode": 1, "policy": "claude-cli", "suffix": "v2_calls1000"}
    assert bench.parse_design_name("design_S2_seed0_mode1_rule.json")["suffix"] == ""
    assert bench.parse_design_name("design_S2_seed0_mode1_rule_pdk_n65_b1.5x.json")["suffix"] == "pdk_n65_b1.5x"
    assert bench.parse_design_name("notes.json") is None


def test_pdk_label():
    assert bench.pdk_label(None) == "crn40lp" and bench.pdk_label({"name": "tsmc crn40lp"}) == "crn40lp"
    assert bench.pdk_label({"name": "CRN65LP"}) == "crn65lp"


def test_agent_impl_switch(monkeypatch):
    monkeypatch.delenv("ORFADC_AGENT_IMPL", raising=False)
    assert bench.agent_impl() == "v1"
    monkeypatch.setenv("ORFADC_AGENT_IMPL", "v2")
    assert bench.agent_impl() == "v2" and bench.agent_impl("v1") == "v1"
    with pytest.raises(ValueError):
        bench.agent_impl("v3")


def _fake_run(d: Path, name: str, success: bool, viol: float) -> None:
    (d / name).write_text(json.dumps({"spec": "S2", "seed": 0, "policy": "x", "success": success,
                                      "report": {"violations": {"gain": viol} if viol else {}}}), encoding="utf-8")


def test_llm_seeds_groups_suffixed_runs(tmp_path):
    _fake_run(tmp_path, "design_S2_seed0_mode1_rule.json", True, 0)
    _fake_run(tmp_path, "design_S2_seed0_mode1_rule_v2.json", False, 1.0)
    _fake_run(tmp_path, "design_S2_seed1_mode1_rule_v2.json", True, 0)
    _fake_run(tmp_path, "design_S2_seed0_mode1_rule_pdk_n65.json", True, 0)
    assert bench.cmd_llm_seeds(tmp_path, []) == 0
    md = (tmp_path / "llm_seeds.md").read_text(encoding="utf-8")
    assert "| S2 | rule | 1 | 1/1 |" in md
    assert "| S2 | rule[v2] | 2 | 1/2 |" in md
    assert "| S2 | rule[pdk_n65] | 1 | 1/1 |" in md


def test_llm_table_has_variant_column(tmp_path):
    _fake_run(tmp_path, "design_S2_seed0_mode1_rule_v2_calls40.json", True, 0)
    assert bench.cmd_llm_table(tmp_path) == 0
    assert "v2_calls40" in (tmp_path / "llm_table.csv").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. power-ratio range
# ---------------------------------------------------------------------------

def test_split_ranges():
    assert V1_SPLIT_RANGE == (0.1, 0.8) and V2_SPLIT_RANGE == (0.15, 0.7)
    edge = [0.12, 0.5, 0.38]
    assert _valid_split(edge)                       # v1 validation unchanged
    assert not _valid_split(edge, V2_SPLIT_RANGE)
    assert _valid_split([0.15, 0.15, 0.7], V2_SPLIT_RANGE)
    assert not _valid_split([0.1, 0.1, 0.8], V2_SPLIT_RANGE)


# ---------------------------------------------------------------------------
# 3. Spectre cap on --backend cadence
# ---------------------------------------------------------------------------

def test_cadence_backend_uncapped_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ORFADC_SPECTRE_MAX_PER_DESIGN", raising=False)
    be = BC.CadenceBackend(runner=FakeRunner(tmp_path / "remote", None), local_root=tmp_path / "local")
    assert be.max_calls is None


def test_cadence_backend_honours_spectre_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("ORFADC_SPECTRE_MAX_PER_DESIGN", "2")
    d = _design()
    final = BC.CadenceBackend(runner=FakeRunner(tmp_path / "remote", d), local_root=tmp_path / "local")
    assert final.max_calls == 2
    ctx = T.ToolContext(SPECS["S2"], backend=BC.HybridBackend(T.SurrogateBackend(), final))
    T.fullchain_evaluation(ctx, d)
    assert not ctx.counter.hard_stop
    T.fullchain_evaluation(ctx, d)
    assert final.n_calls == 2 and "2 calls per design" in ctx.counter.hard_stop
    with pytest.raises(T.BudgetExhausted):          # the design stops; no third Spectre run
        ctx.sim(d, np.array([d.fc_hz]), "hf", final=True)
    assert final.n_calls == 2
