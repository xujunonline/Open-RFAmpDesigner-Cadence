from __future__ import annotations

from ..schemas import Candidate


class Refiner:
    def refine(self, candidate: Candidate, violations: dict[str, float]) -> Candidate:
        if violations.get("nf_violation", 0.0) > 0:
            candidate.notes.append("Increase NF headroom and rerun Stage 2.")
            candidate.status = "retry_stage2"
        elif violations.get("gain_violation", 0.0) > 0 or violations.get("ripple_violation", 0.0) > 0:
            candidate.notes.append("Rerun Stage 3 band planning with tighter gain distribution.")
            candidate.status = "retry_stage3"
        elif violations.get("ip1db_violation", 0.0) > 0:
            candidate.notes.append("Reallocate gain/current to improve linearity.")
            candidate.status = "retry_stage1_or_stage3"
        else:
            candidate.status = "accepted"
        return candidate

