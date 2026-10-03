from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_window_manager_probe import _FILES, _SCRIPT


def audit_window_manager_probe(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError("window-manager probe archive is missing or unsafe")
    saved = read_evidenced_metrics(output_dir)
    script_path = output_dir / _SCRIPT.name
    if script_path.read_bytes() != _SCRIPT.read_bytes():
        raise ValueError("window-manager probe source differs from checked-in script")
    report_path = output_dir / "probe_report.txt"
    if report_path.is_symlink():
        raise ValueError("window-manager report is symlinked")
    report = report_path.read_text(encoding="utf-8")
    if re.fullmatch(r"xvfb_alive=(?:t|nil)\nmutter_alive=(?:t|nil)\nwm_registered=(?:t|nil)\n", report) is None:
        raise ValueError("window-manager report has invalid fields")
    flags = {key: f"{key}=t\n" in report for key in (
        "xvfb_alive", "mutter_alive", "wm_registered",
    )}
    property_path = output_dir / "wm_property.txt"
    if property_path.is_symlink():
        raise ValueError("window-manager property is symlinked")
    property_registered = bool(re.fullmatch(
        r"_NET_SUPPORTING_WM_CHECK\(WINDOW\): window id # 0x[0-9a-fA-F]+\n",
        property_path.read_text(encoding="utf-8"),
    ))
    if flags["wm_registered"] != property_registered:
        raise ValueError("window-manager report and X11 property disagree")
    if (saved.get("schema_version") != 1 or saved.get("run_id") != output_dir.name
            or saved.get("simulation_status") != "unknown"
            or saved.get("circuit_class") != "window_manager_probe"
            or saved.get("script_sha256") != hashlib.sha256(_SCRIPT.read_bytes()).hexdigest()
            or saved.get("pdk_access") is not False or saved.get("cadence_launched") is not False
            or saved.get("not_lna_result") is not True or saved.get("spec_pass") is not None
            or saved.get("xvfb_alive_at_probe") is not flags["xvfb_alive"]
            or saved.get("mutter_alive_at_probe") is not flags["mutter_alive"]
            or saved.get("wm_registered_at_probe") is not flags["wm_registered"]
            or saved.get("downloads") != {name: True for name in _FILES}):
        raise ValueError("window-manager metrics differ from archived observation")
    expected_status = "registered" if all(flags.values()) else "unavailable"
    if saved.get("status") != expected_status or saved.get("returncode") != 0:
        raise ValueError("window-manager status differs from archived observation")
    return {"status": "verified", "wm_registered": flags["wm_registered"],
            "cadence_launched": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of isolated Xvfb/Mutter probe")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    result = audit_window_manager_probe(args.output_dir)
    print(f"status={result['status']} wm_registered={result['wm_registered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
