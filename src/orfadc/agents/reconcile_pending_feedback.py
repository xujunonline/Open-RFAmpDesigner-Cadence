from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.remote_identity import read_remote_identity_snapshot
from orfadc.agents.run_lock import agent_run_lock
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.audit_diagnostic_feedback_agent import (
    audit_diagnostic_feedback_agent, rebuild_diagnostic_feedback_summary,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.schemas import Candidate, Spec


def _source_dir(root: Path, spec: Spec, candidate: Candidate, run_id: str) -> Path:
    cursor = root
    for part in (spec.id, f"seed{candidate.seed}", candidate.candidate_id, run_id):
        cursor = cursor / part
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("feedback source path is linked")
    if not cursor.is_dir() or not cursor.resolve().is_relative_to(root.resolve()):
        raise ValueError("planned feedback archive is absent or unsafe")
    return cursor


def _audit_source(
    run_dir: Path, spec: Spec, candidate: Candidate, *, template: Path, template_sha256: str,
) -> tuple[dict, str]:
    saved = read_evidenced_metrics(run_dir)
    evidence = audit_active_diagnostic_candidate(
        run_dir, template=template, template_sha256=template_sha256,
    )
    if (
        evidence != saved or evidence.get("spec") != asdict(spec)
        or evidence.get("candidate") != candidate.to_dict()
        or evidence.get("run_id") != run_dir.name
        or evidence.get("simulation_status") != "ok"
        or evidence.get("not_lna_result") is not True
        or evidence.get("spec_pass") is not None
    ):
        raise ValueError("feedback source differs from the planned candidate or raw audit")
    digest = hashlib.sha256((run_dir / "evidence_manifest.json").read_bytes()).hexdigest()
    return evidence, digest


def _check_recovery_provenance(
    run_dir: Path, evidence: dict, trace_dir: Path, identity: dict, identity_digest: str,
    candidate: Candidate,
) -> None:
    if evidence.get("recovery_mode") is None:
        return
    if evidence["recovery_mode"] != "remote_quiescent_download_v1":
        raise ValueError("feedback source has unsupported recovery mode")
    provenance = json.loads((run_dir / "recovery_provenance.json").read_text(encoding="utf-8"))
    remote_name = (
        f"rf_active_{candidate.spec_id}_seed{candidate.seed}_{candidate.candidate_id}_{run_dir.name}"
    )
    remote_dir = str(PurePosixPath(identity["remote_root"]) / remote_name)
    if (
        provenance.get("trace_id") != trace_dir.name
        or provenance.get("remote_identity_sha256") != identity_digest
        or provenance.get("remote_dir_sha256") != hashlib.sha256(remote_dir.encode("utf-8")).hexdigest()
    ):
        raise ValueError("feedback recovery provenance differs from the planned remote identity")


def reconcile_pending_feedback(
    trace_dir: Path, runs_root: Path, spec: Spec, *, seed: int,
    template: Path, template_sha256: str, specs_path: Path,
) -> dict:
    """Adopt an already completed second OA feedback run without dispatching Spectre."""
    for path in (trace_dir, runs_root, template):
        _require_private_path(path)
    loaded = {item.id: item for item in load_specs(specs_path)}
    if loaded.get(spec.id) != spec:
        raise ValueError("feedback reconciliation spec file differs from the planned spec")
    with agent_run_lock(trace_dir):
        journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
        if (
            journal.disposition != "reconcile_pending_evaluation"
            or not journal.spec_verified or not journal.candidate_snapshots_verified
            or not journal.remote_identity_verified or not journal.candidate_bindings_verified
            or journal.spec_id != spec.id or journal.seed != seed
            or journal.searches_used != 2 or journal.evaluations_used != 2
            or journal.pending_candidate_id != f"{spec.id}_seed{seed}_oa_feedback1"
            or journal.pending_run_id is None
            or any((trace_dir / name).exists() or (trace_dir / name).is_symlink() for name in (
                "agent_trace.json", "diagnostic_feedback_summary.json", "feedback_reconciliation.json",
            ))
        ):
            raise ValueError("trace is not an eligible second-round feedback pending evaluation")
        events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        if [item["action"] for item in events] != [
            "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
            "SearchCandidates", "EvaluateCandidate",
        ] or events[3]["status"] != "diagnostic_refinement_proposed":
            raise ValueError("pending feedback journal has an incompatible first round")
        start = events[0]
        if (
            start.get("dispatch_mode") != "planned"
            or start.get("max_searches") != 2 or start.get("max_evaluations") != 2
            or read_spec_snapshot(trace_dir, start["spec_sha256"]) != spec
        ):
            raise ValueError("pending feedback lacks its original planned spec context")
        identity_digest = start["remote_identity_sha256"]
        identity = read_remote_identity_snapshot(trace_dir, identity_digest)
        snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
            encoding="ascii"
        ).splitlines()]
        if len(snapshots) != 2 or any(len(item["candidates"]) != 1 for item in snapshots):
            raise ValueError("pending feedback lacks two bound candidate snapshots")
        first, second = (Candidate(**item["candidates"][0]) for item in snapshots)
        if (
            first.candidate_id != f"{spec.id}_seed{seed}_oa_feedback0"
            or second.candidate_id != journal.pending_candidate_id
            or any(candidate.spec_id != spec.id or candidate.seed != seed
                   or candidate.status != "active_common_source_diagnostic"
                   or candidate.notes or candidate.power_ratio_list or candidate.passive_params
                   or candidate.sim_result is not None
                   or set(candidate.active_params) != {"rd_ohm", "vbias_v"}
                   for candidate in (first, second))
            or events[2]["candidate_id"] != first.candidate_id
            or events[3]["candidate_id"] != first.candidate_id
            or events[3]["run_id"] != events[2]["run_id"]
            or events[5]["candidate_id"] != second.candidate_id
            or events[5]["run_id"] != journal.pending_run_id
        ):
            raise ValueError("pending feedback candidates differ from their journal")
        pending_path = trace_dir / "feedback_pending.json"
        if pending_path.exists() or pending_path.is_symlink():
            if not pending_path.is_file() or pending_path.is_symlink():
                raise ValueError("pending feedback snapshot is unsafe")
            expected_pending = {
                "schema_version": 1, "status": "pending_remote_evaluation",
                "trace_id": trace_dir.name, "pending_run_id": journal.pending_run_id,
                "evaluations_used": 2,
                "recovery_status": "manual_reconciliation_required_no_automatic_retry",
                "not_lna_result": True, "spec_pass": None,
            }
            if json.loads(pending_path.read_text(encoding="utf-8")) != expected_pending:
                raise ValueError("pending feedback snapshot differs from the planned dispatch")
        first_dir = _source_dir(runs_root, spec, first, events[2]["run_id"])
        first_evidence, first_digest = _audit_source(
            first_dir, spec, first, template=template, template_sha256=template_sha256,
        )
        _check_recovery_provenance(first_dir, first_evidence, trace_dir, identity, identity_digest, first)
        if events[3]["evidence_manifest_sha256"] != first_digest:
            raise ValueError("first feedback source differs from the journal binding")
        first_gain = first_evidence["metrics"].get("s21_db")
        first_rd = first.active_params["rd_ohm"]
        second_rd = second.active_params["rd_ohm"]
        if (
            type(first_gain) not in {int, float} or not math.isfinite(first_gain)
            or first_gain >= spec.gain_db
            or second_rd != round(first_rd * 1.1, 9)
            or second_rd > 1000
            or second.active_params["vbias_v"] != first.active_params["vbias_v"]
        ):
            raise ValueError("second feedback candidate is not justified by the first raw result")
        second_dir = _source_dir(runs_root, spec, second, journal.pending_run_id)
        second_evidence, second_digest = _audit_source(
            second_dir, spec, second, template=template, template_sha256=template_sha256,
        )
        _check_recovery_provenance(second_dir, second_evidence, trace_dir, identity, identity_digest, second)
        manager = Manager(max_searches=2, max_evaluations=2)
        manager.context = (spec.id, seed)
        manager.searches_used = manager.evaluations_used = 2
        manager.seen_ids = {first.candidate_id, second.candidate_id}
        manager.pending = {second.candidate_id: second}
        manager.pending_run_ids = {second.candidate_id: journal.pending_run_id}
        manager.trace = events
        manager.attach_journal_for_resume(trace_dir)
        try:
            refined = manager.record_result(second, second_dir, spec)
            manager._record("Stop", status="budget_exhausted")
        finally:
            manager.close_journal()
        manager.save_trace(trace_dir)
        summary = rebuild_diagnostic_feedback_summary(
            trace_dir, runs_root, template=template,
            template_sha256=template_sha256, specs_path=specs_path,
        )
        write_json(trace_dir / "diagnostic_feedback_summary.json", summary)
        if audit_diagnostic_feedback_agent(
            trace_dir, runs_root, template=template,
            template_sha256=template_sha256, specs_path=specs_path,
        ) != summary:
            raise ValueError("reconciled feedback differs from independent source audit")
        report = {
            "schema_version": 1, "status": "reconciled_existing_second_feedback_archive",
            "trace_id": trace_dir.name, "first_run_id": first_dir.name,
            "second_run_id": second_dir.name,
            "second_manifest_sha256": second_digest,
            "refiner_status": refined.status,
            "spectre_dispatched_by_reconciliation": False,
            "not_lna_result": True, "spec_pass": None,
        }
        write_json(trace_dir / "feedback_reconciliation.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Adopt a complete second OA feedback archive without Spectre dispatch")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    specs = {item.id: item for item in load_specs(args.specs)}
    if args.spec not in specs:
        parser.error("unknown feedback spec")
    try:
        report = reconcile_pending_feedback(
            args.trace_dir, args.runs_root, specs[args.spec], seed=args.seed,
            template=args.template, template_sha256=args.template_sha256,
            specs_path=args.specs,
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        parser.error(f"feedback reconciliation rejected: {type(exc).__name__}")
    print(f"status={report['status']} run_id={report['second_run_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
