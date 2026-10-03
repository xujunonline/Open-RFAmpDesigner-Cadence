from __future__ import annotations

import json
from pathlib import Path

import pytest

from orfadc.experiments import audit_teaching_hb as module


_FUNDAMENTAL = {
    "fundamental_hz": 10e9, "vout_peak_v": 0.01, "iout_peak_a": 0.0002,
    "output_power_dbm": -30.0, "load_current_relative_error": 0.0,
}


def _archive(root: Path, *, warning: bool = False) -> tuple[Path, dict]:
    run = root / "point_00"
    run.mkdir()
    (run / "netlist.scs").write_text(
        "// not foundry data\n"
        "parameters VDD=1.2 VBIAS=0.65 WMOS=300u LMOS=100n LGS=1n LSS=240p LDD=2n\n"
        "model n_teach mos1 type=n\n"
        "dcOpInfo info what=oppoint where=rawfile\n"
        "PORT1 (in 0) port r=50 num=1 type=sine dbm=-50 freq=10000000000\n"
        "PORT2 (out 0) port r=50 num=2 type=dc\n"
        "hb hb fundfreqs=[10000000000] maxharms=[7] annotate=status\n",
        encoding="ascii",
    )
    (run / "spectre.log").write_text(
        f"spectre completes with 0 errors, {1 if warning else 0} warnings, and 0 notices.\n",
        encoding="utf-8",
    )
    artifacts = dict(module._RAW, op_raw="dcOpInfo.info")
    (run / "evidence_manifest.json").write_text(
        json.dumps({"artifacts": {key: {"path": value} for key, value in artifacts.items()}}),
        encoding="utf-8",
    )
    metrics = {
        **_FUNDAMENTAL, "input_available_power_dbm": -50.0, "power_gain_db": 20.0,
        "small_signal_s21_db": 20.0, "hb_minus_s21_db": 0.0,
    }
    payload = {
        "status": "hb_fundamental_extracted", "simulation_status": "ok",
        "source": "cadence_spectre", "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model", "not_lna_result": True, "spec_pass": None,
        "run_id": run.name,
        "parameters": {"input_dbm": -50.0, "frequency_ghz": 10.0,
                       "harmonics": 7, "vbias_v": 0.65},
        "metrics": metrics,
        "reference_planes": {"input": "PORT1_available_power", "output": "PORT2_50ohm_load",
                             "z0_ohm": 50.0},
    }
    return run, payload


def test_teaching_hb_audit_recomputes_source_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, payload = _archive(tmp_path)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda _: payload)
    monkeypatch.setattr(module, "extract_hb_fundamental_power", lambda *args, **kwargs: _FUNDAMENTAL)
    monkeypatch.setattr(module, "extract_sp_s21_at_frequency", lambda *args: 20.0)
    assert module.audit_teaching_hb(run)["status"] == "verified"
    payload["metrics"]["power_gain_db"] = 19.0
    with pytest.raises(ValueError, match="power_gain_db"):
        module.audit_teaching_hb(run)


def test_teaching_hb_audit_rejects_warning_even_with_stored_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, payload = _archive(tmp_path, warning=True)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda _: payload)
    with pytest.raises(ValueError, match="zero warnings"):
        module.audit_teaching_hb(run)
