from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from orfadc.agents.reconcile_pending_teaching_three_stage import reconcile_pending_teaching_three_stage
from orfadc.cadence.remote_runner import (
    CommandResult, RemoteCadenceConfig, RemoteRunner, load_remote_config,
)
from orfadc.config_loader import load_specs, write_json
from orfadc.experiments.audit_teaching_three_stage_feedback_agent import (
    audit_teaching_three_stage_agent_feedback,
)
from orfadc.experiments.recover_teaching_three_stage_candidate import (
    recover_teaching_three_stage_candidate,
)
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.experiments.run_teaching_three_stage_feedback_agent import (
    run_teaching_three_stage_feedback_agent,
)


class NthReplySuppressedRunner(RemoteRunner):
    """Suppress one selected successful controller response after real Spectre exit."""

    def __init__(self, config: RemoteCadenceConfig, *, target_round: int) -> None:
        if type(target_round) is not int or target_round not in {1, 2}:
            raise ValueError("three-stage controlled reply loss supports only round 1 or 2")
        super().__init__(config)
        self.target_round = target_round
        self.spectre_calls = 0
        self.target_real_returncode: int | None = None
        self.target_reply_suppressed = False

    def run_remote(
        self, command: Sequence[str], *, cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        is_spectre = (
            len(command) == 10 and command[0] == self.config.spectre_bin
            and tuple(command[1:]) == (
                "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
                "+log", "spectre.log", "teaching_three_stage_probe.scs",
            )
        )
        if is_spectre:
            if self.spectre_calls >= 2 or cwd is None:
                raise ValueError("three-stage lost-reply probe permits exactly two Spectre runs")
            self.spectre_calls += 1
        result = super().run_remote(command, cwd=cwd, timeout_seconds=timeout_seconds)
        if is_spectre and self.spectre_calls == self.target_round:
            self.target_real_returncode = result.returncode
            if result.ok:
                self.target_reply_suppressed = True
                return CommandResult(
                    action=result.action, argv=result.argv, returncode=255,
                    stdout="", stderr="controlled teaching reply suppression",
                )
        return result


def probe_teaching_three_stage_agent_lost_reply(
    config_path: Path, specs_path: Path, runs_root: Path, trace_root: Path,
    *, seed: int = 0, target_round: int = 2,
) -> tuple[Path, dict]:
    config = load_remote_config(config_path)
    runner = NthReplySuppressedRunner(config, target_round=target_round)
    trace_dir, pending = run_teaching_three_stage_feedback_agent(
        config_path, specs_path, runs_root, trace_root,
        spec_id="S1", seed=seed, runner=runner,
    )
    if (
        pending["status"] != "pending_remote_evaluation"
        or pending["evaluations_used"] != target_round
        or runner.spectre_calls != target_round
        or runner.target_real_returncode != 0
        or not runner.target_reply_suppressed
    ):
        raise ValueError("controlled lost reply did not yield a bounded pending run")
    adopted_dir = (
        runs_root / "S1" / f"seed{seed}" / pending["pending_candidate_id"]
        / pending["pending_run_id"]
    )
    recovery = recover_teaching_three_stage_candidate(adopted_dir, RemoteRunner(config))
    if recovery["status"] != "verified_recovered":
        raise ValueError("controlled source was not recovered from remote raw data")
    spec = next(item for item in load_specs(specs_path) if item.id == "S1")
    reconciliation = reconcile_pending_teaching_three_stage(
        trace_dir, runs_root, spec, seed=seed,
        config_path=config_path, specs_path=specs_path,
        runner=RemoteRunner(config),
    )
    summary = audit_teaching_three_stage_agent_feedback(trace_dir, runs_root, spec)
    if (
        reconciliation["status"] != (
            "reconciled_existing_first_then_new_second" if target_round == 1
            else "reconciled_existing_second_archive"
        )
        or summary["status"] != "verified_two_run_teaching_agent_feedback"
    ):
        raise ValueError("controlled three-stage agent feedback was not independently auditable")
    report = {
        "schema_version": 1,
        "status": "controlled_first_reply_loss_reconciled" if target_round == 1
        else "controlled_second_reply_loss_reconciled",
        "trace_id": trace_dir.name,
        "first_run_relative": summary["first_run_relative"],
        "second_run_relative": summary["second_run_relative"],
        "lost_reply_round": target_round,
        "spectre_calls_before_recovery": runner.spectre_calls,
        "target_real_returncode": runner.target_real_returncode,
        "target_reply_suppressed": runner.target_reply_suppressed,
        "recovery_dispatched_spectre": False,
        "reconciliation_redispatched_adopted_run": reconciliation["adopted_run_redispatched"],
        "new_second_dispatched_after_first_recovery": reconciliation["new_second_dispatched"],
        "physical_ssh_disconnect_tested": False,
        "not_lna_result": True, "spec_pass": None,
    }
    write_json(trace_dir / "controlled_lost_reply_report.json", report)
    return trace_dir, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a controlled first- or second-round lost-reply teaching-agent probe")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    parser.add_argument("--runs-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_candidates")
    parser.add_argument("--trace-root", type=Path, default=_PRIVATE_ROOT / "teaching_three_stage_agent_feedback")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--target-round", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    try:
        trace, report = probe_teaching_three_stage_agent_lost_reply(
            args.config, args.specs, args.runs_root, args.trace_root,
            seed=args.seed, target_round=args.target_round,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, StopIteration) as exc:
        parser.error(type(exc).__name__)
    print(f"status={report['status']} trace_dir={trace.resolve()} not_lna_result=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
