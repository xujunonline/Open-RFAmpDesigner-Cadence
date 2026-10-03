from __future__ import annotations

import argparse
import hashlib
import json
import math
import posixpath
import re
from pathlib import Path

from orfadc.agents.journal import inspect_journal
from orfadc.agents.remote_identity import read_remote_identity_snapshot, remote_identity
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.config_loader import write_json
from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path


_WARNING = re.compile(
    r"WARNING \(SFE-1131\): Scope option `scalefactor' specified with scope "
    r"`TopCircuit' at line `(\d+)' has also been specified at line `(\d+)' "
    r"in file `([^']+)'\. As a result, the last specified value will be used for simulation\."
)
_EFFECTIVE = re.compile(r"^\s*scalefactor\s*=\s*([0-9.eE+-]+)\s*$", re.MULTILINE)
_REMOTE_SCRIPT = r'''
import hashlib,json,math,pathlib,re,sys
items=json.loads(sys.argv[1])
output=[]
for item in items:
    path=pathlib.Path(item["path"])
    line_no=item["line"]
    raw=path.read_bytes()
    lines=raw.decode("utf-8",errors="replace").splitlines()
    if not 0 < line_no <= len(lines):
        raise ValueError("referenced model line is missing")
    line=lines[line_no-1]
    if line.lstrip().startswith("//"):
        raise ValueError("referenced model line is a comment")
    match=re.search(r"\bscalefactor\s*=\s*([0-9.eE+-]+)(?=\s|$)",line)
    if not match:
        raise ValueError("referenced model line does not assign scalefactor")
    value=float(match.group(1))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("referenced model scale is invalid")
    output.append({"line":line_no,"value":value,
                   "path_sha256":hashlib.sha256(str(path).encode()).hexdigest(),
                   "model_sha256":hashlib.sha256(raw).hexdigest()})
print(json.dumps(output,allow_nan=False,separators=(",",":")))
'''


def probe_sfe1131(
    run_dir: Path, trace_dir: Path, output_dir: Path, runner: RemoteRunner, *,
    template: Path, template_sha256: str,
) -> dict:
    """Record only numeric duplicate-scale evidence; never copy commercial models."""
    for path in (run_dir, trace_dir, output_dir, template):
        _require_private_path(path)
    journal = inspect_journal(trace_dir, candidate_runs_root=_PRIVATE_ROOT)
    if (
        journal.disposition != "complete" or not journal.remote_identity_verified
        or not journal.candidate_bindings_verified or not journal.spec_verified
        or not journal.candidate_snapshots_verified
    ):
        raise ValueError("source diagnostic lacks a bound complete agent trace")
    events = [json.loads(line) for line in (trace_dir / "agent_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    start = events[0]
    bound_remote = read_remote_identity_snapshot(trace_dir, start["remote_identity_sha256"])
    if bound_remote != remote_identity(runner.config):
        raise ValueError("current remote endpoint differs from the source dispatch")
    refined = [event for event in events if event["action"] == "RefineCandidate"]
    if (
        len(refined) != 1 or refined[0].get("run_id") != run_dir.name
        or run_dir.resolve() != (
            _PRIVATE_ROOT / journal.spec_id / f"seed{journal.seed}"
            / refined[0]["candidate_id"] / run_dir.name
        ).resolve()
    ):
        raise ValueError("source diagnostic is not the trace-bound candidate")
    source = audit_active_diagnostic_candidate(
        run_dir, template=template, template_sha256=template_sha256,
    )
    if source.get("not_lna_result") is not True or source.get("spec_pass") is not None:
        raise ValueError("scale probe only accepts a raw-audited diagnostic")
    log_path = run_dir / "spectre.log"
    raw = log_path.read_bytes()
    log = raw.decode("utf-8", errors="replace")
    warnings = _WARNING.findall(log)
    if not warnings or log.count("WARNING (SFE-1131)") != len(warnings) or len(warnings) > 32:
        raise ValueError("SFE-1131 warnings are absent or not fully parseable")
    effective = _EFFECTIVE.findall(log)
    if len(effective) != 1:
        raise ValueError("effective Spectre scalefactor is ambiguous")
    effective_value = float(effective[0])
    if not math.isfinite(effective_value) or effective_value <= 0:
        raise ValueError("effective Spectre scalefactor is invalid")
    items = []
    for _, after, raw_path in warnings:
        normalized = posixpath.normpath(raw_path)
        if (
            not raw_path.startswith("/") or len(raw_path) > 512
            or not re.fullmatch(r"/[A-Za-z0-9._/+-]+", raw_path)
            or not re.fullmatch(r"/[A-Za-z0-9._/+-]+", normalized)
        ):
            raise ValueError("model path in Spectre log is unsafe")
        items.append({"path": normalized, "line": int(after)})
    response = runner.run_remote(
        ["python3", "-c", _REMOTE_SCRIPT, json.dumps(items, separators=(",", ":"))],
        timeout_seconds=30,
    )
    if not response.ok or len(response.stdout) > 8192:
        raise ValueError("remote scale option probe failed")
    try:
        observed = json.loads(response.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("remote scale option report is malformed") from exc
    if not isinstance(observed, list) or len(observed) != len(items):
        raise ValueError("remote scale option count differs")
    model_versions: dict[str, str] = {}
    for item, record in zip(items, observed, strict=True):
        if (
            not isinstance(record, dict)
            or set(record) != {"line", "value", "path_sha256", "model_sha256"}
            or type(record["line"]) is not int or record["line"] != item["line"]
            or record["path_sha256"] != hashlib.sha256(item["path"].encode()).hexdigest()
            or not isinstance(record["model_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["model_sha256"])
            or type(record["value"]) not in {int, float}
            or not math.isfinite(record["value"]) or record["value"] <= 0
        ):
            raise ValueError("remote scale option context differs")
        prior = model_versions.setdefault(record["path_sha256"], record["model_sha256"])
        if prior != record["model_sha256"]:
            raise ValueError("model file changed during the scale option probe")
    same_value = all(
        math.isclose(record["value"], effective_value, rel_tol=0, abs_tol=1e-12)
        for record in observed
    )
    report = {
        "schema_version": 1,
        "status": "observed_assignments_match_effective_value" if same_value else "observed_scale_conflict",
        "source_trace_id": trace_dir.name,
        "remote_identity_sha256": start["remote_identity_sha256"],
        "source_run_id": run_dir.name,
        "source_evidence_manifest_sha256": hashlib.sha256(
            (run_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "spectre_log_sha256": hashlib.sha256(raw).hexdigest(),
        "warning_count": len(warnings),
        "further_occurrences_suppressed": "Further occurrences of this warning will be suppressed." in log,
        "effective_scalefactor": effective_value,
        "referenced_assignments": observed,
        "model_warning_resolved": False,
        "pdk_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "scale_probe.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SFE-1131 scale-value probe; no model files copied")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    args = parser.parse_args()
    try:
        report = probe_sfe1131(
            args.run_dir, args.trace_dir, args.output_dir,
            RemoteRunner(load_remote_config(args.config)),
            template=args.template, template_sha256=args.template_sha256,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"scale option probe rejected: {type(exc).__name__}")
    print(f"status={report['status']} warnings={report['warning_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
