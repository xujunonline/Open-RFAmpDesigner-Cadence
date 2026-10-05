"""LLM policy: routes Manager/Refiner decisions through a ReAct exchange.

The model sees the paper's templates (Fig. 6) and must answer with

    <rationale>...</rationale><tools>{"action": ..., ...}</tools>

(A <think> tag is deliberately not requested: asking a model to print its reasoning
trips Claude's 'reasoning_extraction' safeguard, observed on Windows with Opus.)

The JSON is validated against the same action schema the rule policy uses;
anything invalid falls back to ``RulePolicy`` (counted as ``fallbacks``) so a
bad completion can never corrupt a run.  Transports:

* ``anthropic``  -- Claude Messages API (env ANTHROPIC_API_KEY, ORFADC_LLM_MODEL)
* ``openai``     -- any OpenAI-compatible endpoint (env OPENAI_API_KEY,
                    OPENAI_BASE_URL, ORFADC_LLM_MODEL) e.g. DeepSeek, Qwen, vLLM
* ``claude-cli`` -- Claude Code ``claude -p`` on a Claude Pro/Max subscription (``llm_cli.py``)
* ``codex-mcp``  -- MCP -> codex-bridge -> ``codex exec`` on a ChatGPT subscription
* ``scripted``   -- offline: replays the rule policy through the XML format so
                    the parsing/validation path is tested without network.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import Spec
from .agents import Candidate, RulePolicy

PROMPT_DIR = Path(__file__).with_name("prompts")
REFINE_ACTIONS = {"rerun_stage2", "rerun_stage3", "fail"}


def _prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    notional_cost_usd: float = 0.0   # list-price estimate reported by the CLI; subscriptions are not billed per call
    fallbacks: int = 0               # LLM answered (or the call failed) but the rule decision was used instead
    rule_after_disable: int = 0      # decisions made by the rule policy after the cap/circuit breaker tripped
    errors: int = 0
    latency_s: float = 0.0
    disabled_reason: str = ""


class AnthropicTransport:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("ORFADC_LLM_MODEL", "claude-sonnet-4-5")
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        body = json.dumps({"model": self.model, "max_tokens": 800, "system": system,
                           "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        return text, {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}


class OpenAICompatTransport:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("ORFADC_LLM_MODEL", "gpt-4o")
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        body = json.dumps({"model": self.model, "temperature": 0.2, "max_tokens": 800,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(f"{self.base}/chat/completions", data=body, headers={
            "authorization": f"Bearer {self.key}", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        u = data.get("usage", {})
        return data["choices"][0]["message"]["content"], {"prompt_tokens": u.get("prompt_tokens", 0),
                                                           "completion_tokens": u.get("completion_tokens", 0)}


class ScriptedTransport:
    """Offline stand-in: emits the rule policy's decision in ReAct XML."""

    def __init__(self) -> None:
        self.rule = RulePolicy()
        self.pending: dict | None = None

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        assert self.pending is not None, "ScriptedTransport needs a staged decision"
        d, self.pending = self.pending, None
        return f"<rationale>rule-derived decision</rationale><tools>{json.dumps(d)}</tools>", {"prompt_tokens": len(user) // 4,
                                                                                      "completion_tokens": 30}


def parse_tools(text: str) -> dict | None:
    m = re.search(r"<tools>\s*(\{.*?\})\s*</tools>", text, re.S)
    if not m:
        m = re.search(r"<answer>\s*(\{.*?\})\s*</answer>", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _valid_refine(a: dict | None) -> bool:
    if not isinstance(a, dict) or a.get("action") not in REFINE_ACTIONS:
        return False
    if a["action"] == "rerun_stage2":
        h = a.get("nf_headroom_db", 0.2)
        g = a.get("gain_require_db")
        return isinstance(h, (int, float)) and 0 <= h <= 3 and (g is None or (isinstance(g, (int, float)) and 0 < g < 45))
    if a["action"] == "rerun_stage3":
        req = a.get("gain_req_list")
        gu = a.get("gain_user_db")
        ok_req = req is None or (isinstance(req, list) and len(req) == 3
                                 and all(isinstance(x, (int, float)) or x is None for x in req))
        return ok_req and (gu is None or isinstance(gu, (int, float)))
    return True


def _valid_split(s: Any) -> bool:
    return (isinstance(s, list) and len(s) == 3 and all(isinstance(x, (int, float)) and 0.1 <= x <= 0.8 for x in s)
            and abs(sum(s) - 1.0) < 0.05)


@dataclass
class LLMPolicy(RulePolicy):
    transport: Any = None
    usage: Usage = field(default_factory=Usage)
    log: list[dict] = field(default_factory=list)
    name: str = "llm"

    def __post_init__(self) -> None:
        RulePolicy.__init__(self)
        self.transport = self.transport or AnthropicTransport()

    max_consecutive_errors: int = 3
    # read when the policy is created (not at import), so the env var can be changed per run;
    # 200 protects the subscription quota, paper-aligned runs use 1000 (docs/127)
    max_calls: int = field(default_factory=lambda: int(os.environ.get("ORFADC_LLM_MAX_CALLS", "200")))

    def _ask(self, role: str, user: str, staged: dict | None) -> dict | None:
        self._just_failed = False
        if not self.usage.disabled_reason and self.usage.calls >= self.max_calls:
            self.usage.disabled_reason = f"max_calls={self.max_calls} reached"
        if self.usage.disabled_reason:  # circuit breaker: quota/auth/network gone -> rule policy only
            return None
        if isinstance(self.transport, ScriptedTransport):
            self.transport.pending = staged
        t = time.perf_counter()
        try:
            text, u = self.transport.complete(_prompt(role), user)
        except Exception as exc:  # network/auth/quota failures fall back to the rule policy
            self.usage.errors += 1
            self._just_failed = True
            self._consecutive = getattr(self, "_consecutive", 0) + 1
            self.log.append({"role": role, "error": repr(exc)[:600]})
            if self._consecutive >= self.max_consecutive_errors:
                self.usage.disabled_reason = f"{self._consecutive} consecutive transport errors; last: {repr(exc)[:300]}"
            return None
        self._consecutive = 0
        self.usage.calls += 1
        self.usage.latency_s += time.perf_counter() - t
        self.usage.prompt_tokens += u.get("prompt_tokens", 0)
        self.usage.completion_tokens += u.get("completion_tokens", 0)
        self.usage.cached_prompt_tokens += u.get("cached_prompt_tokens", 0)
        self.usage.notional_cost_usd += float(u.get("notional_cost_usd", 0.0))
        act = parse_tools(text)
        self.log.append({"role": role, "response": text[-2000:], "parsed": act})
        return act

    def refine_action(self, spec: Spec, cand: Candidate, fc: dict, s3: dict, step: int) -> dict:
        rule = RulePolicy.refine_action(self, spec, cand, fc, s3, step)
        obs = {"spec": spec.__dict__, "candidate": cand.brief(), "step": step, "observation": {
            "sim_results": fc["sim_results_dict"], "violations": fc["violations"],
            "compression_stages": fc["compression_stages"], "stage_gain_hf_db_at_fc": s3.get("stage_gain_hf_db_at_fc"),
            "stage3_rounds": s3.get("rounds")}}
        user = ("Current candidate and the latest full-chain simulation are below. Choose ONE next action.\n"
                + json.dumps(obs, default=float))
        act = self._ask("refiner", user, rule)
        if act is None and self.usage.disabled_reason and not self._just_failed:
            self.usage.rule_after_disable += 1
            return rule
        if not _valid_refine(act):
            self.usage.fallbacks += 1
            return rule
        if act["action"] == "fail":
            act.setdefault("bottleneck", rule.get("bottleneck", "unknown"))
        return act

    def next_split(self, spec: Spec, tried: list[list[float]], bottleneck: str | None) -> list[float] | None:
        rule = RulePolicy.next_split(self, spec, tried, bottleneck)
        user = json.dumps({"spec": spec.__dict__, "tried_power_ratio_lists": tried, "last_bottleneck": bottleneck,
                           "instruction": "Propose the next power_ratio_list (3 ratios summing to 1, each 0.15..0.7) "
                                          "or {\"stop\": true}."})
        act = self._ask("manager", user, {"power_ratio_list": rule} if rule else {"stop": True})
        if act is None and self.usage.disabled_reason and not self._just_failed:
            self.usage.rule_after_disable += 1
            return rule
        if isinstance(act, dict) and act.get("stop"):
            return None
        s = act.get("power_ratio_list") if isinstance(act, dict) else None
        if not _valid_split(s) or any(all(abs(a - b) < 1e-3 for a, b in zip(s, t)) for t in tried):
            self.usage.fallbacks += 1
            return rule
        tot = sum(s)
        return [round(x / tot, 3) for x in s]


def make_policy(kind: str) -> RulePolicy:
    if kind == "rule":
        return RulePolicy()
    if kind == "scripted":
        return LLMPolicy(transport=ScriptedTransport(), name="llm-scripted")
    if kind == "anthropic":
        return LLMPolicy(transport=AnthropicTransport(), name="llm-anthropic")
    if kind == "openai":
        return LLMPolicy(transport=OpenAICompatTransport(), name="llm-openai")
    if kind == "claude-cli":  # Claude Pro/Max subscription via Claude Code headless mode
        from .llm_cli import ClaudeCLITransport
        return LLMPolicy(transport=ClaudeCLITransport(), name="llm-claude-cli")
    if kind == "codex-mcp":  # ChatGPT subscription via the codex-bridge MCP server
        from .llm_cli import CodexMCPTransport
        return LLMPolicy(transport=CodexMCPTransport(), name="llm-codex-mcp")
    raise ValueError(f"unknown policy {kind}")


POLICIES = ["rule", "scripted", "anthropic", "openai", "claude-cli", "codex-mcp"]
