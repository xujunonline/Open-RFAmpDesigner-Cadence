from __future__ import annotations

import math
import re
from itertools import product


_LOOKUP_TEXT_FIELDS = ("model_kind", "technology_id", "model_revision", "corner")
_LOOKUP_NUMERIC_FIELDS = ("current_ma", "w_um", "l_um", "vgs_v", "gm_s", "gds_s", "cgs_f", "cgd_f")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def normalize_power_ratios(power_ratio_list: list[float]) -> list[float]:
    if not power_ratio_list or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        for value in power_ratio_list
    ):
        raise ValueError("power ratios must be finite and nonnegative")
    try:
        total = math.fsum(power_ratio_list)
    except OverflowError as exc:
        raise ValueError("power ratios must have a finite positive sum") from exc
    if not math.isfinite(total) or total <= 0:
        raise ValueError("power ratios must have a finite positive sum")
    return [x / total for x in power_ratio_list]


def active_sizing(
    power_ratio_list: list[float], total_current_ma: float,
    lookup_table: list[dict] | None = None, lookup_context: dict | None = None,
) -> list[dict]:
    if isinstance(total_current_ma, bool) or not isinstance(total_current_ma, (int, float)) or not math.isfinite(total_current_ma) or total_current_ma <= 0:
        raise ValueError("total_current_ma must be finite and positive")
    ratios = normalize_power_ratios(power_ratio_list)
    stage_currents = [total_current_ma * ratio for ratio in ratios]
    if lookup_table is not None:
        return _from_lookup(stage_currents, lookup_table, lookup_context)
    if lookup_context is not None:
        raise ValueError("lookup context requires a lookup table")
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


def _validated_context(context: dict | None) -> dict:
    if not isinstance(context, dict) or set(context) != {*_LOOKUP_TEXT_FIELDS, "temperature_c"}:
        raise ValueError("lookup requires exact model provenance context")
    if context["model_kind"] not in {"authorized_pdk", "teaching_model"}:
        raise ValueError("lookup model kind is unsupported")
    if any(
        not isinstance(context[key], str) or not _SAFE_ID.fullmatch(context[key])
        for key in _LOOKUP_TEXT_FIELDS
    ):
        raise ValueError("lookup context contains an unsafe identifier")
    temperature = context["temperature_c"]
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or temperature <= -273.15:
        raise ValueError("lookup temperature must be finite and physical")
    return context


def _from_lookup(stage_currents: list[float], lookup_table: list[dict], context: dict | None) -> list[dict]:
    expected = _validated_context(context)
    if not isinstance(lookup_table, list) or not lookup_table:
        raise ValueError("lookup table is empty")
    for row in lookup_table:
        if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict):
            raise ValueError("lookup row is missing provenance metadata")
        if _validated_context(row["metadata"]) != expected:
            raise ValueError("lookup row belongs to another model context")
        if not isinstance(row.get("source_run_id"), str) or not _SAFE_ID.fullmatch(row["source_run_id"]):
            raise ValueError("lookup row is missing a safe source run ID")
        if type(row.get("stage")) is not int or row["stage"] < 1:
            raise ValueError("lookup stage must be a positive integer")
        for key in _LOOKUP_NUMERIC_FIELDS:
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"lookup {key} must be finite")
            if key not in {"vgs_v", "gds_s", "cgs_f", "cgd_f"} and value <= 0:
                raise ValueError(f"lookup {key} must be positive")
            if key in {"gds_s", "cgs_f", "cgd_f"} and value < 0:
                raise ValueError(f"lookup {key} must be nonnegative")
    selected = []
    for index, target in enumerate(stage_currents, start=1):
        matches = sorted(
            (
                row for row in lookup_table
                if row.get("stage") == index
                and row["current_ma"] <= target
            ),
            key=lambda row: target - row["current_ma"],
        )
        if not matches:
            raise ValueError(f"no lookup row within current budget for stage {index}")
        row = dict(matches[0])
        row["stage"] = index
        row["target_current_ma"] = target
        row["lookup_status"] = "metadata_matched_unverified"
        selected.append(row)
    return selected
