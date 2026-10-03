from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_cdf_readonly import _LAUNCHER, _LOGS, _render_readonly_script


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("CDF read-only archive file is missing or unsafe")
    return path.read_bytes()


def audit_virtuoso_cdf_readonly(run_dir: Path, source: Path, baseline_report: Path) -> dict:
    for path in (run_dir, source, baseline_report):
        _require_private_path(path)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("CDF read-only archive directory is missing or unsafe")
    status = json.loads(_read(run_dir / "run_status.json"))
    if (
        status.get("run_id") != run_dir.name
        or status.get("status") != "gui_cdf_readonly_completed"
        or status.get("returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("downloads") != dict.fromkeys((*_LOGS, "cdf_readonly_report.txt"), True)
        or any(status.get(name) is not False for name in ("pdk_write", "user_oa_write", "cdf_callback_invoked"))
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
    ):
        raise ValueError("CDF read-only run status lacks its execution boundary")
    original = _read(run_dir / "source_readonly.ocn")
    source_sha = status.get("source_sha256")
    if original != _read(source) or hashlib.sha256(original).hexdigest() != source_sha:
        raise ValueError("CDF query source differs from the fixed private source")
    rendered = _read(run_dir / "virtuoso_gui_smoke.il")
    first = rendered.splitlines(keepends=True)[0]
    match = re.fullmatch(rb'reportPort=outfile\("([^"\r\n]+/cdf_readonly_report\.txt)" "w"\)\r?\n', first)
    if (
        match is None
        or rendered != _render_readonly_script(source, source_sha, match[1].decode("ascii"))
        or hashlib.sha256(rendered).hexdigest() != status.get("rendered_sha256")
        or _read(run_dir / _LAUNCHER.name) != _read(_LAUNCHER)
        or hashlib.sha256(_read(run_dir / _LAUNCHER.name)).hexdigest() != status.get("launcher_sha256")
    ):
        raise ValueError("CDF query replay differs from the approved read-only derivation")
    for name in _LOGS:
        _read(run_dir / name)
    log = _read(run_dir / "virtuoso.log").decode("utf-8", errors="replace")
    if "Virtuoso has launched" not in log or re.search(r"(?m)^\\i exit\(\)\s*$", log) is None:
        raise ValueError("full Virtuoso replay did not complete")
    report = _read(run_dir / "cdf_readonly_report.txt")
    if not report or report != _read(baseline_report):
        raise ValueError("GUI CDF report differs from the prior OCEAN read-only baseline")
    return {
        "status": "gui_cdf_readonly_verified",
        "full_virtuoso_initialized": True,
        "cdf_report_matches_prior_ocean": True,
        "cdf_callback_validated": False,
        "pdk_write": False,
        "user_oa_write": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reaudit private full-Virtuoso read-only CDF query")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("baseline_report", type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_cdf_readonly(args.run_dir, args.source, args.baseline_report)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"CDF read-only probe rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
