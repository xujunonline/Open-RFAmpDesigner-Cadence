from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from orfadc.experiments.audit_active_diagnostic_candidate import audit_active_diagnostic_candidate
from orfadc.schemas import Candidate, Spec

from .refiner import Refiner
from .searcher import Searcher


@dataclass(frozen=True)
class DiagnosticProposal:
    rd_ohm: float
    vbias_v: float
    parent_run_id: str
    parent_manifest_sha256: str


class DiagnosticFeedbackRefiner(Refiner):
    """Propose one diagnostic RD step only from audited Cadence raw data."""

    def __init__(self, *, template: Path, template_sha256: str, rd_step_fraction: float = 0.1) -> None:
        if type(rd_step_fraction) not in {int, float} or not math.isfinite(rd_step_fraction) or not 0 < rd_step_fraction <= 0.25:
            raise ValueError("diagnostic RD step must be finite and in (0, 0.25]")
        self.template = template
        self.template_sha256 = template_sha256
        self.rd_step_fraction = float(rd_step_fraction)
        self._proposal: DiagnosticProposal | None = None
        self._proposals_created = 0

    def take_proposal(self) -> DiagnosticProposal | None:
        proposal = self._proposal
        self._proposal = None
        return proposal

    def refine_from_run(self, candidate: Candidate, run_dir: Path, spec: Spec) -> Candidate:
        self._proposal = None
        if self._proposals_created:
            candidate.status = "needs_evaluation"
            candidate.notes.append("Diagnostic feedback budget is exhausted; no LNA acceptance is available.")
            return candidate
        try:
            evidence = audit_active_diagnostic_candidate(
                run_dir, template=self.template, template_sha256=self.template_sha256,
            )
            metrics = evidence["metrics"]
            manifest = (run_dir / "evidence_manifest.json").read_bytes()
        except (OSError, ValueError, TypeError, KeyError):
            candidate.status = "needs_evaluation"
            candidate.notes.append("A matching raw Cadence diagnostic is required before feedback.")
            return candidate
        if (
            evidence.get("candidate") != candidate.to_dict()
            or evidence.get("spec") != asdict(spec)
            or evidence.get("run_id") != run_dir.name
            or evidence.get("status") not in {"ok", "ok_with_warnings"}
            or evidence.get("simulation_status") != "ok"
            or evidence.get("not_lna_result") is not True
            or evidence.get("spec_pass") is not None
            or type(metrics.get("s21_db")) not in {int, float}
            or not math.isfinite(metrics["s21_db"])
        ):
            candidate.status = "needs_evaluation"
            candidate.notes.append("Diagnostic feedback source does not match this candidate/spec.")
            return candidate
        rd = candidate.active_params.get("rd_ohm")
        vbias = candidate.active_params.get("vbias_v")
        if (
            type(rd) not in {int, float} or not math.isfinite(rd) or not 50 <= rd <= 1000
            or type(vbias) not in {int, float} or not math.isfinite(vbias) or not 0.4 <= vbias <= 0.8
            or metrics["s21_db"] >= spec.gain_db
        ):
            candidate.status = "needs_evaluation"
            candidate.notes.append("No bounded diagnostic RD step is justified by measured gain.")
            return candidate
        next_rd = round(float(rd) * (1 + self.rd_step_fraction), 9)
        if next_rd <= rd or next_rd > 1000:
            candidate.status = "needs_evaluation"
            candidate.notes.append("The diagnostic RD bound prevents another candidate.")
            return candidate
        self._proposal = DiagnosticProposal(
            rd_ohm=next_rd, vbias_v=float(vbias), parent_run_id=run_dir.name,
            parent_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        )
        self._proposals_created += 1
        candidate.status = "diagnostic_refinement_proposed"
        candidate.notes.append("One audited common-source gain diagnostic prompted an RD step; not LNA sizing.")
        return candidate


class DiagnosticFeedbackSearcher(Searcher):
    def __init__(self, refiner: DiagnosticFeedbackRefiner, *, rd_ohm: float, vbias_v: float) -> None:
        if type(rd_ohm) not in {int, float} or not math.isfinite(rd_ohm) or not 50 <= rd_ohm <= 1000:
            raise ValueError("diagnostic RD must be finite and in [50, 1000]")
        if type(vbias_v) not in {int, float} or not math.isfinite(vbias_v) or not 0.4 <= vbias_v <= 0.8:
            raise ValueError("diagnostic VBIAS must be finite and in [0.4, 0.8]")
        self.refiner = refiner
        self.rd_ohm = float(rd_ohm)
        self.vbias_v = float(vbias_v)
        self.search_calls = 0
        self.used_proposal: DiagnosticProposal | None = None

    def initial_candidate(self, spec: Spec, seed: int) -> Candidate:
        return Candidate(
            candidate_id=f"{spec.id}_seed{seed}_oa_feedback0",
            spec_id=spec.id, seed=seed, power_ratio_list=[],
            active_params={"rd_ohm": self.rd_ohm, "vbias_v": self.vbias_v},
            status="active_common_source_diagnostic", notes=[],
        )

    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        index = self.search_calls
        self.search_calls += 1
        if index == 0:
            return [self.initial_candidate(spec, seed)]
        elif index == 1:
            proposal = self.refiner.take_proposal()
            if proposal is None:
                return []
            rd, vbias = proposal.rd_ohm, proposal.vbias_v
            self.used_proposal = proposal
        else:
            return []
        return [Candidate(
            candidate_id=f"{spec.id}_seed{seed}_oa_feedback{index}",
            spec_id=spec.id, seed=seed, power_ratio_list=[],
            active_params={"rd_ohm": rd, "vbias_v": vbias},
            status="active_common_source_diagnostic", notes=[],
        )]
