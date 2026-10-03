from __future__ import annotations

import math
from typing import Any

from .tools.cost_functions import fullchain_violations


_PASS_METRIC_UNITS = {
    "s11_db": "dB",
    "s21_db": "dB",
    "nf_db": "dB",
    "ip1db_dbm": "dBm",
    "power_ma": "mA",
}


def validate_metrics_payload(payload: dict[str, Any]) -> None:
    """Validate the shared result envelope before it is persisted."""
    required = ("schema_version", "status", "simulation_status", "circuit_class", "not_lna_result", "spec_pass", "run_id")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"metrics payload missing fields: {', '.join(missing)}")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if not isinstance(payload["status"], str) or not payload["status"]:
        raise ValueError("status must be a nonempty string")
    if payload["simulation_status"] not in {"ok", "failed", "unknown"}:
        raise ValueError("invalid simulation_status")
    if not isinstance(payload["circuit_class"], str) or not payload["circuit_class"]:
        raise ValueError("circuit_class must be a nonempty string")
    if type(payload["not_lna_result"]) is not bool:
        raise ValueError("not_lna_result must be boolean")
    if payload["spec_pass"] is not None and type(payload["spec_pass"]) is not bool:
        raise ValueError("spec_pass must be boolean or null")
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise ValueError("run_id must be a nonempty string")
    _validate_optional_metadata(payload)

    if payload["status"] in {"ok", "ok_with_warnings"}:
        if payload["simulation_status"] != "ok" or not payload.get("source"):
            raise ValueError("successful result requires a successful simulation and source")
        if not isinstance(payload.get("metrics"), dict) or not payload["metrics"]:
            raise ValueError("successful result requires metrics")
    if payload["simulation_status"] == "ok" and not payload.get("source"):
        raise ValueError("successful simulation requires source")
    if payload["not_lna_result"] and payload["spec_pass"] is not None:
        raise ValueError("non-LNA result must leave spec_pass null")
    if payload["spec_pass"] is True:
        if (
            payload["circuit_class"] != "active_lna"
            or payload["simulation_status"] != "ok"
            or payload.get("source") != "cadence_spectre"
        ):
            raise ValueError("spec_pass=true requires a verified active LNA result")
        _validate_active_pass(payload)

    _validate_candidate_context(payload)

    band = payload.get("frequency_band_ghz")
    if band is not None:
        if not isinstance(band, dict) or set(band) != {"low", "high"}:
            raise ValueError("frequency_band_ghz must contain low and high")
        low, high = band["low"], band["high"]
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in (low, high)):
            raise ValueError("frequency band limits must be finite numbers")
        if low <= 0 or high <= low:
            raise ValueError("frequency band must be positive and increasing")


def _validate_active_pass(payload: dict[str, Any]) -> None:
    if payload.get("frequency_band_ghz") is None:
        raise ValueError("active LNA pass requires a frequency band")
    metrics = payload.get("metrics")
    spec = payload.get("spec")
    candidate = payload.get("candidate")
    units = payload.get("units")
    planes = payload.get("reference_planes")
    analyses = payload.get("analysis")
    if not isinstance(metrics, dict) or not isinstance(spec, dict):
        raise ValueError("active LNA pass requires metrics and spec")
    if (
        not isinstance(candidate, dict)
        or not candidate.get("candidate_id")
        or not isinstance(spec.get("id"), str)
        or not spec["id"]
        or candidate.get("spec_id") != spec.get("id")
        or type(candidate.get("seed")) is not int
        or candidate["seed"] != payload.get("seed")
        or payload.get("seed") is None
        or payload.get("timeout_seconds") is None
    ):
        raise ValueError("active LNA pass requires matching candidate, seed and timeout")
    if not isinstance(units, dict) or any(
        units.get(name) != unit for name, unit in _PASS_METRIC_UNITS.items()
    ):
        raise ValueError("active LNA pass requires explicit metric units")
    if (
        not isinstance(planes, dict)
    ):
        raise ValueError("active LNA pass requires input/output reference planes")
    if not isinstance(analyses, list) or not {"dc", "sp", "noise", "compression"}.issubset(analyses):
        raise ValueError("active LNA pass requires dc, sp, noise and compression analyses")
    assessed = fullchain_violations(
        {
            **metrics,
            "source": payload["source"],
            "simulation_status": payload["simulation_status"],
            "circuit_class": payload["circuit_class"],
            "not_lna_result": payload["not_lna_result"],
        },
        spec,
    )
    if not assessed["pass"]:
        raise ValueError("spec_pass=true disagrees with complete active LNA violations")


def _validate_optional_metadata(payload: dict[str, Any]) -> None:
    for name in ("spec", "candidate", "violation"):
        value = payload.get(name)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{name} must be an object or null")
    seed = payload.get("seed")
    if seed is not None and (type(seed) is not int or seed < 0):
        raise ValueError("seed must be a nonnegative integer or null")
    timeout = payload.get("timeout_seconds")
    if timeout is not None and (type(timeout) is not int or timeout <= 0):
        raise ValueError("timeout_seconds must be a positive integer or null")
    analyses = payload.get("analysis")
    if analyses is not None and (
        not isinstance(analyses, list)
        or any(not isinstance(value, str) or not value for value in analyses)
        or len(analyses) != len(set(analyses))
    ):
        raise ValueError("analysis must list distinct nonempty names")
    units = payload.get("units")
    if units is not None and (
        not isinstance(units, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) or not value
               for key, value in units.items())
    ):
        raise ValueError("units must map metric names to unit strings")
    planes = payload.get("reference_planes")
    plane_ohms = _reference_plane_ohms(planes) if planes is not None else None
    port_ohms = payload.get("port_reference_ohm")
    if port_ohms is not None:
        if not isinstance(port_ohms, dict) or set(port_ohms) != {"input", "output"} or any(
            type(port_ohms[name]) not in {int, float}
            or not math.isfinite(port_ohms[name]) or port_ohms[name] <= 0
            for name in ("input", "output")
        ):
            raise ValueError("port_reference_ohm requires positive input/output impedances")
        if plane_ohms is not None and any(
            not math.isclose(plane_ohms[index], port_ohms[name], rel_tol=1e-12)
            for index, name in enumerate(("input", "output"))
        ):
            raise ValueError("reference_planes and port_reference_ohm disagree")


def _reference_plane_ohms(planes: Any) -> tuple[float, float]:
    common = {"input", "output", "z0_ohm"}
    separate = {"input", "output", "input_z0_ohm", "output_z0_ohm"}
    if (not isinstance(planes, dict) or set(planes) not in (common, separate)
            or any(not isinstance(planes.get(name), str) or not planes[name].strip()
                   for name in ("input", "output"))):
        raise ValueError("reference_planes requires named ports and one valid impedance form")
    names = ("z0_ohm",) if set(planes) == common else ("input_z0_ohm", "output_z0_ohm")
    if any(type(planes[name]) not in {int, float} or not math.isfinite(planes[name])
           or planes[name] <= 0 for name in names):
        raise ValueError("reference_planes requires positive finite port impedances")
    if len(names) == 1:
        return float(planes[names[0]]), float(planes[names[0]])
    return float(planes[names[0]]), float(planes[names[1]])


def _validate_candidate_context(payload: dict[str, Any]) -> None:
    spec = payload.get("spec")
    candidate = payload.get("candidate")
    if spec is None and candidate is None:
        return
    if not isinstance(spec, dict) or not isinstance(candidate, dict):
        raise ValueError("candidate context requires both spec and candidate")
    if not isinstance(spec.get("id"), str) or not spec["id"].strip():
        raise ValueError("candidate context requires a nonempty spec id")
    if not isinstance(candidate.get("candidate_id"), str) or not candidate["candidate_id"].strip():
        raise ValueError("candidate context requires a nonempty candidate id")
    if candidate.get("spec_id") != spec["id"]:
        raise ValueError("candidate spec_id must match the run spec id")
    if type(payload.get("seed")) is not int or candidate.get("seed") != payload["seed"]:
        raise ValueError("candidate seed must match the run seed")
    if type(payload.get("timeout_seconds")) is not int or payload["timeout_seconds"] <= 0:
        raise ValueError("candidate context requires a positive timeout_seconds")
