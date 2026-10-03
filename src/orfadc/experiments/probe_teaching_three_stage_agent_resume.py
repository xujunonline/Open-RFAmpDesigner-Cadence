from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from orfadc.agents.resume_teaching_three_stage_agent import resume_teaching_three_stage_agent
from orfadc.cadence.remote_runner import (
    CommandResult, RemoteCadenceConfig, RemoteRunner, load_remote_config,
)
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


def audit_teaching_three_stage_agent_resume_probe(
    trace_dir: Path, source_trace: Path, runs_root: Path, specs_path: Path,
) -> dict:
    for path in (trace_dir, source_trace, runs_root):
        _require_private_path(path)
    spec = next(item for item in load_specs(specs_path) if item.id == "S1")
    source = audit_teaching_three_stage_agent_feedback(source_trace, runs_root, spec)
    resumed = audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    if (
        resumed["first_run_relative"] != source["first_run_relative"]
        or resumed["second_run_relative"] == source["second_run_relative"]
        or (trace_dir / "agent_events.jsonl").read_bytes().splitlines(keepends=True)[:4]
        != (source_trace / "agent_events.jsonl").read_bytes().splitlines(keepends=True)[:4]
        or (trace_dir / "agent_candidates.jsonl").read_bytes().splitlines(keepends=True)[0]
        != (source_trace / "agent_candidates.jsonl").read_bytes().splitlines(keepends=True)[0]
        or (trace_dir / "agent_spec.json").read_bytes() != (source_trace / "agent_spec.json").read_bytes()
        or (trace_dir / "agent_remote.json").read_bytes() != (source_trace / "agent_remote.json").read_bytes()
    ):
        raise ValueError("teaching resume changed the source first round or reused the old second run")
    expected = {
        "schema_version": 1, "status": "verified_first_refinement_resume",
        "trace_id": trace_dir.name, "source_trace_id": source_trace.name,
        "source_trace_sha256": hashlib.sha256(
            (source_trace / "agent_trace.json").read_bytes()
        ).hexdigest(),
        "first_run_relative": resumed["first_run_relative"],
        "second_run_relative": resumed["second_run_relative"],
        "first_source_reused": True, "new_second_spectre_calls": 1,
        "first_redispatched": False, "not_lna_result": True, "spec_pass": None,
    }
    report_path = trace_dir / "resume_probe.json"
    if (
        not report_path.is_file() or report_path.is_symlink()
        or json.loads(report_path.read_text(encoding="utf-8")) != expected
    ):
        raise ValueError("teaching resume report differs from source-audited traces")
    return expected


class CountedTeachingSpectreRunner(RemoteRunner):
    def __init__(self, config: RemoteCadenceConfig) -> None:
        super().__init__(config)
        self.spectre_calls = 0

    def run_remote(
        self, command: Sequence[str], *, cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        if (
            len(command) == 10 and command[0] == self.config.spectre_bin
            and command[-1] == "teaching_three_stage_probe.scs"
        ):
            self.spectre_calls += 1
            if self.spectre_calls != 1:
                raise ValueError("teaching resume probe permits only one new Spectre dispatch")
        return super().run_remote(command, cwd=cwd, timeout_seconds=timeout_seconds)


def probe_teaching_three_stage_agent_resume(
    source_trace: Path, trace_root: Path, runs_root: Path,
    config_path: Path, specs_path: Path,
) -> tuple[Path, dict]:
    """Inject a pre-second-dispatch stop into an audited trace, then resume once."""
    for path in (source_trace, trace_root, runs_root):
        _require_private_path(path)
    if not source_trace.is_dir() or source_trace.is_symlink():
        raise ValueError("resume probe source trace is missing or unsafe")
    spec = next(item for item in load_specs(specs_path) if item.id == "S1")
    source = audit_teaching_three_stage_agent_feedback(source_trace, runs_root, spec)
    original_trace = source_trace / "agent_trace.json"
    original_hash = hashlib.sha256(original_trace.read_bytes()).hexdigest()
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    trace_dir.mkdir(exist_ok=False)
    for name in ("agent_remote.json", "agent_spec.json"):
        (trace_dir / name).write_bytes((source_trace / name).read_bytes())
    events = (source_trace / "agent_events.jsonl").read_bytes().splitlines(keepends=True)
    snapshots = (source_trace / "agent_candidates.jsonl").read_bytes().splitlines(keepends=True)
    if len(events) != 8 or len(snapshots) != 2:
        raise ValueError("resume probe source is not an exact two-round teaching trace")
    (trace_dir / "agent_events.jsonl").write_bytes(b"".join(events[:4]))
    (trace_dir / "agent_candidates.jsonl").write_bytes(snapshots[0])
    config = load_remote_config(config_path)
    runner = CountedTeachingSpectreRunner(config)
    resumed = resume_teaching_three_stage_agent(
        trace_dir, runs_root, spec, seed=0,
        config_path=config_path, specs_path=specs_path, runner=runner,
    )
    if resumed["status"] != "resumed_existing_first_then_new_second" or runner.spectre_calls != 1:
        raise ValueError("teaching resume did not complete one new second evaluation")
    summary = audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    if summary["first_run_relative"] != source["first_run_relative"]:
        raise ValueError("teaching resume replaced the already audited first source")
    report = {
        "schema_version": 1, "status": "verified_first_refinement_resume",
        "trace_id": trace_dir.name, "source_trace_id": source_trace.name,
        "source_trace_sha256": original_hash,
        "first_run_relative": summary["first_run_relative"],
        "second_run_relative": summary["second_run_relative"],
        "first_source_reused": True,
        "new_second_spectre_calls": runner.spectre_calls,
        "first_redispatched": False,
        "not_lna_result": True, "spec_pass": None,
    }
    write_json(trace_dir / "resume_probe.json", report)
    return trace_dir, audit_teaching_three_stage_agent_resume_probe(
        trace_dir, source_trace, runs_root, specs_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one audited pre-second-evaluation teaching resume probe")
    parser.add_argument("source_trace", type=Path)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_agent_resume")
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.audit_dir is not None:
            report = audit_teaching_three_stage_agent_resume_probe(
                args.audit_dir, args.source_trace, args.runs_root, args.specs,
            )
            print(f"status={report['status']} trace_dir={args.audit_dir.resolve()} not_lna_result=true")
            return 0
        trace, report = probe_teaching_three_stage_agent_resume(
            args.source_trace, args.trace_root, args.runs_root, args.config, args.specs,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, StopIteration) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_dir={trace.resolve()} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
