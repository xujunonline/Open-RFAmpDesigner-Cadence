from __future__ import annotations

from ..schemas import Candidate, Spec
from .tool_registry import AgentToolRegistry


class Searcher:
    def __init__(self, power_ratio_options: list[list[float]] | None = None) -> None:
        self.power_ratio_options = power_ratio_options or [[0.4, 0.3, 0.3]]

    def search(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        candidates = []
        registry = AgentToolRegistry(spec)
        for index, ratios in enumerate(self.power_ratio_options):
            sizing = registry.invoke({
                "tool": "active_sizing",
                "arguments": {"power_ratio_list": ratios, "total_current_ma": spec.power_ma},
            })
            candidates.append(
                Candidate(
                    candidate_id=f"{spec.id}_seed{seed}_search{index}",
                    spec_id=spec.id,
                    seed=seed,
                    power_ratio_list=ratios,
                    active_params={"stages": sizing["stages"]},
                    status=sizing["status"],
                )
            )
        return candidates
