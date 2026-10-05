"""PreToolUse hook for Bash.

- Blocks commands that would read or print secrets (exit 2).
- Asks for confirmation before anything that reaches the remote Cadence VM or Spectre
  (ssh/scp, `bench cadence-check`, `bench pdk-*`, `--backend cadence|pdk`), so live
  remote runs only happen on an explicit user request (CLAUDE.md rule 2).
"""
import json
import re
import sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")
except Exception:
    sys.exit(0)

BLOCK = [
    (r"remote_cadence\.local\.yaml|model_paths\.local\.yaml", "secret config files must not be read or printed"),
    (r"(cat|type|Get-Content)\s+[^|]*\.(pem|key)\b|id_rsa|id_ed25519", "private keys must not be read"),
]
ASK = r"\b(ssh|scp)\b|bench\s+(cadence-check|pdk-\w+)|--backend\s+(cadence|pdk)\b"

for pat, why in BLOCK:
    if re.search(pat, cmd):
        print(f"Blocked by project guard: {why}.", file=sys.stderr)
        sys.exit(2)
if re.search(ASK, cmd):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "Remote Cadence/Spectre action: confirm the request and the expected Spectre count (CLAUDE.md rule 2).",
    }}))
sys.exit(0)
