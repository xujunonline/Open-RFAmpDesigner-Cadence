from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.experiments import run_hb_sweep as module


def test_hb_sweep_brackets_compression_from_verified_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    powers = [-60.0, -50.0, -40.0, -30.0, -20.0]
    gains = [10.0, 10.0, 10.0, 9.5, 8.0]
    results: dict[str, dict] = {}
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)

    def fake_run(config: Path, run_dir: Path, *, input_dbm: float, **kwargs) -> dict:
        run_dir.mkdir()
        gain = gains[powers.index(input_dbm)]
        result = {
            "status": "hb_fundamental_extracted", "source": "cadence_spectre",
            "simulation_status": "ok", "not_lna_result": True, "spec_pass": None,
            "parameters": {"input_dbm": input_dbm, "rd_ohm": 150, "vbias_v": 0.67,
                           "frequency_ghz": 10.0, "harmonics": 7},
            "metrics": {"output_power_dbm": input_dbm + gain, "power_gain_db": gain,
                        "small_signal_s21_db": 10.0, "hb_minus_s21_db": gain - 10.0},
        }
        results[run_dir.name] = result
        return result

    monkeypatch.setattr(module, "run_hb_diagnostic", fake_run)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: results[path.name])
    sweep = tmp_path / "sweep"
    summary = module.run_hb_sweep(
        tmp_path / "config", sweep, template=tmp_path / "template", template_sha256="0" * 64,
        rd_ohm=150, vbias_v=0.67, input_powers_dbm=powers,
    )
    assert summary["status"] == "ok"
    assert summary["compression"]["ip1db_dbm"] == pytest.approx(-26.6666666667)
    assert summary["compression"]["op1db_dbm"] == pytest.approx(-17.6666666667)
    assert summary["points_completed"] == 5
    assert (sweep / "power_sweep.csv").is_file()
    assert (sweep / "summary.json").is_file()


def test_hb_sweep_rejects_unsorted_without_creating_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    sweep = tmp_path / "sweep"
    with pytest.raises(ValueError, match="strictly increasing"):
        module.run_hb_sweep(
            tmp_path / "config", sweep, template=tmp_path / "template", template_sha256="0" * 64,
            rd_ohm=150, vbias_v=0.67, input_powers_dbm=[-60, -50, -40, -40],
        )
    assert not sweep.exists()


def test_hb_sweep_reports_unbracketed_without_extrapolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    powers = [-60.0, -50.0, -40.0, -30.0]
    results: dict[str, dict] = {}
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)

    def fake_run(config: Path, run_dir: Path, *, input_dbm: float, **kwargs) -> dict:
        run_dir.mkdir()
        gain = 9.9 if input_dbm == -30.0 else 10.0
        result = {
            "status": "hb_fundamental_extracted", "source": "cadence_spectre",
            "simulation_status": "ok", "not_lna_result": True, "spec_pass": None,
            "parameters": {"input_dbm": input_dbm, "rd_ohm": 150, "vbias_v": 0.67,
                           "frequency_ghz": 10.0, "harmonics": 7},
            "metrics": {"output_power_dbm": input_dbm + gain, "power_gain_db": gain,
                        "small_signal_s21_db": 10.0, "hb_minus_s21_db": gain - 10.0},
        }
        results[run_dir.name] = result
        return result

    monkeypatch.setattr(module, "run_hb_diagnostic", fake_run)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: results[path.name])
    summary = module.run_hb_sweep(
        tmp_path / "config", tmp_path / "sweep", template=tmp_path / "template",
        template_sha256="0" * 64, rd_ohm=150, vbias_v=0.67, input_powers_dbm=powers,
    )
    assert summary["status"] == "unbracketed"
    assert summary["compression"]["ip1db_dbm"] is None
    assert summary["compression"]["op1db_dbm"] is None


def test_hb_sweep_preserves_backend_failure_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda path: None)

    def failed_run(config: Path, run_dir: Path, **kwargs) -> dict:
        run_dir.mkdir()
        return {"status": "spectre_failed"}

    monkeypatch.setattr(module, "run_hb_diagnostic", failed_run)
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: {"status": "spectre_failed"})
    summary = module.run_hb_sweep(
        tmp_path / "config", tmp_path / "sweep", template=tmp_path / "template",
        template_sha256="0" * 64, rd_ohm=150, vbias_v=0.67,
        input_powers_dbm=[-60, -50, -40, -30],
    )
    assert summary["status"] == "incomplete"
    assert summary["failures"][0]["backend_status"] == "spectre_failed"
    assert summary["points_completed"] == 0
