"""PreToolUse hook: block commands that would leak secrets or dispatch
unrequested remote Cadence jobs.  Exit 2 = block with a reason."""
import json
import re
import sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")
except Exception:
    sys.exit(0)
rules = [
    (r"remote_cadence\.local\.yaml|model_paths\.local\.yaml", "secret config files must not be read or printed"),
    (r"(cat|type|Get-Content)\s+[^|]*\.(pem|key)\b|id_rsa|id_ed25519", "private keys must not be read"),
    (r"--publish-remote-fence|ORFADC_RUN_LIVE_SSH_AUDIT=1", "live remote Cadence actions need an explicit user request (docs/113, docs/114)"),
]
for pat, why in rules:
    if re.search(pat, cmd):
        print(f"Blocked by project guard: {why}.", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
