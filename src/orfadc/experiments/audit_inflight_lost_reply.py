from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from orfadc.agents.journal import inspect_journal
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


_RAW_PROBE = re.compile(
    r"directory=(present|missing|symlink)\nactive=([01])\nlog=([01])\n"
    r"sp=([01])\nnoise=([01])\n?\Z"
)


def _json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("probe evidence is missing or unsafe")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("probe evidence must be an object")
    return data


def audit_inflight_lost_reply(
    trace_dir: Path, runs_root: Path, *, template: Path, template_sha256: str,
) -> dict:
    for path in (trace_dir, runs_root, template):
        _require_private_path(path)
    if not trace_dir.is_dir() or trace_dir.is_symlink():
        raise ValueError("probe trace is missing or unsafe")
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if not (
        journal.disposition == "complete" and journal.trace_verified
        and journal.candidate_bindings_verified and journal.candidate_snapshots_verified
        and journal.spec_verified and journal.remote_identity_verified
    ):
        raise ValueError("probe journal is not a verified completed recovery")
    events_path = trace_dir / "agent_events.jsonl"
    if events_path.is_symlink():
        raise ValueError("probe journal is unsafe")
    start = json.loads(events_path.read_text(encoding="ascii").splitlines()[0])
    identity = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    pending = _json(trace_dir / "agent_evaluation.json")
    final = _json(trace_dir / "agent_reconciliation.json")
    lost = _json(trace_dir / "lost_reply_probe.json")
    inflight = _json(trace_dir / "inflight_probe.json")
    run_id = pending.get("candidate_run_id")
    candidate_id = pending.get("candidate_id")
    remote_name = f"rf_active_{journal.spec_id}_seed{journal.seed}_{candidate_id}_{run_id}"
    remote_dir = str(PurePosixPath(identity["remote_root"]) / remote_name)
    if (
        start.get("dispatch_mode") != "planned"
        or pending.get("execution_status") != "pending_remote_evaluation"
        or pending.get("not_lna_result") is not True or pending.get("spec_pass") is not None
        or final.get("status") != "reconciled_existing_diagnostic_archive"
        or final.get("candidate_run_id") != run_id
        or final.get("refiner_status") != "needs_evaluation"
        or final.get("spectre_dispatched_by_reconciliation") is not False
        or final.get("recovery_mode") != "remote_quiescent_download_v1"
        or final.get("not_lna_result") is not True or final.get("spec_pass") is not None
        or lost.get("trace_id") != trace_dir.name
        or lost.get("candidate_run_id") != run_id
        or lost.get("spectre_calls") != 1
        or lost.get("actual_remote_returncode") != 0
        or lost.get("reply_suppressed") is not True
        or lost.get("pending_execution_status") != "pending_remote_evaluation"
        or inflight.get("trace_id") != trace_dir.name
        or inflight.get("candidate_run_id") != run_id
        or inflight.get("remote_dir_sha256") != hashlib.sha256(remote_dir.encode("utf-8")).hexdigest()
        or inflight.get("real_spectre_returncode") != 0
        or inflight.get("reply_suppressed") is not True
        or inflight.get("pending_execution_status") != "pending_remote_evaluation"
        or inflight.get("spectre_dispatched_by_observer") is not False
        or inflight.get("not_lna_result") is not True or inflight.get("spec_pass") is not None
    ):
        raise ValueError("in-flight probe does not match the planned recovered run")
    samples = inflight.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 100:
        raise ValueError("in-flight probe has no bounded SSH observations")
    active_observed = False
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("raw_returncode") != 0:
            raise ValueError("in-flight SSH observation did not complete")
        raw = sample.get("raw_stdout")
        match = _RAW_PROBE.fullmatch(raw) if isinstance(raw, str) else None
        if match is None:
            raise ValueError("in-flight raw SSH status is malformed")
        directory, active, log, sp, noise = match.groups()
        parsed = sample.get("parsed")
        if parsed != {
            "state": "observed", "directory": directory,
            "spectre_active": active == "1", "spectre_log_present": log == "1",
            "sp_raw_present": sp == "1", "noise_raw_present": noise == "1",
        }:
            raise ValueError("in-flight parsed status differs from raw SSH response")
        active_observed |= directory == "present" and active == "1"
    if inflight.get("spectre_in_flight_observed") is not active_observed or not active_observed:
        raise ValueError("no matching live Spectre process was observed")
    relative = final.get("candidate_run_relative")
    if relative != f"{journal.spec_id}/seed{journal.seed}/{candidate_id}/{run_id}":
        raise ValueError("recovered candidate path differs from planned run")
    run_dir = runs_root / relative
    metrics = audit_active_diagnostic_candidate(
        run_dir, template=template, template_sha256=template_sha256,
    )
    if (
        metrics.get("status") not in {"ok", "ok_with_warnings"}
        or metrics.get("recovery_mode") != "remote_quiescent_download_v1"
        or metrics.get("not_lna_result") is not True or metrics.get("spec_pass") is not None
    ):
        raise ValueError("recovered candidate is not a verified diagnostic result")
    return {
        "status": "inflight_seen_and_recovered_diagnostic",
        "samples": len(samples), "candidate_run_id": run_id,
        "points": metrics["points"], "spectre_calls_recorded": 1,
        "not_lna_result": True, "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a private in-flight Spectre observation and recovery")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    result = audit_inflight_lost_reply(
        args.trace_dir, args.runs_root,
        template=args.template, template_sha256=args.template_sha256,
    )
    print(f"status={result['status']} samples={result['samples']} points={result['points']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
