from __future__ import annotations

from itertools import product


def normalize_power_ratios(power_ratio_list: list[float]) -> list[float]:
    total = sum(power_ratio_list)
    if total <= 0:
        raise ValueError("power ratios must sum to a positive value")
    return [x / total for x in power_ratio_list]


def active_sizing(power_ratio_list: list[float], total_current_ma: float, lookup_table: list[dict] | None = None) -> list[dict]:
    ratios = normalize_power_ratios(power_ratio_list)
    stage_currents = [total_current_ma * ratio for ratio in ratios]
    if lookup_table:
        return _from_lookup(stage_currents, lookup_table)
    return [
        {
            "stage": index + 1,
            "current_ma": current,
            "lookup_status": "missing",
            "note": "Populate from Cadence-generated gm/Id and impedance lookup table.",
        }
        for index, current in enumerate(stage_currents)
    ]


def enumerate_extreme_candidates(stage_options: list[list[dict]]) -> list[list[dict]]:
    if not stage_options:
        return []
    reduced = []
    for options in stage_options:
        if len(options) <= 2:
            reduced.append(options)
        else:
            reduced.append([options[0], options[-1]])
    return [list(combo) for combo in product(*reduced)]


def _from_lookup(stage_currents: list[float], lookup_table: list[dict]) -> list[dict]:
    selected = []
    for index, target in enumerate(stage_currents, start=1):
        matches = sorted(lookup_table, key=lambda row: abs(float(row["current_ma"]) - target))
        if not matches:
            raise ValueError("lookup table is empty")
        row = dict(matches[0])
        row["stage"] = index
        row["target_current_ma"] = target
        selected.append(row)
    return selected

