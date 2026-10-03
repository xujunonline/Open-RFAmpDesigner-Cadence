"""Stand-in for `codex exec --json ... -o FILE -` and `codex login status`."""
import json
import os
import sys

args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
    sys.exit(0)
assert args[0] == "exec" and "--json" in args and args[-1] == "-", args
out = args[args.index("-o") + 1]
prompt = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "fake-thread"}))
print(json.dumps({"type": "turn.started"}))
if os.environ.get("FAKE_CODEX_FAIL"):
    print(json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit"}}))
    sys.exit(1)
if "Reply with exactly: OK" in prompt:
    text = "OK"
elif "power_ratio_list" in prompt and "RFAmpManager" in prompt:
    text = '<rationale>more stage-3 current</rationale><tools>{"power_ratio_list": [0.3, 0.15, 0.55]}</tools>'
else:
    text = '<rationale>lower critical gain</rationale><tools>{"action":"rerun_stage2","nf_headroom_db":0.4,"gain_require_db":12.0}</tools>'
print(json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": text}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 900, "cached_input_tokens": 300, "output_tokens": 40}}))
open(out, "w", encoding="utf-8").write(text)
