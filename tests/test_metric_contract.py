from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.metric_contract import validate_metrics_payload


def _passive_payload() -> dict:
    return {
        "schema_version": 1,
        "status": "ok",
        "simulation_status": "ok",
        "source": "cadence_spectre",
        "circuit_class": "passive_twoport",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": "rf_smoke_001",
        "frequency_band_ghz": {"low": 0.1, "high": 20.0},
        "metrics": {"s21_db": -3.0},
    }


def test_metrics_v1_accepts_passive_success_and_connection_failure() -> None:
    validate_metrics_payload(_passive_payload())
    failure = {
        "schema_version": 1,
        "status": "mkdir_failed",
        "simulation_status": "unknown",
        "circuit_class": "passive_twoport",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": "rf_smoke_002",
    }
    validate_metrics_payload(failure)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"source": None}, "source"),
        ({"spec_pass": True}, "non-LNA"),
        ({"frequency_band_ghz": {"low": 2.0, "high": 1.0}}, "positive and increasing"),
        ({"frequency_band_ghz": {"low": True, "high": 2.0}}, "finite numbers"),
        ({"simulation_status": "unknown"}, "successful result"),
    ],
)
def test_metrics_v1_rejects_invalid_success(updates: dict, message: str) -> None:
    payload = {**_passive_payload(), **updates}
    with pytest.raises(ValueError, match=message):
        validate_metrics_payload(payload)


def test_metrics_v1_requires_explicit_lna_provenance_for_spec_pass() -> None:
    payload = {**_passive_payload(), "not_lna_result": False, "spec_pass": True}
    with pytest.raises(ValueError, match="active LNA"):
        validate_metrics_payload(payload)
    payload["circuit_class"] = "active_lna"
    with pytest.raises(ValueError, match="metrics and spec"):
        validate_metrics_payload(payload)


def _active_payload() -> dict:
    return {
        **_passive_payload(),
        "circuit_class": "active_lna",
        "not_lna_result": False,
        "spec_pass": True,
        "analysis": ["dc", "sp", "noise", "compression"],
        "reference_planes": {"input": "PORT1", "output": "PORT2", "z0_ohm": 50.0},
        "units": {"s11_db": "dB", "s21_db": "dB", "nf_db": "dB", "ip1db_dbm": "dBm", "power_ma": "mA"},
        "metrics": {"s11_db": -15.0, "s21_db": 15.0, "nf_db": 2.0, "ip1db_dbm": -10.0, "power_ma": 5.0},
        "spec": {"id": "S1", "s11_max_db": -10.0, "gain_db": 10.0, "nf_max_db": 3.0, "ip1db_min_dbm": -15.0, "power_ma": 10.0},
        "candidate": {"candidate_id": "c001", "spec_id": "S1", "seed": 0},
        "seed": 0,
        "timeout_seconds": 300,
    }


def test_active_pass_requires_complete_consistent_evidence() -> None:
    validate_metrics_payload(_active_payload())
    invalid = _active_payload()
    invalid["metrics"].pop("ip1db_dbm")
    with pytest.raises(ValueError, match="violations"):
        validate_metrics_payload(invalid)
    invalid = _active_payload()
    invalid["metrics"]["nf_db"] = 4.0
    with pytest.raises(ValueError, match="violations"):
        validate_metrics_payload(invalid)
    invalid = _active_payload()
    invalid["units"]["power_ma"] = "mW"
    with pytest.raises(ValueError, match="units"):
        validate_metrics_payload(invalid)
    invalid = _active_payload()
    invalid["analysis"].remove("compression")
    with pytest.raises(ValueError, match="compression"):
        validate_metrics_payload(invalid)
    invalid = _active_payload()
    invalid["candidate"]["spec_id"] = "S2"
    with pytest.raises(ValueError, match="candidate"):
        validate_metrics_payload(invalid)
    invalid = _active_payload()
    invalid.pop("frequency_band_ghz")
    with pytest.raises(ValueError, match="frequency band"):
        validate_metrics_payload(invalid)


def test_candidate_context_is_consistent_even_without_spec_pass() -> None:
    payload = {
        **_passive_payload(),
        "spec": {"id": "S1"},
        "candidate": {"candidate_id": "c001", "spec_id": "S1", "seed": 2},
        "seed": 2,
        "timeout_seconds": 300,
    }
    validate_metrics_payload(payload)
    for key, value, message in (
        ("spec", None, "both spec and candidate"),
        ("seed", 3, "candidate seed"),
        ("timeout_seconds", None, "positive timeout"),
    ):
        with pytest.raises(ValueError, match=message):
            validate_metrics_payload({**payload, key: value})
    bad_candidate = {**payload["candidate"], "spec_id": "S2"}
    with pytest.raises(ValueError, match="spec_id"):
        validate_metrics_payload({**payload, "candidate": bad_candidate})


@pytest.mark.parametrize("updates", [{"seed": -1}, {"timeout_seconds": 0}, {"analysis": ["sp", "sp"]}])
def test_optional_run_metadata_is_validated(updates: dict) -> None:
    with pytest.raises(ValueError):
        validate_metrics_payload({**_passive_payload(), **updates})


def test_metrics_schema_file_declares_runtime_envelope() -> None:
    schema = json.loads(Path("config/metrics_v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == 1
    assert set(_passive_payload()).issuperset(schema["required"])


def test_mixed_port_references_are_explicit_and_consistent() -> None:
    payload = {
        **_passive_payload(),
        "reference_planes": {
            "input": "PORT1_50ohm", "output": "PORT2_differential_1787ohm",
            "input_z0_ohm": 50.0, "output_z0_ohm": 1787.0,
        },
        "port_reference_ohm": {"input": 50.0, "output": 1787.0},
    }
    validate_metrics_payload(payload)
    for bad in (
        {"input": 50.0, "output": True},
        {"input": 50.0, "output": -1787.0},
        {"input": 50.0},
    ):
        with pytest.raises(ValueError, match="port_reference_ohm"):
            validate_metrics_payload({**payload, "port_reference_ohm": bad})
    with pytest.raises(ValueError, match="disagree"):
        validate_metrics_payload({**payload, "port_reference_ohm": {"input": 50.0, "output": 50.0}})
    with pytest.raises(ValueError, match="impedance form"):
        validate_metrics_payload({**payload, "reference_planes": {
            **payload["reference_planes"], "z0_ohm": 50.0,
        }})


def test_active_pass_can_express_mixed_reference_planes() -> None:
    payload = _active_payload()
    payload["reference_planes"] = {
        "input": "PORT1", "output": "PORT2_diff",
        "input_z0_ohm": 50.0, "output_z0_ohm": 1787.0,
    }
    payload["port_reference_ohm"] = {"input": 50.0, "output": 1787.0}
    validate_metrics_payload(payload)
