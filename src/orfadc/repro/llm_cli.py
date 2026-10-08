"""Subscription-quota LLM transports (no API key).

* ``ClaudeCLITransport`` -- Claude Code headless mode (``claude -p``) signed in with a
  Claude Pro/Max account; usage is drawn from the subscription.
* ``CodexMCPTransport``  -- talks MCP (stdio) to ``orfadc.repro.codex_mcp_server``,
  which wraps ``codex exec`` signed in with a ChatGPT account.  (Codex CLI removed its
  own ``codex mcp-server`` in 0.154, so the bridge provides the MCP surface.)
* ``run_codex_exec``     -- the non-interactive Codex call shared by the bridge.

All transports return ``(text, usage)`` like the HTTP transports in ``llm.py``.
Binaries can be overridden with ORFADC_CLAUDE_BIN / ORFADC_CODEX_BIN (tests use fakes).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Environment variables that would silently switch the CLIs from subscription to paid API billing.
_API_KEY_VARS = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
}


class TransportError(RuntimeError):
    """The CLI ran but did not produce a usable answer (auth, quota, network, timeout)."""


def _resolve(name: str, env_var: str) -> str:
    exe = os.environ.get(env_var)
    exe = os.path.abspath(exe) if exe else shutil.which(name)
    if not exe or not os.path.exists(exe):
        raise TransportError(f"'{name}' CLI not found on PATH (set {env_var} to its full path)")
    return exe


def _unshim(exe: str) -> list[str] | None:
    """npm on Windows installs ``name.cmd`` shims.  Running them goes through cmd.exe, which
    re-parses arguments (empty strings, quotes, non-ASCII temp paths).  Resolve the shim to
    the real target: ``node <script.js>`` or a native ``.exe``."""
    import re
    try:
        text = Path(exe).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    base = Path(exe).parent
    for m in re.finditer(r'"%(?:~?dp0)%\\?([^"%]+?\.(?:js|cjs|mjs|exe))"', text):
        target = (base / m.group(1).replace("\\", os.sep)).resolve()
        if target.exists():
            if target.suffix == ".exe":
                return [str(target)]
            node = shutil.which("node") or str(base / "node.exe")
            return [node, str(target)]
    return None


def _cmd(exe: str, args: list[str]) -> list[str]:
    # A fake CLI written in Python (tests) is started through the current interpreter.
    if exe.endswith(".py"):
        return [sys.executable, exe, *args]
    if exe.lower().endswith((".cmd", ".bat")):
        real = _unshim(exe)
        if real:
            return [*real, *args]
    return [exe, *args]


def codex_home() -> str | None:
    """Separate CLI home so the Codex desktop app's ~/.codex/config.toml (whose schema can
    differ from the CLI's) is never read or modified.  Priority: ORFADC_CODEX_HOME,
    an explicit CODEX_HOME, then ~/.codex-cli if it exists."""
    for key in ("ORFADC_CODEX_HOME", "CODEX_HOME"):
        if os.environ.get(key):
            return os.environ[key]
    alt = Path.home() / ".codex-cli"
    return str(alt) if alt.is_dir() else None


def _child_env(kind: str, keep_api_key: bool) -> dict:
    env = dict(os.environ)
    if not keep_api_key:
        for k in _API_KEY_VARS[kind]:
            env.pop(k, None)
    if kind == "codex" and codex_home():
        env["CODEX_HOME"] = codex_home()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


# ---------------------------------------------------------------------------
# Claude Code (Claude Pro/Max subscription)
# ---------------------------------------------------------------------------

class ClaudeCLITransport:
    """``claude -p`` with a replaced system prompt, no tools, no MCP, no settings.

    Do NOT add ``--bare``: bare mode ignores OAuth and would require an API key.
    """

    def __init__(self, model: str | None = None, timeout_s: float = 240.0, keep_api_key: bool = False) -> None:
        self.model = model or os.environ.get("ORFADC_CLAUDE_MODEL") or None
        self.timeout_s = timeout_s
        self.keep_api_key = keep_api_key
        self.exe = _resolve("claude", "ORFADC_CLAUDE_BIN")

    # Benign RF prompts occasionally trip a model's safeguard classifier (observed ~5 % of
    # calls on S9/S10); one retry on another model avoids losing that decision.
    retry_model = os.environ.get("ORFADC_CLAUDE_RETRY_MODEL", "opus")

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        try:
            return self._complete(system, user, self.model)
        except TransportError as exc:
            if "safeguards" in str(exc) and self.retry_model and self.retry_model != self.model:
                text, u = self._complete(system, user, self.retry_model)
                u["retried_with"] = self.retry_model
                return text, u
            raise

    def _complete(self, system: str, user: str, model: str | None) -> tuple[str, dict]:
        with tempfile.TemporaryDirectory(prefix="orfadc_claude_") as tmp:
            sp = Path(tmp) / "system.md"
            sp.write_text(system, encoding="utf-8")
            args = ["-p", "--output-format", "json", "--system-prompt-file", str(sp), "--tools", "",
                    "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                    "--max-turns", "1", "--setting-sources", ""]
            if model:
                args += ["--model", model]
            t = time.perf_counter()
            try:
                proc = subprocess.run(_cmd(self.exe, args), input=user, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=self.timeout_s, cwd=tmp,
                                      env=_child_env("claude", self.keep_api_key))
            except subprocess.TimeoutExpired as exc:
                raise TransportError(f"claude -p timed out after {self.timeout_s:.0f} s") from exc
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if proc.returncode != 0 or not data or data.get("is_error"):
            msg = data.get("result") or proc.stderr.strip() or proc.stdout.strip()
            raise TransportError(f"claude -p failed (rc={proc.returncode}): {msg[:400]}")
        u = data.get("usage", {})
        return str(data.get("result", "")), {
            "prompt_tokens": int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0))
            + int(u.get("cache_creation_input_tokens", 0)),
            "completion_tokens": int(u.get("output_tokens", 0)),
            "notional_cost_usd": float(data.get("total_cost_usd") or 0.0),  # list price; subscription is not billed per call
            "latency_s": time.perf_counter() - t,
            "backend": "claude-cli",
        }


# ---------------------------------------------------------------------------
# Codex (ChatGPT subscription)
# ---------------------------------------------------------------------------

def run_codex_exec(prompt: str, system: str = "", *, model: str | None = None, timeout_s: float = 300.0,
                   keep_api_key: bool = False) -> dict:
    """One non-interactive, read-only, ephemeral Codex turn in an empty temp directory."""
    exe = _resolve("codex", "ORFADC_CODEX_BIN")
    full = (f"# Role instructions\n{system.strip()}\n\n# Task\n{prompt.strip()}\n\n"
            "Do not run commands or edit files; answer directly in the required format.") if system else prompt
    with tempfile.TemporaryDirectory(prefix="orfadc_codex_") as tmp:
        last = Path(tmp) / "last_message.txt"
        args = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                "--color", "never", "-C", tmp, "-o", str(last)]
        if model:
            args += ["-m", model]
        args.append("-")
        t = time.perf_counter()
        try:
            proc = subprocess.run(_cmd(exe, args), input=full, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout_s, cwd=tmp, env=_child_env("codex", keep_api_key))
        except subprocess.TimeoutExpired as exc:
            raise TransportError(f"codex exec timed out after {timeout_s:.0f} s") from exc
        text = last.read_text(encoding="utf-8").strip() if last.exists() else ""
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    errors, thread_id = [], None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = ev.get("type")
        if typ == "thread.started":
            thread_id = ev.get("thread_id")
        elif typ == "turn.completed":
            for k in usage:
                usage[k] += int((ev.get("usage") or {}).get(k, 0))
        elif typ == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message" and not text:
            text = ev["item"].get("text", "")
        elif typ in ("turn.failed", "error"):
            errors.append((ev.get("error") or {}).get("message") or ev.get("message", ""))
    if not text:
        raise TransportError(f"codex exec returned no answer (rc={proc.returncode}): "
                             f"{(errors[-1] if errors else proc.stderr.strip())[:400]}")
    return {"text": text, "usage": usage, "latency_s": time.perf_counter() - t, "thread_id": thread_id,
            "returncode": proc.returncode}


def codex_login_status() -> str:
    exe = _resolve("codex", "ORFADC_CODEX_BIN")
    proc = subprocess.run(_cmd(exe, ["login", "status"]), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, env=_child_env("codex", False))
    return (proc.stdout + proc.stderr).strip()


# codex CLI errors where the request never reached the model (no answer, nothing decided): safe to retry the same call.
# Seen with codex-cli 0.162.0-alpha after a ChatGPT.app auto-update (docs/133 §6): "workspace routing discovery
# failed / timed out" for single calls, then fine again.
_CODEX_TRANSIENT = ("workspace routing discovery",)
CODEX_RETRY_DELAYS_S = (15.0, 30.0, 60.0)


def with_transient_retries(fn, delays=CODEX_RETRY_DELAYS_S, sleep=time.sleep, markers=_CODEX_TRANSIENT):
    """Call ``fn()``; on a TransportError whose text contains one of ``markers`` wait and retry (one retry per delay).
    Returns ``(result, retries)``; other errors and the last transient error propagate unchanged."""
    retries = 0
    while True:
        try:
            return fn(), retries
        except TransportError as exc:
            if retries >= len(delays) or not any(m in str(exc) for m in markers):
                raise
            sleep(delays[retries])
            retries += 1


class CodexMCPTransport:
    """MCP client (stdio) to the codex-bridge server; one persistent session per policy."""

    def __init__(self, model: str | None = None, timeout_s: float = 300.0, server_cmd: list[str] | None = None) -> None:
        self.model = model or os.environ.get("ORFADC_CODEX_MODEL") or None
        self.timeout_s = timeout_s
        self.server_cmd = server_cmd or [sys.executable, str(Path(__file__).with_name("codex_mcp_server.py"))]
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._session = None
        self._stack = None
        self._call(self._open())

    def _call(self, coro, timeout: float | None = None):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout or self.timeout_s + 60)

    async def _open(self) -> None:
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self.server_cmd[0], args=self.server_cmd[1:], env=dict(os.environ))
        r, w = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(r, w))
        await self._session.initialize()

    async def _ask(self, system: str, user: str) -> dict:
        args = {"prompt": user, "system": system, "timeout_s": self.timeout_s}
        if self.model:
            args["model"] = self.model
        res = await self._session.call_tool("codex_ask", args)
        payload = json.loads(res.content[0].text) if res.content else {}
        if res.isError or not payload.get("ok"):
            raise TransportError(f"codex bridge: {payload.get('error') or (res.content[0].text if res.content else '?')}")
        return payload

    def list_tools(self) -> list[str]:
        async def _lt():
            return [t.name for t in (await self._session.list_tools()).tools]
        return self._call(_lt(), 60)

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        p, retries = with_transient_retries(lambda: self._call(self._ask(system, user)))
        u = p.get("usage", {})
        out = {"prompt_tokens": int(u.get("input_tokens", 0)),
               "completion_tokens": int(u.get("output_tokens", 0)),
               "cached_prompt_tokens": int(u.get("cached_input_tokens", 0)),
               "latency_s": float(p.get("latency_s", 0.0)), "backend": "codex-mcp"}
        if retries:
            out["transient_retries"] = retries
        return p["text"], out

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._call(self._stack.aclose(), 30)
            except Exception:
                pass
            self._stack = None
        self._loop.call_soon_threadsafe(self._loop.stop)

    def __del__(self) -> None:  # best effort
        try:
            self.close()
        except Exception:
            pass
