"""Stand-in for `claude -p --output-format json` (same JSON shape as Claude Code 2.x)."""
import json
import os
import sys

args = sys.argv[1:]
prompt = sys.stdin.read()
assert "-p" in args and "--output-format" in args and "--bare" not in args, args
sp = args[args.index("--system-prompt-file") + 1]
system = open(sp, encoding="utf-8").read()
assert "ANTHROPIC_API_KEY" not in os.environ, "API key must be stripped so the subscription is used"
if os.environ.get("FAKE_CLAUDE_FLAG") and "--model" not in args:
    print(json.dumps({"type": "result", "is_error": True, "result": "API Error: safeguards flagged this message"}))
    sys.exit(1)
if os.environ.get("FAKE_CLAUDE_FAIL"):
    print(json.dumps({"type": "result", "is_error": True, "result": "Claude usage limit reached"}))
    sys.exit(1)
if "Reply with exactly: OK" in prompt:
    result = "OK"
elif "power_ratio_list" in prompt and "RFAmpManager" in system:
    result = '<rationale>shift current to stage 3</rationale><tools>{"power_ratio_list": [0.3, 0.15, 0.55]}</tools>'
else:
    result = ('<rationale>stage 3 current-limited: lower gain before it</rationale>'
              '<tools>{"action":"rerun_stage3","gain_req_list":[4.0,6.0,16.0],"why":"fake"}</tools>')
print(json.dumps({"type": "result", "is_error": False, "result": result, "total_cost_usd": 0.01,
                  "usage": {"input_tokens": 12, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0,
                            "output_tokens": 20}}))
