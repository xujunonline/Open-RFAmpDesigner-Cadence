from __future__ import annotations

from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.observe_teaching_three_stage_candidate import (
    observe_teaching_three_stage_candidate,
)
from orfadc.experiments.run_teaching_three_stage_refinement import _proposal
from orfadc.schemas import Candidate, Spec

from .refiner import Refiner
from .searcher import Searcher


class TeachingThreeStageRefiner(Refiner):
    """Offer one passive teaching step only after a source-audited first run."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root
        self._pending_proposal: Candidate | None = None
        self.proposals_created = 0
        self.parent_manifest_sha256: str | None = None

    def take_proposal(self) -> Candidate | None:
        proposed = self._pending_proposal
        self._pending_proposal = None
        return proposed

    def refine_from_run(self, candidate: Candidate, run_dir: Path, spec: Spec) -> Candidate:
        if self.proposals_created:
            try:
                observe_teaching_three_stage_candidate(run_dir, spec, candidate)
            except (OSError, ValueError, TypeError, KeyError):
                candidate.notes.append("Second teaching source is not independently auditable.")
            else:
                candidate.notes.append("Two small-signal teaching runs do not qualify an LNA.")
            candidate.status = "needs_evaluation"
            return candidate
        try:
            evidence = read_evidenced_metrics(run_dir)
            if evidence.get("candidate") != candidate.to_dict():
                raise ValueError("first candidate differs from its source archive")
            proposed, observation, _ = _proposal(run_dir, self.runs_root, spec, candidate.seed)
        except (OSError, ValueError, TypeError, KeyError):
            candidate.status = "needs_evaluation"
            candidate.notes.append("A matching raw three-stage result is required before refinement.")
            return candidate
        self._pending_proposal = proposed
        self.proposals_created = 1
        self.parent_manifest_sha256 = observation["evidence_manifest_sha256"]
        candidate.status = "teaching_refinement_proposed"
        candidate.notes.append("One audited output-network seed was proposed; no LNA pass is available.")
        return candidate


class TeachingThreeStageSearcher(Searcher):
    def __init__(self, refiner: TeachingThreeStageRefiner) -> None:
        self.refiner = refiner
        self.search_calls = 0
        self.used_proposal: Candidate | None = None

    @staticmethod
    def initial_candidate(spec: Spec, seed: int) -> Candidate:
        if spec.id != "S1" or type(seed) is not int or seed < 0:
            raise ValueError("teaching three-stage search supports only a nonnegative S1 seed")
        return Candidate(
            candidate_id=f"{spec.id}_seed{seed}_teach3_l3s2",
            spec_id=spec.id, seed=seed, power_ratio_list=[], active_params={},
            passive_params={"output_tune_ff": 0.0, "output_secondary_nh": 2.0},
            status="teaching_three_stage_diagnostic", notes=[],
        )

    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        index = self.search_calls
        self.search_calls += 1
        if index == 0:
            return [self.initial_candidate(spec, seed)]
        if index == 1:
            proposed = self.refiner.take_proposal()
            if proposed is not None and proposed.spec_id == spec.id and proposed.seed == seed:
                self.used_proposal = proposed
                return [proposed]
        return []
