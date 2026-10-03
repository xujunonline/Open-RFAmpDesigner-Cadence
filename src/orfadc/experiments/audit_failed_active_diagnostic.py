from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.run_active_diagnostic_candidate import (
    _read_ade_companion, render_active_diagnostic_netlist,
)
from orfadc.schemas import Candidate, Spec


FAILURE_RECOVERY_MODE = "remote_quiescent_failed_log_v1"
FAILURE_SOURCE_FILES = ("netlist.scs", "ade_e.scs", "spectre.log")
FAILURE_ARTIFACTS = {
    "metrics": "metrics.json", "candidate": "candidate.json",
    "netlist": "netlist.scs", "ade_companion": "ade_e.scs",
    "spectre_log": "spectre.log", "recovery_provenance": "recovery_provenance.json",
}
_SUMMARY = re.compile(rb"(?im)^[ \t]*spectre completes with ([0-9]+) errors?\b")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def terminal_spectre_error_count(log: bytes) -> int:
    if not isinstance(log, bytes) or not log or len(log) > 16 * 1024 * 1024:
        raise ValueError("failed Spectre log is empty or too large")
    summaries = _SUMMARY.findall(log)
    if len(summaries) != 1 or int(summaries[0]) < 1:
        raise ValueError("failed Spectre log lacks one nonzero terminal error summary")
    return int(summaries[0])


def audit_failed_active_diagnostic(
    run_dir: Path, *, template: Path, template_sha256: str,
) -> dict:
    """Verify a terminal failed OA run; never infer RF metrics from a failure log."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("failed diagnostic archive is missing or unsafe")
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    if {key: value["path"] for key, value in manifest["artifacts"].items()} != FAILURE_ARTIFACTS:
        raise ValueError("failed diagnostic evidence artifacts differ")
    if any((run_dir / name).exists() or (run_dir / name).is_symlink()
           for name in ("spectre.stdout.log", "spectre.stderr.log", "waveforms.csv")):
        raise ValueError("failed recovery archive claims unsupported control or waveform data")
    expected_fields = {
        "schema_version", "status", "simulation_status", "circuit_class", "not_lna_result",
        "spec_pass", "failure_code", "analysis", "spec", "candidate", "seed",
        "timeout_seconds", "run_id", "template_sha256", "source_template_sha256",
        "recovery_mode", "controller_stdout_stderr_captured", "terminal_error_count",
        "recovery_provenance_sha256",
    }
    if not isinstance(saved, dict) or set(saved) != expected_fields:
        raise ValueError("failed diagnostic metrics fields differ")
    if (
        saved["status"] != "spectre_failed"
        or saved["simulation_status"] != "failed"
        or saved["circuit_class"] != "active_common_source_smoke"
        or saved["not_lna_result"] is not True or saved["spec_pass"] is not None
        or saved["failure_code"] != "spectre_error"
        or saved["analysis"] != [] or saved["run_id"] != run_dir.name
        or saved["template_sha256"] != template_sha256
        or saved["source_template_sha256"] != template_sha256
        or saved["recovery_mode"] != FAILURE_RECOVERY_MODE
        or saved["controller_stdout_stderr_captured"] is not False
    ):
        raise ValueError("failed diagnostic status or provenance differs")
    try:
        spec = Spec(**saved["spec"])
        candidate = Candidate(**saved["candidate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("failed diagnostic context is invalid") from exc
    if candidate.spec_id != spec.id or candidate.seed != saved["seed"]:
        raise ValueError("failed diagnostic candidate context differs")
    netlist = render_active_diagnostic_netlist(candidate, template, template_sha256)
    companion = _read_ade_companion(template, netlist)
    if (
        candidate.status != "active_common_source_diagnostic"
        or companion is None
        or (run_dir / "netlist.scs").read_bytes() != netlist.encode("utf-8")
        or (run_dir / "ade_e.scs").read_bytes() != companion
    ):
        raise ValueError("failed diagnostic OA source differs from the planned candidate")
    error_count = terminal_spectre_error_count((run_dir / "spectre.log").read_bytes())
    if type(saved["terminal_error_count"]) is not int or saved["terminal_error_count"] != error_count:
        raise ValueError("failed diagnostic error count differs from Spectre log")
    path = run_dir / "recovery_provenance.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError("failed diagnostic recovery provenance is unsafe")
    raw = path.read_bytes()
    if saved["recovery_provenance_sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("failed diagnostic provenance digest differs")
    try:
        provenance = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("failed diagnostic provenance is malformed") from exc
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {
            "schema_version", "mode", "trace_id", "spec_id", "seed", "candidate_id",
            "run_id", "remote_identity_sha256", "remote_dir_sha256",
            "remote_artifacts_sha256", "terminal_error_count",
            "controller_stdout_stderr_captured", "spectre_dispatched_by_recovery",
        }
        or type(provenance["schema_version"]) is not int or provenance["schema_version"] != 1
        or provenance["mode"] != FAILURE_RECOVERY_MODE
        or not isinstance(provenance["trace_id"], str) or not _ID.fullmatch(provenance["trace_id"])
        or provenance["spec_id"] != spec.id or provenance["seed"] != candidate.seed
        or provenance["candidate_id"] != candidate.candidate_id
        or provenance["run_id"] != run_dir.name
        or any(not isinstance(provenance[key], str) or not _SHA256.fullmatch(provenance[key])
               for key in ("remote_identity_sha256", "remote_dir_sha256"))
        or provenance["terminal_error_count"] != error_count
        or provenance["controller_stdout_stderr_captured"] is not False
        or provenance["spectre_dispatched_by_recovery"] is not False
        or not isinstance(provenance["remote_artifacts_sha256"], dict)
        or set(provenance["remote_artifacts_sha256"]) != set(FAILURE_SOURCE_FILES)
    ):
        raise ValueError("failed diagnostic recovery provenance context differs")
    for name, digest in provenance["remote_artifacts_sha256"].items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("failed diagnostic remote artifact digest is invalid")
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError("failed diagnostic source differs from the remote snapshot")
    return saved
