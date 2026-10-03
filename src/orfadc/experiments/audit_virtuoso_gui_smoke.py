from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_SOURCES = (
    _ROOT / "circuit/skill/virtuoso_gui_smoke.il",
    _ROOT / "circuit/skill/run_virtuoso_gui_smoke.sh",
)
_LOGS = ("virtuoso.log", "virtuoso.stdout", "virtuoso.stderr", "xvfb.stdout", "xvfb.stderr")


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("GUI smoke archive file is missing or unsafe")
    return path.read_bytes()


def audit_virtuoso_gui_smoke(run_dir: Path) -> dict:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("GUI smoke archive directory is missing or unsafe")
    status = json.loads(_read(run_dir / "run_status.json"))
    if (
        status.get("run_id") != run_dir.name
        or status.get("status") != "gui_replay_completed"
        or status.get("returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("downloads") != dict.fromkeys(_LOGS, True)
        or any(status.get(name) is not False for name in
               ("design_cell_opened", "pdk_write", "user_oa_write", "cdf_callback_invoked"))
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
    ):
        raise ValueError("GUI smoke status overstates or lacks its execution evidence")
    hashes = status.get("source_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {path.name for path in _SOURCES}:
        raise ValueError("GUI smoke source hash list is incomplete")
    for source in _SOURCES:
        archived = _read(run_dir / source.name)
        if archived != _read(source) or hashlib.sha256(archived).hexdigest() != hashes[source.name]:
            raise ValueError("GUI smoke replay source differs from checked-in source")
    for name in _LOGS:
        _read(run_dir / name)
    log = _read(run_dir / "virtuoso.log").decode("utf-8", errors="replace")
    if (
        "Virtuoso has launched" not in log
        or len(re.findall(r"(?m)^\\o ORFADC_GUI_REPLAY_BEGIN\s*$", log)) != 1
        or len(re.findall(r"(?m)^\\o ORFADC_GUI_REPLAY_END\s*$", log)) != 1
        or re.search(r"(?m)^\\i exit\(\)\s*$", log) is None
        or log.index("\\o ORFADC_GUI_REPLAY_BEGIN") >= log.index("\\o ORFADC_GUI_REPLAY_END")
    ):
        raise ValueError("Virtuoso did not complete the intended GUI replay")
    return {
        "status": "gui_replay_verified",
        "full_virtuoso_initialized": True,
        "replay_exited": True,
        "design_cell_opened": False,
        "cdf_callback_validated": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reaudit a private full-Virtuoso/Xvfb startup probe")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_gui_smoke(args.run_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"GUI smoke rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
