from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.spec_snapshots import read_spec_snapshot
from orfadc.config_loader import load_specs
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


def rebuild_diagnostic_feedback_summary(
    trace_dir: Path, runs_root: Path, *, template: Path, template_sha256: str,
    specs_path: Path,
) -> dict:
    for path in (trace_dir, runs_root, template):
        _require_private_path(path)
    journal = inspect_journal(trace_dir, candidate_runs_root=runs_root)
    if not all((
        journal.disposition == "complete", journal.trace_verified,
        journal.spec_verified, journal.remote_identity_verified,
        journal.candidate_snapshots_verified, journal.candidate_bindings_verified,
        journal.searches_used == 2, journal.evaluations_used == 2,
    )):
        raise ValueError("diagnostic feedback journal lacks two complete evidenced rounds")
    specs = {item.id: item for item in load_specs(specs_path)}
    if journal.spec_id not in specs:
        raise ValueError("diagnostic feedback spec is unavailable")
    spec = specs[journal.spec_id]
    events = json.loads((trace_dir / "agent_trace.json").read_text(encoding="utf-8"))["events"]
    if read_spec_snapshot(trace_dir, events[0]["spec_sha256"]) != spec:
        raise ValueError("diagnostic feedback spec snapshot differs from the loaded spec")
    snapshots = [json.loads(line) for line in (trace_dir / "agent_candidates.jsonl").read_text(
        encoding="ascii"
    ).splitlines()]
    if (
        len(snapshots) != 2 or any(len(item["candidates"]) != 1 for item in snapshots)
        or [item["action"] for item in events] != [
            "RunStarted", "SearchCandidates", "EvaluateCandidate", "RefineCandidate",
            "SearchCandidates", "EvaluateCandidate", "RefineCandidate", "Stop",
        ]
        or events[3]["status"] != "diagnostic_refinement_proposed"
        or events[6]["status"] not in {"needs_evaluation", "diagnostic_refinement_proposed"}
    ):
        raise ValueError("diagnostic feedback trace has an incompatible schedule")
    results = []
    for index in range(2):
        candidate = snapshots[index]["candidates"][0]
        evaluation = events[2 + 3 * index]
        refinement = events[3 + 3 * index]
        if (
            candidate["candidate_id"] != f"{spec.id}_seed{journal.seed}_oa_feedback{index}"
            or candidate["spec_id"] != spec.id or candidate["seed"] != journal.seed
            or candidate["status"] != "active_common_source_diagnostic"
            or candidate["power_ratio_list"] != [] or candidate["passive_params"] != {}
            or candidate["notes"] != [] or candidate["sim_result"] is not None
            or set(candidate["active_params"]) != {"rd_ohm", "vbias_v"}
            or evaluation["candidate_id"] != candidate["candidate_id"]
            or refinement["candidate_id"] != candidate["candidate_id"]
            or refinement["run_id"] != evaluation["run_id"]
        ):
            raise ValueError("diagnostic feedback candidate differs from the bound snapshot")
        run_dir = runs_root / spec.id / f"seed{journal.seed}" / candidate["candidate_id"] / evaluation["run_id"]
        evidence = audit_active_diagnostic_candidate(
            run_dir, template=template, template_sha256=template_sha256,
        )
        manifest_sha256 = hashlib.sha256((run_dir / "evidence_manifest.json").read_bytes()).hexdigest()
        if (
            evidence["candidate"] != candidate or evidence["spec"] != asdict(spec)
            or evidence["run_id"] != run_dir.name or evidence["seed"] != journal.seed
            or evidence["not_lna_result"] is not True or evidence["spec_pass"] is not None
            or refinement["evidence_manifest_sha256"] != manifest_sha256
            or evidence["status"] not in {"ok", "ok_with_warnings"}
            or evidence["simulation_status"] != "ok"
        ):
            raise ValueError("diagnostic feedback raw evidence differs from its journal context")
        gain = evidence["metrics"].get("s21_db")
        if type(gain) not in {int, float} or not math.isfinite(gain):
            raise ValueError("diagnostic feedback gain is not finite")
        results.append({
            "run_id": run_dir.name, "source_status": "raw_audited",
            "candidate_id": candidate["candidate_id"],
            "rd_ohm": candidate["active_params"]["rd_ohm"],
            "vbias_v": candidate["active_params"]["vbias_v"],
            "s21_db": gain, "manifest_sha256": manifest_sha256,
            "not_lna_result": True, "spec_pass": None,
        })
    first, second = results
    if (
        first["s21_db"] >= spec.gain_db
        or first["rd_ohm"] < 50 or first["rd_ohm"] > 1000
        or second["rd_ohm"] != round(first["rd_ohm"] * 1.1, 9)
        or second["rd_ohm"] > 1000 or second["vbias_v"] != first["vbias_v"]
    ):
        raise ValueError("diagnostic feedback RD step is not justified by the first raw result")
    expected = {
        "schema_version": 1, "status": "verified_two_run_diagnostic_feedback",
        "trace_id": trace_dir.name, "spec_id": spec.id, "seed": journal.seed,
        "searches_used": 2, "evaluations_used": 2,
        "candidate_bindings_verified": True,
        "parent_run_id": first["run_id"], "parent_manifest_sha256": first["manifest_sha256"],
        "results": results, "not_lna_result": True, "spec_pass": None,
    }
    return expected


def audit_diagnostic_feedback_agent(
    trace_dir: Path, runs_root: Path, *, template: Path, template_sha256: str,
    specs_path: Path,
) -> dict:
    expected = rebuild_diagnostic_feedback_summary(
        trace_dir, runs_root, template=template,
        template_sha256=template_sha256, specs_path=specs_path,
    )
    saved = json.loads((trace_dir / "diagnostic_feedback_summary.json").read_text(encoding="utf-8"))
    if saved != expected:
        raise ValueError("diagnostic feedback summary differs from independent raw audit")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of two OA common-source feedback rounds")
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    args = parser.parse_args()
    try:
        report = audit_diagnostic_feedback_agent(
            args.trace_dir, args.runs_root, template=args.template,
            template_sha256=args.template_sha256, specs_path=args.specs,
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_id={report['trace_id']} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
