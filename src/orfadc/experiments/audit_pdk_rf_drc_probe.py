from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


_COUNTS = ("Polygons", "Rectangles", "Paths")
_RULE = re.compile(r"(?m)^RULECHECK\s+(\S+).*?TOTAL Result Count =\s*(\d+)\s*\((\d+)\)")
_DIGEST = re.compile(r"^([0-9a-f]{64})\s+(.+)$")


def _file(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError("physical probe artifact is missing or unsafe")
    return path.read_bytes()


def _text(path: Path) -> str:
    return _file(path).decode("utf-8", errors="replace")


def _status(run_dir: Path) -> dict:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("physical probe archive is missing or unsafe")
    payload = json.loads(_text(run_dir / "run_status.json"))
    if payload.get("returncode") != 0 or payload.get("host_available_gib_before", 0) < 2.66:
        raise ValueError("physical probe did not pass its execution and memory gates")
    if payload.get("pdk_write") is not False or payload.get("user_oa_write") is not False:
        raise ValueError("physical probe claims an unexpected database write")
    return payload


def _stream(run_dir: Path, cell: str, *, expect_empty: bool) -> tuple[dict[str, int], str]:
    status = _status(run_dir)
    if (
        status.get("source_user_cell") != cell
        or status.get("downloads") != {name: True for name in ("layout.gds", "strmout.log", "summary.txt")}
        or (status.get("explicit_tech_library") not in (None, False) if expect_empty
            else status.get("explicit_tech_library") is not True)
    ):
        raise ValueError("stream input context is incomplete")
    summary = _text(run_dir / "summary.txt")
    counts = {}
    for name in _COUNTS:
        match = re.search(rf"(?m)^\s*{name}:\s*(\d+)$", summary)
        if match is None:
            raise ValueError("stream geometry summary is incomplete")
        counts[name] = int(match[1])
    if (sum(counts.values()) == 0) is not expect_empty:
        raise ValueError("stream geometry presence differs from the expected gate")
    log = _text(run_dir / "strmout.log")
    completion = re.search(r"Translation completed\. '0' error\(s\) and '(\d+)' warning\(s\) found\.", log)
    if completion is None or (int(completion[1]) == 0) is expect_empty:
        raise ValueError("stream completion or warning profile is inconsistent")
    if not expect_empty and status.get("shape_counts") != counts:
        raise ValueError("stream status disagrees with translated shapes")
    return counts, hashlib.sha256(_file(run_dir / "layout.gds")).hexdigest()


def _drc(
    run_dir: Path, cell: str, stream_run_id: str, gds_sha256: str,
) -> tuple[int, int, int, dict[str, tuple[int, int]], str]:
    status = _status(run_dir)
    required = ("calibre.stdout", "calibre.stderr", "calibre.exitcode", "source_hashes.txt", "DRC.rep", "DRC_RES.db")
    if (
        status.get("status") != "drc_completed"
        or status.get("downloads") != {name: True for name in required}
        or status.get("remote_script_same") is not True
        or status.get("source_gds_run") != stream_run_id
        or status.get("deck_copy_downloaded") is not False
        or status.get("drc_pass") is True
        or _file(run_dir / "run_drc.sh") != _file(run_dir / "remote_run_drc.sh")
        or hashlib.sha256(_file(run_dir / "run_drc.sh")).hexdigest() != status.get("script_sha256")
        or _text(run_dir / "calibre.exitcode").strip() != "0"
    ):
        raise ValueError("DRC job source or completion differs")
    hashes = [_DIGEST.fullmatch(line) for line in _text(run_dir / "source_hashes.txt").splitlines()]
    if len(hashes) != 3 or any(match is None for match in hashes):
        raise ValueError("DRC source hash list is malformed")
    deck_sha256, _, source_gds_sha256 = (match[1] for match in hashes)
    if source_gds_sha256 != gds_sha256 or Path(hashes[2][2]).name != "layout.gds":
        raise ValueError("DRC did not consume the archived nonempty GDS")
    report = _text(run_dir / "DRC.rep")
    if (
        re.search(rf"(?m)^Layout Primary Cell:\s+{re.escape(cell)}\s*$", report) is None
        or hashes[2][2] not in report
        or "--- RUNTIME WARNINGS" not in report
    ):
        raise ValueError("DRC report does not bind the intended input or warnings")
    stdout = _text(run_dir / "calibre.stdout")
    if "CALIBRE::DRC-H COMPLETED" not in stdout:
        raise ValueError("Calibre did not complete")
    checks = re.search(r"TOTAL RULECHECKS EXECUTED =\s*(\d+)", stdout)
    totals = re.search(r"TOTAL RESULTS GENERATED =\s*(\d+)\s*\((\d+)\)", stdout)
    reported = re.search(r"TOTAL DRC Results Generated:\s*(\d+)\s*\((\d+)\)", report)
    if checks is None or totals is None or reported is None or totals.groups() != reported.groups():
        raise ValueError("DRC result totals are incomplete or inconsistent")
    groups, results = (int(item) for item in totals.groups())
    rules = {name: (int(group), int(count)) for name, group, count in _RULE.findall(report) if int(group) > 0}
    if not rules or sum(group for group, _ in rules.values()) != groups or sum(count for _, count in rules.values()) != results:
        raise ValueError("DRC rule counts do not reconcile with the summary")
    return int(checks[1]), groups, results, rules, deck_sha256


def audit_pdk_rf_drc_probe(
    empty_stream: Path, default_stream: Path, variant_stream: Path,
    default_drc: Path, variant_drc: Path,
) -> dict:
    """Bind OA stream and Calibre evidence without converting job completion into DRC pass."""
    if empty_stream.name != default_drc.name or variant_stream.name != variant_drc.name:
        raise ValueError("physical probe directories do not pair by cell")
    empty_counts, _ = _stream(empty_stream, empty_stream.name, expect_empty=True)
    default_counts, default_gds = _stream(default_stream, default_drc.name, expect_empty=False)
    variant_counts, variant_gds = _stream(variant_stream, variant_drc.name, expect_empty=False)
    if default_gds == variant_gds or default_counts != variant_counts:
        raise ValueError("paired GDS files lack the expected distinct, comparable geometry")
    base_checks, base_groups, base_results, base_rules, base_deck = _drc(
        default_drc, default_drc.name, default_stream.name, default_gds,
    )
    var_checks, var_groups, var_results, var_rules, var_deck = _drc(
        variant_drc, variant_drc.name, variant_stream.name, variant_gds,
    )
    if base_deck != var_deck or base_checks != var_checks:
        raise ValueError("paired DRC jobs did not use one source deck and rule budget")
    return {
        "status": "drc_completed_with_violations",
        "empty_stream_rejected": sum(empty_counts.values()) == 0,
        "nonempty_streams_verified": True,
        "same_source_deck": True,
        "rulechecks_executed": base_checks,
        "default_violation_groups": base_groups,
        "default_results": base_results,
        "variant_violation_groups": var_groups,
        "variant_results": var_results,
        "same_nonzero_rule_counts": base_rules == var_rules,
        "drc_pass": False,
        "drc_context_qualified": False,
        "cdf_callback_validated": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit paired private RF PCell GDS/DRC diagnostics")
    for name in ("empty_stream", "default_stream", "variant_stream", "default_drc", "variant_drc"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = audit_pdk_rf_drc_probe(
            args.empty_stream, args.default_stream, args.variant_stream,
            args.default_drc, args.variant_drc,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"RF DRC probe rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
