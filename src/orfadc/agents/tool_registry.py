from __future__ import annotations

import math
import re
from typing import Any

from ..schemas import Candidate, Spec
from ..tools.active_sizing import active_sizing


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_TOOL_ARGUMENTS = {
    "active_sizing": frozenset({"power_ratio_list", "total_current_ma"}),
    "impedance_matching": frozenset({"candidate_id", "nf_headroom_db"}),
    "band_planning": frozenset({"candidate_id", "gain_require_list"}),
    "fullchain_eval": frozenset({"candidate_id"}),
}


def _finite_number(value: object, name: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite JSON number")
    return float(value)


class AgentToolRegistry:
    """Constrain agent actions; unimplemented Cadence tools never emit measured scores."""

    def __init__(
        self, spec: Spec, *, lookup_table: list[dict] | None = None,
        lookup_context: dict | None = None,
    ) -> None:
        if not isinstance(spec, Spec):
            raise TypeError("tool registry needs a validated Spec")
        self.spec = spec
        self.lookup_table = lookup_table
        self.lookup_context = lookup_context

    @staticmethod
    def tool_names() -> tuple[str, ...]:
        return tuple(_TOOL_ARGUMENTS)

    def invoke(self, request: dict[str, Any], *, candidate: Candidate | None = None) -> dict:
        if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
            raise ValueError("tool call must contain exactly tool and arguments")
        name = request["tool"]
        args = request["arguments"]
        if not isinstance(name, str) or name not in _TOOL_ARGUMENTS or not isinstance(args, dict) or set(args) != _TOOL_ARGUMENTS[name]:
            raise ValueError("unknown tool or invalid tool argument keys")
        if name == "active_sizing":
            if candidate is not None:
                raise ValueError("active sizing does not take an existing candidate")
            ratios = args["power_ratio_list"]
            total_current = _finite_number(args["total_current_ma"], "total_current_ma")
            if (
                not isinstance(ratios, list) or len(ratios) != 3
                or any(_finite_number(value, "power ratio") <= 0 for value in ratios)
                or not 0 < total_current <= self.spec.power_ma
            ):
                raise ValueError("three positive stage ratios and current within the spec budget are required")
            stages = active_sizing(
                ratios, total_current, self.lookup_table, self.lookup_context,
            )
            ready = all(stage.get("lookup_status") == "verified" for stage in stages)
            return {
                "tool": name,
                "status": "active_sizing_ready" if ready else "needs_verified_active_lookup",
                "stages": stages,
                "spec_id": self.spec.id,
                "not_lna_result": True,
                "spec_pass": None,
            }

        candidate_id = args["candidate_id"]
        if (
            not isinstance(candidate_id, str) or not _SAFE_ID.fullmatch(candidate_id)
            or not isinstance(candidate, Candidate)
            or candidate.candidate_id != candidate_id
            or candidate.spec_id != self.spec.id
        ):
            raise ValueError("tool call needs a matching trusted candidate")
        if name == "impedance_matching":
            headroom = _finite_number(args["nf_headroom_db"], "nf_headroom_db")
            if not 0 <= headroom <= 6:
                raise ValueError("NF headroom is outside the 0..6 dB policy range")
            status = "needs_verified_active_lookup"
            stages = candidate.active_params.get("stages") if isinstance(candidate.active_params, dict) else None
            if isinstance(stages, list) and len(stages) == 3 and all(
                isinstance(stage, dict) and stage.get("lookup_status") == "verified"
                for stage in stages
            ):
                status = "matching_backend_unavailable"
        elif name == "band_planning":
            targets = args["gain_require_list"]
            if (
                not isinstance(targets, list) or len(targets) != 3
                or any(not -50 <= _finite_number(value, "gain target") <= 100 for value in targets)
            ):
                raise ValueError("three bounded gain targets are required")
            status = "band_planning_backend_unavailable"
        else:
            status = "fullchain_backend_unavailable"
        return {
            "tool": name,
            "status": status,
            "candidate_id": candidate_id,
            "spec_id": self.spec.id,
            "not_lna_result": True,
            "spec_pass": None,
        }
