"""Offline tests for the surrogate reproduction pipeline (orfadc.repro)."""
from __future__ import annotations

import asyncio
import math
from pathlib import Path

import numpy as np
import pytest

from orfadc.config_loader import load_specs
from orfadc.repro import agents as A
from orfadc.repro import tools as T
from orfadc.repro import twoport as tp
from orfadc.repro.llm import LLMPolicy, ScriptedTransport, _valid_refine, parse_tools
from orfadc.repro.mcr_eq3 import eq3_voltage
from orfadc.repro.memory import MemoryStore
from orfadc.tools.mcr_lumped import lumped_mcr_response, symmetric_parallel_mcr

ROOT = Path(__file__).resolve().parents[1]
SPECS = {s.id: s for s in load_specs(ROOT / "config" / "specs_table_iii.yaml")}


# --------------------------------------------------------------- Eq. (3)
@pytest.mark.parametrize("k,q,f0", [(0.3, 2.0, 30e9), (0.6, 5.0, 10e9), (0.15, 0.8, 50e9)])
def test_eq3_corrected_y11_z21_match_nodal_model(k, q, f0):
    """The derived Y11 denominator (with the missing 's') equals nodal analysis."""
    w0 = 2 * math.pi * f0
    c = 100e-15
    model = symmetric_parallel_mcr(w0, q, c, k)
    for f in (0.7 * f0, f0, 1.3 * f0):
        ref = lumped_mcr_response(f, model)
        out = eq3_voltage(np.array([f]), k=k, w0=w0, q0=q, c_f=c, gm50_s=0.05, rs_drv_ohm=300, cs_drv_f=20e-15)
        assert out["y11"][0] == pytest.approx(ref.input_admittance_s, rel=1e-9)
        assert out["z21"][0] == pytest.approx(ref.transfer_impedance_ohm, rel=1e-9)


def test_eq3_printed_form_is_not_the_nodal_admittance():
    w0 = 2 * math.pi * 30e9
    model = symmetric_parallel_mcr(w0, 2.0, 100e-15, 0.3)
    ref = lumped_mcr_response(30e9, model).input_admittance_s
    printed = eq3_voltage(np.array([30e9]), k=0.3, w0=w0, q0=2.0, c_f=100e-15, gm50_s=0.05, rs_drv_ohm=300,
                          cs_drv_f=20e-15, variant="printed")["y11"][0]
    assert abs(printed - ref) / abs(ref) > 0.5


# --------------------------------------------------------------- two-port engine
def test_series_resistor_noise_figure_and_gain():
    blk = tp.series(np.full(2, 50.0 + 0j))
    assert np.allclose(blk.noise_factor(50.0), 2.0)
    # 50 ohm source, 50 ohm series, 50 ohm load: 2*Vl/Vs = 2*50/150
    assert np.allclose(np.abs(blk.voltage_gain(50.0, 50.0)), 2 / 3)


def test_cascade_obeys_friis_for_matched_attenuators():
    # two identical matched 3 dB-ish pi attenuators built from Y parameters
    r1, r2 = 292.4, 17.6  # ~3 dB matched pi pad (50 ohm)
    y = np.array([[1 / r1 + 1 / r2, -1 / r2], [-1 / r2, 1 / r1 + 1 / r2]], dtype=complex)[None]
    pad = tp.passive_y(y)
    g_av = 1 / pad.noise_factor(50.0)[0]  # passive: F = 1/G_av
    both = pad @ pad
    friis = pad.noise_factor(50.0)[0] + (pad.noise_factor(50.0)[0] - 1) / g_av
    assert both.noise_factor(50.0)[0] == pytest.approx(friis, rel=2e-2)


# --------------------------------------------------------------- tools
def test_active_sizing_four_configs_within_budget():
    out = T.active_sizing([0.4, 0.3, 0.3], 30.0)
    assert out["status"] == "ok" and len(out["active_params_dict_list"]) == 4
    for cfg in out["active_params_dict_list"]:
        total = sum(s["stage_current_ma"] for s in cfg["stages"])
        assert total <= 30.0 * 1.001
        assert cfg["stages"][0]["kind"] == "cascode" and cfg["stages"][1]["kind"] == "diff"


def test_l_match_gives_deep_s11():
    zin = complex(12.0, -40.0)
    w = 2 * math.pi * 30e9
    lg, lpar, ok = T.l_match(zin, w)
    assert ok
    z = zin + 1j * w * lg
    y = 1 / z + 1 / (1j * w * lpar)
    g = (1 / y - 50) / (1 / y + 50)
    assert 20 * math.log10(abs(g)) < -40


def test_stage2_and_stage3_tools_return_paper_schema():
    ctx = T.ToolContext(SPECS["S2"])
    cfg = T.active_sizing([0.4, 0.3, 0.3], 30.0)["active_params_dict_list"][0]
    s2 = T.impedance_matching(ctx, cfg, iters=3, n_particles=4)
    assert {"passive_params_cpstages", "sim_result_cpstages", "stage2_cost"} <= set(s2)
    assert set(T.STAGE2_BOUNDS) <= set(s2["passive_params_cpstages"])
    s3 = T.band_planning(ctx, cfg, s2, sa_iters=80, max_rounds=2)
    assert {"passive_params_dict", "cal_gain_dict"} <= set(s3)
    fc = T.fullchain_evaluation(ctx, s3["_design"])
    assert set(fc["spec_check"]["violations"]) == {"gain", "ripple", "nf", "ip1db", "s11", "power"}
    assert fc["not_silicon_result"] is True
    assert ctx.counter.hf_total > 0 and ctx.counter.lf > 0


def test_budget_exhaustion_is_enforced():
    ctx = T.ToolContext(SPECS["S2"])
    ctx.counter.budget_equiv_s = 5.0
    cfg = T.active_sizing([0.4, 0.3, 0.3], 30.0)["active_params_dict_list"][0]
    with pytest.raises(T.BudgetExhausted):
        T.impedance_matching(ctx, cfg)


# --------------------------------------------------------------- agents / memory / LLM path
def test_rule_agent_solves_s2_and_writes_memory(tmp_path):
    out = A.run_design(SPECS["S2"], 0, memory_dir=tmp_path, budget_equiv_s=3600.0)
    assert out["success"], out["report"]
    assert out["report"]["metrics"]["power_ma"] <= 30.0
    kb, eb = MemoryStore(tmp_path).n_records()
    assert kb >= 1 and eb >= 1
    hint = MemoryStore(tmp_path).insights(SPECS["S2"])
    assert hint["n_pass"] >= 1 and "nf_headroom_db" in hint


def test_scripted_llm_policy_matches_rule_policy():
    rule = A.run_design(SPECS["S2"], 0, budget_equiv_s=3600.0)
    pol = LLMPolicy(transport=ScriptedTransport(), name="llm-scripted")
    llm = A.run_design(SPECS["S2"], 0, budget_equiv_s=3600.0, policy=pol)
    assert llm["success"] == rule["success"]
    assert llm["sims"]["hf_total"] == rule["sims"]["hf_total"]
    assert pol.usage.fallbacks == 0


def test_llm_output_validation():
    assert parse_tools('<think>x</think><tools>{"action":"fail","bottleneck":"nf"}</tools>')["action"] == "fail"
    assert parse_tools("no xml here") is None
    assert not _valid_refine({"action": "rm -rf"})
    assert not _valid_refine({"action": "rerun_stage2", "nf_headroom_db": 99})
    assert _valid_refine({"action": "rerun_stage3", "gain_req_list": [3.0, 8.0, 14.0]})


def test_mcp_server_registers_table_i_tools():
    from orfadc.repro import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"active_sizing", "impedance_matching", "band_planning", "fullchain_evaluation"} <= names
