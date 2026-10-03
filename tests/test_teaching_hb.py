from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments import run_teaching_hb as module


def _ok() -> CommandResult:
    return CommandResult("mock", (), 0, "", "")


def test_teaching_hb_renderer_is_bounded_and_keeps_dc_block() -> None:
    source = module.render_teaching_hb_netlist(-50)
    assert "CIN (in rf_in) capacitor c=5p" in source
    assert "PORT1 (in 0) port r=50 num=1 type=sine dbm=-50 freq=10000000000" in source
    assert "PORT2 (out 0) port r=50 num=2 type=dc" in source
    assert "hb hb fundfreqs=[10000000000] maxharms=[7]" in source
    assert "VBIAS=0.55000000000000004" in module.render_teaching_hb_netlist(-50, vbias_v=0.55)
    with pytest.raises(ValueError, match="-100..0"):
        module.render_teaching_hb_netlist(1)
    with pytest.raises(ValueError, match="-100..0"):
        module.render_teaching_hb_netlist(float("nan"))
    with pytest.raises(ValueError, match="VBIAS"):
        module.render_teaching_hb_netlist(-50, vbias_v=0.8)
    with pytest.raises(ValueError, match="SP grid"):
        module.render_teaching_hb_netlist(-50, frequency_ghz=10.05)


def test_matched_hb_uses_the_same_whitelisted_circuit_and_band_grid() -> None:
    source = module.render_teaching_hb_netlist(
        -50, ldd_nh=1.688093092794574, cblock_ff=225.0790790392765,
        rdamp_ohm=150, sp_start_ghz=8, sp_stop_ghz=12, sp_intervals=160,
    )
    assert "RDAMP (vdd drain) resistor r=150" in source
    assert "sp sp start=8G stop=12G lin=160" in source
    assert "PORT1 (in 0) port r=50 num=1 type=sine dbm=-50 freq=10000000000" in source
    with pytest.raises(ValueError, match="SP grid"):
        module.render_teaching_hb_netlist(
            -50, frequency_ghz=10.01, sp_start_ghz=8, sp_stop_ghz=12, sp_intervals=160,
        )


def test_teaching_hb_rejects_warning_point_but_archives_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class WarningRunner:
        config = RemoteCadenceConfig(host="example.test", user="test", remote_root="/tmp/test")

        @staticmethod
        def ensure_remote_dir(path: str) -> CommandResult:
            return _ok()

        @staticmethod
        def upload(source: Path, destination: str) -> CommandResult:
            return _ok()

        @staticmethod
        def run_remote(command: list[str], *, cwd: str) -> CommandResult:
            return _ok()

        @staticmethod
        def download(source: str, destination: Path) -> CommandResult:
            if destination.name == "spectre.log":
                destination.write_text(
                    "WARNING (CMI-2377): model exceeded voltage\n"
                    "spectre completes with 0 errors, 1 warnings, and 0 notices.\n",
                    encoding="utf-8",
                )
            else:
                destination.write_text("raw diagnostic", encoding="utf-8")
            return _ok()

    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 4.0)
    output = tmp_path / "invalid01"
    payload = module.run_teaching_hb(tmp_path / "unused", output, input_dbm=0, runner=WarningRunner())
    assert payload["status"] == "model_validity_warning"
    assert payload["quality_flags"] == ["spectre_warnings", "CMI-2377"]
    assert payload["spec_pass"] is None and payload["not_lna_result"] is True
    assert "metrics" not in payload
    assert (output / "hb.fd.pss_hb").exists()
    assert read_evidenced_metrics(output) == payload
