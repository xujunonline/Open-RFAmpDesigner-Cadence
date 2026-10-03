from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_spiral_stream import audit_pdk_spiral_stream_report
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_spiral_drc import render_spiral_drc_script
from orfadc.experiments.run_pdk_spiral_stream import _CELLS
from orfadc.metric_contract import validate_metrics_payload


_ROOT = _PRIVATE_ROOT / "pdk_spiral_drc"
_RUNS = {"default": "20260927T062725Z_9d6d0279", "nr4": "20260927T062819Z_e91b6a15"}
_FILES = (
    "run_status.json", "run_drc.sh", "remote_run_drc.sh", "remote_input.gds",
    "calibre.stdout", "calibre.stderr", "calibre.exitcode", "source_hashes.txt",
    "DRC.rep", "DRC_RES.db", "stdout.log", "stderr.log",
)
_RULE = re.compile(r"(?m)^RULECHECK\s+(\S+).*?TOTAL Result Count =\s*(\d+)\s*\((\d+)\)")
_HASH_LINE = re.compile(r"([0-9a-f]{64})\s+(/[^\s]+)\Z")


def _read(path: Path) -> bytes:
    _require_private_path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("diagnostic spiral DRC artifact is missing or unsafe")
    return path.read_bytes()


def build_pdk_spiral_drc_report(run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("spiral DRC summary run ID is invalid")
    stream_summary = _PRIVATE_ROOT / "pdk_spiral_stream" / "summary_20260927_01"
    audit_pdk_spiral_stream_report(stream_summary)
    stream = read_evidenced_metrics(stream_summary)
    hashes = {}
    rules = {}
    totals = {}
    deck_hashes = set()
    source_paths = set()
    rulechecks = set()
    for variant, name in _RUNS.items():
        run_dir = _ROOT / name
        hashes[variant] = {file: hashlib.sha256(_read(run_dir / file)).hexdigest()
                           for file in _FILES}
        status = json.loads(_read(run_dir / "run_status.json").decode("utf-8"))
        gds = _read(stream_summary.parent / stream["source_run_ids"][variant] / "layout.gds")
        if (
            status.get("status") != "diagnostic_drc_recorded"
            or status.get("run_id") != name or status.get("variant") != variant
            or status.get("source_stream_run_id") != stream["source_run_ids"][variant]
            or status.get("source_stream_summary_run_id") != stream_summary.name
            or status.get("source_stream_manifest_sha256") != hashlib.sha256(
                _read(stream_summary / "evidence_manifest.json"),
            ).hexdigest()
            or status.get("source_gds_sha256") != hashlib.sha256(gds).hexdigest()
            or status.get("host_available_gib_before", 0) < 2.66
            or status.get("returncode") != 0
            or status.get("downloads") != dict.fromkeys((
                "remote_run_drc.sh", "remote_input.gds", "calibre.stdout", "calibre.stderr",
                "calibre.exitcode", "source_hashes.txt", "DRC.rep", "DRC_RES.db",
            ), True)
            or any(status.get(flag) is not False for flag in (
                "pdk_write", "user_oa_write", "drc_input_qualified", "drc_pass",
                "cdf_callback_validated", "physical_qualification",
            ))
            or status.get("not_lna_result") is not True or status.get("spec_pass") is not None
            or _read(run_dir / "remote_input.gds") != gds
            or _read(run_dir / "calibre.exitcode").strip() != b"0"
            or not _read(run_dir / "DRC_RES.db")
        ):
            raise ValueError("spiral DRC source GDS, execution, or qualification differs")
        lines = _read(run_dir / "source_hashes.txt").decode("utf-8").splitlines()
        parsed = [_HASH_LINE.fullmatch(line) for line in lines]
        if len(parsed) != 3 or any(match is None for match in parsed):
            raise ValueError("spiral DRC source hash list is malformed")
        deck_sha, deck_path = parsed[0].groups()
        _, rule_path = parsed[1].groups()
        input_sha, input_path = parsed[2].groups()
        remote_dir = str(Path(input_path).parent).replace("\\", "/")
        script = render_spiral_drc_script(remote_dir, deck_path, _CELLS[variant][0])
        if (
            input_sha != hashlib.sha256(gds).hexdigest()
            or Path(input_path).name != "input.gds"
            or Path(rule_path).name != "rules.svrf"
            or str(Path(rule_path).parent).replace("\\", "/") != remote_dir
            or _read(run_dir / "run_drc.sh") != script
            or _read(run_dir / "remote_run_drc.sh") != script
            or status.get("script_sha256") != hashlib.sha256(script).hexdigest()
            or status.get("source_deck_path_sha256") != hashlib.sha256(deck_path.encode("utf-8")).hexdigest()
        ):
            raise ValueError("spiral DRC script or remote source hashes differ")
        deck_hashes.add(deck_sha)
        source_paths.add(deck_path)
        report = _read(run_dir / "DRC.rep").decode("utf-8", errors="replace")
        stdout = _read(run_dir / "calibre.stdout").decode("utf-8", errors="replace")
        if (
            not re.search(r"(?m)^Layout Primary Cell:\s+" + re.escape(_CELLS[variant][0]) + r"\s*$", report)
            or input_path not in report
            or "--- RUNTIME WARNINGS" not in report
            or "CALIBRE::DRC-H COMPLETED" not in stdout
        ):
            raise ValueError("spiral DRC report lacks its input or warning context")
        checks = re.search(r"TOTAL RULECHECKS EXECUTED =\s*(\d+)", stdout)
        stdout_totals = re.search(r"TOTAL RESULTS GENERATED =\s*(\d+)\s*\((\d+)\)", stdout)
        report_totals = re.search(r"TOTAL DRC Results Generated:\s*(\d+)\s*\((\d+)\)", report)
        if checks is None or stdout_totals is None or report_totals is None or stdout_totals.groups() != report_totals.groups():
            raise ValueError("spiral DRC total counts do not reconcile")
        rulechecks.add(int(checks[1]))
        groups, count = (int(value) for value in stdout_totals.groups())
        nonzero = {key: (int(group), int(items)) for key, group, items in _RULE.findall(report)
                   if int(group) > 0}
        if (
            not nonzero or groups == 0 or count == 0
            or sum(group for group, _ in nonzero.values()) != groups
            or sum(items for _, items in nonzero.values()) != count
        ):
            raise ValueError("spiral DRC nonzero rule counts differ from totals")
        totals[variant] = {"violation_groups": groups, "results": count,
                           "nonzero_rule_types": len(nonzero)}
        rules[variant] = nonzero
    if len(deck_hashes) != 1 or len(source_paths) != 1 or rulechecks != {2319}:
        raise ValueError("spiral DRC pair did not use the same deck and rule budget")
    changed = sum(rules["default"].get(key) != rules["nr4"].get(key)
                  for key in rules["default"].keys() | rules["nr4"].keys())
    if totals != {
        "default": {"violation_groups": 83, "results": 83, "nonzero_rule_types": 39},
        "nr4": {"violation_groups": 85, "results": 85, "nonzero_rule_types": 41},
    } or changed != 2:
        raise ValueError("spiral DRC comparison differs from the recorded diagnostics")
    payload = {
        "schema_version": 1, "run_id": run_id,
        "status": "pdk_spiral_diagnostic_drc_with_violations",
        "simulation_status": "unknown", "source": "cadence_calibre_private_archives",
        "circuit_class": "passive_oneport_layout_probe", "model_kind": "authorized_pdk_private",
        "scope": "Paired Calibre jobs on warned GDS inputs; diagnostic only, not DRC signoff",
        "source_stream_summary_run_id": stream_summary.name,
        "source_stream_manifest_sha256": hashlib.sha256(
            _read(stream_summary / "evidence_manifest.json"),
        ).hexdigest(),
        "source_run_ids": _RUNS,
        "source_artifact_sha256": hashes,
        "same_source_deck": True, "source_deck_sha256": next(iter(deck_hashes)),
        "rulechecks_executed_each": 2319, "results": totals,
        "changed_nonzero_rule_types": changed,
        "runtime_warnings_present": True,
        "drc_input_qualified": False, "drc_context_qualified": False,
        "drc_pass": False, "cdf_callback_validated": False,
        "physical_qualification": False, "pdk_write": False,
        "not_lna_result": True, "spec_pass": None,
    }
    validate_metrics_payload(payload)
    return payload


def write_pdk_spiral_drc_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    report = build_pdk_spiral_drc_report(output_dir.name)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "metrics.json", report)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json"})
    audit_pdk_spiral_drc_report(output_dir)
    return report


def audit_pdk_spiral_drc_report(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    saved = read_evidenced_metrics(output_dir)
    rebuilt = build_pdk_spiral_drc_report(output_dir.name)
    if saved != rebuilt:
        raise ValueError("spiral diagnostic DRC summary differs from original Calibre archives")
    return {"status": "verified", "drc_pass": False,
            "drc_input_qualified": False, "physical_qualification": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or audit paired private spiral diagnostic DRC jobs")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = write_pdk_spiral_drc_report(args.output_dir) if args.finalize else audit_pdk_spiral_drc_report(args.output_dir)
    print(f"status={result['status']} output={args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
