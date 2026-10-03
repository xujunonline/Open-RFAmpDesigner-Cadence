from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Sequence

from orfadc.cadence.remote_runner import (
    CommandResult, RemoteCadenceConfig, RemoteRunner, load_remote_config,
)
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_agent_diagnostic import run_diagnostic_agent


class LostReplyAfterSpectreRunner(RemoteRunner):
    """Run Spectre once, then report a lost controller reply for this probe only."""

    def __init__(self, config: RemoteCadenceConfig) -> None:
        super().__init__(config)
        self.spectre_calls = 0
        self.actual_returncode: int | None = None
        self.reply_suppressed = False
        self.dispatch_starting = Event()
        self.spectre_remote_dir: str | None = None

    def run_remote(
        self, command: Sequence[str], *, cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        is_spectre = (
            len(command) == 10 and command[0] == self.config.spectre_bin
            and tuple(command[1:]) == (
                "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
                "+log", "spectre.log", "netlist.scs",
            )
        )
        if is_spectre:
            if self.spectre_calls or cwd is None:
                raise ValueError("lost-reply probe permits exactly one Spectre dispatch")
            if not PurePosixPath(cwd).is_absolute():
                raise ValueError("lost-reply probe requires an absolute Spectre run directory")
            self.spectre_calls += 1
            self.spectre_remote_dir = cwd
            self.dispatch_starting.set()
        result = super().run_remote(command, cwd=cwd, timeout_seconds=timeout_seconds)
        if is_spectre:
            self.actual_returncode = result.returncode
            if result.ok:
                self.reply_suppressed = True
                return CommandResult(
                    action=result.action, argv=result.argv, returncode=255,
                    stdout="", stderr="controlled lost-reply probe after remote Spectre exit",
                )
        return result


def probe_lost_reply_recovery(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path, *,
    template: Path, template_sha256: str, spec_id: str, seed: int,
    rd_ohm: float, vbias_v: float,
    runner: LostReplyAfterSpectreRunner | None = None,
) -> tuple[Path, dict]:
    _require_private_path(runs_root)
    _require_private_path(trace_root)
    _require_private_path(template)
    runner = runner or LostReplyAfterSpectreRunner(load_remote_config(config_path))
    trace_dir, index = run_diagnostic_agent(
        config_path, specs_path, runs_root, trace_root,
        template=template, template_sha256=template_sha256,
        spec_id=spec_id, seed=seed, rd_ohm=rd_ohm, vbias_v=vbias_v,
        runner=runner,
    )
    report = {
        "schema_version": 1,
        "mode": "real_spectre_then_controller_reply_suppressed",
        "trace_id": trace_dir.name,
        "candidate_run_id": index.get("candidate_run_id"),
        "spectre_calls": runner.spectre_calls,
        "actual_remote_returncode": runner.actual_returncode,
        "reply_suppressed": runner.reply_suppressed,
        "pending_execution_status": index["execution_status"],
        "not_lna_result": True,
        "spec_pass": None,
    }
    write_json(trace_dir / "lost_reply_probe.json", report)
    if runner.reply_suppressed and (
        runner.spectre_calls != 1 or runner.actual_returncode != 0
        or index["execution_status"] != "pending_remote_evaluation"
    ):
        raise ValueError("real Spectre reply suppression did not yield a pending agent run")
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a bounded lost reply after one real Spectre run")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT)
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "agent_lost_reply_probe")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rd-ohm", type=float, required=True)
    parser.add_argument("--vbias-v", type=float, required=True)
    args = parser.parse_args()
    try:
        trace_dir, report = probe_lost_reply_recovery(
            args.config, args.specs, args.runs_root, args.trace_root,
            template=args.template, template_sha256=args.template_sha256,
            spec_id=args.spec, seed=args.seed,
            rd_ohm=args.rd_ohm, vbias_v=args.vbias_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(
        f"trace_dir={trace_dir.resolve()} actual_returncode={report['actual_remote_returncode']} "
        f"pending={report['pending_execution_status']}"
    )
    return 0 if report["reply_suppressed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
