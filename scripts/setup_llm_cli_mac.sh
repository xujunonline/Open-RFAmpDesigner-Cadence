#!/usr/bin/env bash
# macOS twin of setup_codex_cli.ps1 + the Claude half of docs/119 §6: subscription LLM CLIs for
# --policy claude-cli / codex-mcp (no API keys).  Run it yourself in a terminal; the logins open a browser.
#   scripts/setup_llm_cli_mac.sh            # install if missing, log in, show status
#   scripts/setup_llm_cli_mac.sh --check    # also run `bench llm-check` for both (1-2 LLM calls each)
# Installs into ~/.local/bin (no sudo, no Node.js): Claude Code with its official native installer,
# Codex CLI from the official GitHub release.  Codex uses CODEX_HOME=~/.codex-cli, as on Windows,
# so a Codex desktop app's ~/.codex/config.toml is never read or modified.
set -u
repo="$(cd "$(dirname "$0")/.." && pwd)"
bin="$HOME/.local/bin"
mkdir -p "$bin"
export PATH="$bin:$PATH"
unset ANTHROPIC_API_KEY OPENAI_API_KEY

echo "[1/4] Claude Code CLI"
if ! command -v claude >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash || { echo "Claude Code install failed" >&2; exit 1; }
fi
claude --version
if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  claude auth login --claudeai
fi
claude auth status | grep -E '"loggedIn"|"authMethod"|subscription' || true

echo "[2/4] Codex CLI"
if ! command -v codex >/dev/null 2>&1; then
  case "$(uname -m)" in
    arm64) triple=aarch64-apple-darwin ;;
    *) triple=x86_64-apple-darwin ;;
  esac
  tmp="$(mktemp -d)"
  url="https://github.com/openai/codex/releases/latest/download/codex-$triple.tar.gz"
  echo "downloading $url"
  curl -fL "$url" -o "$tmp/codex.tar.gz" && tar -xzf "$tmp/codex.tar.gz" -C "$tmp" || { echo "Codex download failed" >&2; exit 1; }
  install -m 0755 "$tmp/codex-$triple" "$bin/codex" || { echo "unexpected archive layout: $(ls "$tmp")" >&2; exit 1; }
fi
codex --version

echo "[3/4] Codex login (ChatGPT account, CODEX_HOME=~/.codex-cli)"
export CODEX_HOME="$HOME/.codex-cli"
mkdir -p "$CODEX_HOME"
codex login status >/dev/null 2>&1 || codex login
codex login status

echo "[4/4] Pipeline check"
if [ "${1:-}" = "--check" ]; then
  py="$repo/.venv/bin/python"; [ -x "$py" ] || py=python3
  cd "$repo" && export PYTHONPATH="$repo/src" PYTHONIOENCODING=utf-8
  "$py" -m orfadc.repro.bench llm-check --policy claude-cli --out results/windows_checks/llm_check_mac
  "$py" -m orfadc.repro.bench llm-check --policy codex-mcp --out results/windows_checks/llm_check_mac
else
  echo "skipped (pass --check to run bench llm-check for both CLIs)"
fi
