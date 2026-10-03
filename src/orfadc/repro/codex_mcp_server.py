"""codex-bridge: MCP server that lets any MCP client use Codex with a ChatGPT subscription.

Codex CLI >= 0.154 no longer ships ``codex mcp-server``; this bridge restores an MCP
surface on top of ``codex exec`` (sign in once with ``codex login``; no API key).

Tools
  codex_ask(prompt, system="", model=None, timeout_s=300) -> {"ok", "text", "usage", "latency_s"}
  codex_status() -> login status text

Run:  python src/orfadc/repro/codex_mcp_server.py      (stdio; registered in .mcp.json as "codex")
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from mcp.server.fastmcp import FastMCP  # noqa: E402  (mcp 1.x API)
except ModuleNotFoundError as exc:  # mcp 2.x renamed FastMCP
    raise SystemExit("orfadc MCP servers need the mcp 1.x SDK: python -m pip install \"mcp>=1.2,<2\" "
                     f"(see config/requirements_repro.txt); import error: {exc}") from exc

from orfadc.repro.llm_cli import TransportError, codex_login_status, run_codex_exec  # noqa: E402

mcp = FastMCP("codex-bridge")


@mcp.tool()
def codex_ask(prompt: str, system: str = "", model: str | None = None, timeout_s: float = 300.0) -> str:
    """Ask Codex (ChatGPT subscription) one question; read-only, ephemeral, no tools executed.
    Returns JSON {ok, text, usage{input_tokens,cached_input_tokens,output_tokens}, latency_s} or {ok:false,error}."""
    try:
        r = run_codex_exec(prompt, system, model=model, timeout_s=timeout_s)
        return json.dumps({"ok": True, **r}, ensure_ascii=False)
    except TransportError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def codex_status() -> str:
    """Show `codex login status` (which account / plan the bridge will use)."""
    try:
        return codex_login_status()
    except TransportError as exc:
        return f"error: {exc}"


if __name__ == "__main__":
    mcp.run()
