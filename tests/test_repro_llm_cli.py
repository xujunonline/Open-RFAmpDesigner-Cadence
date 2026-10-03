"""Subscription transports (claude -p, codex via MCP bridge) against fake CLIs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orfadc.config_loader import load_specs
from orfadc.repro import agents as A
from orfadc.repro.llm import LLMPolicy
from orfadc.repro.llm_cli import ClaudeCLITransport, CodexMCPTransport, TransportError, run_codex_exec

ROOT = Path(__file__).resolve().parents[1]
FAKES = Path(__file__).with_name("fakes")
SPECS = {s.id: s for s in load_specs(ROOT / "config" / "specs_table_iii.yaml")}


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("ORFADC_CLAUDE_BIN", str(FAKES / "fake_claude.py"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-be-stripped")


@pytest.fixture
def fake_codex(monkeypatch):
    monkeypatch.setenv("ORFADC_CODEX_BIN", str(FAKES / "fake_codex.py"))


def test_claude_cli_transport_parses_result_and_usage(fake_claude):
    text, u = ClaudeCLITransport().complete("You are terse.", "Reply with exactly: OK")
    assert text == "OK" and u["prompt_tokens"] == 112 and u["completion_tokens"] == 20
    assert u["backend"] == "claude-cli"


def test_claude_cli_error_is_transport_error(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    with pytest.raises(TransportError, match="usage limit"):
        ClaudeCLITransport().complete("s", "u")


def test_codex_exec_parses_jsonl(fake_codex):
    r = run_codex_exec("Reply with exactly: OK", "terse")
    assert r["text"] == "OK" and r["usage"]["input_tokens"] == 900 and r["thread_id"] == "fake-thread"


def test_codex_mcp_bridge_end_to_end(fake_codex):
    tr = CodexMCPTransport()
    try:
        assert {"codex_ask", "codex_status"} <= set(tr.list_tools())
        text, u = tr.complete("You are RFAmpRefiner.", "decide")
        assert '"rerun_stage2"' in text and u["prompt_tokens"] == 900 and u["backend"] == "codex-mcp"
    finally:
        tr.close()


def test_codex_bridge_reports_quota_error(fake_codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    tr = CodexMCPTransport()
    try:
        with pytest.raises(TransportError, match="usage limit"):
            tr.complete("s", "u")
    finally:
        tr.close()


def test_llm_policy_with_claude_cli_runs_design_loop(fake_claude):
    pol = LLMPolicy(transport=ClaudeCLITransport(), name="llm-claude-cli")
    out = A.run_design(SPECS["S2"], 0, budget_equiv_s=1500.0, policy=pol)
    assert out["sims"]["hf_total"] > 0
    assert pol.usage.calls >= 1 and pol.usage.fallbacks == 0 and pol.usage.errors == 0


def test_circuit_breaker_falls_back_to_rules(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    pol = LLMPolicy(transport=ClaudeCLITransport(), name="llm-claude-cli")
    out = A.run_design(SPECS["S2"], 0, budget_equiv_s=3600.0, policy=pol)
    assert pol.usage.disabled_reason and pol.usage.errors == pol.max_consecutive_errors
    assert out["success"]  # rule fallback still solves S2
    assert pol.usage.fallbacks == pol.max_consecutive_errors and pol.usage.rule_after_disable > 0


def test_call_cap_counts_rule_decisions_separately(fake_claude):
    pol = LLMPolicy(transport=ClaudeCLITransport(), name="llm-claude-cli", max_calls=2)
    A.run_design(SPECS["S2"], 0, budget_equiv_s=3600.0, policy=pol)
    assert pol.usage.calls == 2 and pol.usage.disabled_reason.startswith("max_calls")
    assert pol.usage.fallbacks == 0 and pol.usage.rule_after_disable >= 1


def test_codex_bridge_registered_in_mcp_json():
    cfg = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert "codex" in cfg["mcpServers"] and "rfamp" in cfg["mcpServers"]
    from orfadc.repro import codex_mcp_server
    names = {t.name for t in asyncio.run(codex_mcp_server.mcp.list_tools())}
    assert names == {"codex_ask", "codex_status"}


def test_claude_cli_retries_safeguard_false_positive_on_other_model(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FLAG", "1")
    text, u = ClaudeCLITransport().complete("s", "Reply with exactly: OK")
    assert text == "OK" and u["retried_with"] == "opus"


def test_codex_home_isolated_from_desktop_app(monkeypatch, tmp_path):
    from orfadc.repro import llm_cli
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("ORFADC_CODEX_HOME", str(tmp_path / "cli-home"))
    assert llm_cli._child_env("codex", False)["CODEX_HOME"] == str(tmp_path / "cli-home")
