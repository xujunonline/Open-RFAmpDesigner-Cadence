from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.reconcile_pending import reconcile_pending_diagnostic
from orfadc.agents.recover_pending_remote import recover_pending_diagnostic_remote
from orfadc.agents.remote_identity import write_remote_identity_snapshot
from orfadc.agents.spec_snapshots import write_spec_snapshot
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_agent_diagnostic import DiagnosticSearcher


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic pending-journal drill against an existing completed remote OA run; never dispatch Spectre",
    )
    parser.add_argument("--existing-run-id", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    if not args.existing_run_id.startswith("20") or len(args.existing_run_id) > 64:
        parser.error("existing run ID is not a timestamped diagnostic ID")
    _require_private_path(args.template)
    spec = next((item for item in load_specs(args.specs) if item.id == "S1"), None)
    if spec is None:
        parser.error("S1 spec is missing")
    config = load_remote_config(args.config)
    searcher = DiagnosticSearcher(args.rd_ohm, args.vbias_v)
    label = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    root = _PRIVATE_ROOT / "synthetic_remote_recovery" / label
    trace_dir = root / "trace"
    runs_root = root / "runs"
    trace_dir.mkdir(parents=True, exist_ok=False)
    runs_root.mkdir()
    manager = Manager(searcher=searcher)
    manager.enable_journal(trace_dir)
    try:
        manager.context = (spec.id, 0)
        spec_digest = write_spec_snapshot(trace_dir, spec)
        remote_digest = write_remote_identity_snapshot(trace_dir, config)
        manager._record(
            "RunStarted", spec_id=spec.id, seed=0, max_searches=1, max_evaluations=1,
            spec_sha256=spec_digest, dispatch_mode="planned",
            remote_identity_sha256=remote_digest,
        )
        manager.search_candidates(spec)
        manager.pop_candidate(run_id=args.existing_run_id)
    finally:
        manager.close_journal()
    if inspect_journal(trace_dir).disposition != "reconcile_pending_evaluation":
        raise ValueError("synthetic pending journal was not accepted")
    archive, recovered = recover_pending_diagnostic_remote(
        trace_dir, runs_root, RemoteRunner(config),
        template=args.template, template_sha256=args.template_sha256,
    )
    reconciled = reconcile_pending_diagnostic(
        trace_dir, runs_root, spec, seed=0,
        template=args.template, template_sha256=args.template_sha256,
    )
    audited = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if audited.disposition != "complete" or not audited.candidate_bindings_verified:
        raise ValueError("synthetic recovery journal did not complete")
    report = {
        "schema_version": 1,
        "status": "synthetic_recovery_validation_complete",
        "synthetic_pending_journal": True,
        "actual_interruption_observed": False,
        "existing_remote_run_id": args.existing_run_id,
        "archive_relative": archive.relative_to(root).as_posix(),
        "recovery_status": recovered["status"],
        "reconciliation_status": reconciled["status"],
        "points": recovered["points"],
        "spectre_dispatched_by_validation": False,
        "not_lna_result": True,
        "spec_pass": None,
    }
    write_json(root / "validation_summary.json", report)
    print(f"status={report['status']} points={report['points']}")
    print(f"validation_root={root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
