"""PostToolUse hook: byte-compile edited Python files under src/ or tests/.

Exit code 2 feeds the compiler error back to Claude so it fixes it at once.
"""
import json
import py_compile
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
path = (data.get("tool_input") or {}).get("file_path") or ""
p = Path(path)
if p.suffix == ".py" and p.exists() and any(part in ("src", "tests") for part in p.parts):
    try:
        py_compile.compile(str(p), doraise=True)
    except (py_compile.PyCompileError, OSError) as exc:
        print(f"Python syntax error after edit: {getattr(exc, 'msg', exc)}", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
