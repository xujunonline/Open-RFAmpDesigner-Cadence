from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments import run_hb_diagnostic as module


def _render(monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: source)
    return module.render_hb_diagnostic_netlist(
        Path("unused"), "0" * 64, rd_ohm=150, vbias_v=0.67,
        input_dbm=-40, frequency_ghz=10,
    )


def test_hb_renderer_keeps_fixed_ports_and_one_hb_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    netlist = _render(monkeypatch, "PORT1 (in 0) port r=50 num=1 type=sine\n"
                       "PORT2 (out 0) port r=50 num=2 type=sine\n")
    assert "PORT1 (in 0) port r=50 num=1 type=sine dbm=-40 freq=10000000000" in netlist
    assert "PORT2 (out 0) port r=50 num=2 type=dc" in netlist
    assert netlist.count("hb hb fundfreqs=[10000000000] maxharms=[3]") == 1


@pytest.mark.parametrize("source", [
    "PORT1 (in 0) port r=50 num=1 type=sine\n",
    "PORT1 (in 0) port r=50 num=1 type=sine\nPORT1 (x 0) port r=50 num=1 type=sine\n"
    "PORT2 (out 0) port r=50 num=2 type=sine\n",
    "PORT1 (in 0) port r=50 num=1 type=sine\nPORT2 (out 0) port r=50 num=2 type=sine\n"
    "hb hb fundfreqs=[10G] maxharms=[3]\n",
])
def test_hb_renderer_rejects_changed_topology(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    with pytest.raises(ValueError, match="unique expected ports"):
        _render(monkeypatch, source)


@pytest.mark.parametrize("input_dbm,frequency_ghz,harmonics", [
    (float("nan"), 10.0, 3), (1.0, 10.0, 3), (-40.0, 0.0, 3),
    (-40.0, 10.0, 0), (-40.0, 10.0, 8),
])
def test_hb_renderer_rejects_out_of_bounds(
    monkeypatch: pytest.MonkeyPatch, input_dbm: float, frequency_ghz: float, harmonics: int
) -> None:
    monkeypatch.setattr(module, "render_active_diagnostic_netlist", lambda *args: "")
    with pytest.raises(ValueError, match="HB input"):
        module.render_hb_diagnostic_netlist(
            Path("unused"), "0" * 64, rd_ohm=150, vbias_v=0.67,
            input_dbm=input_dbm, frequency_ghz=frequency_ghz, harmonics=harmonics,
        )


def test_hb_runner_archives_success_with_source_and_raw_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeRunner:
        config = RemoteCadenceConfig("example.test", "testuser")

        def ensure_remote_dir(self, path: str) -> CommandResult:
            return CommandResult("mkdir", (), 0, "", "")

        def upload(self, local_path: Path, remote_path: str) -> CommandResult:
            return CommandResult("upload", (), 0, "", "")

        def run_remote(self, command: list[str], *, cwd: str) -> CommandResult:
            return CommandResult("spectre", (), 0, "", "")

        def download(self, remote_path: str, local_path: Path) -> CommandResult:
            local_path.write_text(
                "spectre completes with 0 errors\n" if local_path.name == "spectre.log" else "raw\n",
                encoding="ascii",
            )
            return CommandResult("download", (), 0, "", "")

    monkeypatch.setattr(module, "_require_private_path", lambda path: None)
    monkeypatch.setattr(module, "render_hb_diagnostic_netlist", lambda *args, **kwargs:
                        "simulator lang=spectre\r\nPORT2 (out 0) port r=50 num=2 type=dc\r\n")
    monkeypatch.setattr(module, "_read_ade_companion", lambda *args: None)
    monkeypatch.setattr(module, "extract_hb_fundamental_power", lambda *args, **kwargs: {
        "fundamental_hz": 10e9, "vout_peak_v": 0.003, "iout_peak_a": 0.003 / 50,
        "output_power_dbm": -40.0, "load_current_relative_error": 0.0,
    })
    monkeypatch.setattr(module, "extract_sp_s21_at_frequency", lambda *args: 0.0)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 5.0)
    monkeypatch.setattr(module, "load_remote_config", lambda path: FakeRunner.config)
    monkeypatch.setattr(module, "RemoteRunner", lambda config: FakeRunner())
    output = tmp_path / "hb_run"
    payload = module.run_hb_diagnostic(
        tmp_path / "unused_config", output, template=tmp_path / "unused_template",
        template_sha256="0" * 64, rd_ohm=150, vbias_v=0.67,
        input_dbm=-40,
    )
    assert payload["status"] == "hb_fundamental_extracted"
    assert payload["source"] == "cadence_spectre"
    assert payload["metrics"]["power_gain_db"] == 0.0
    assert read_evidenced_metrics(output) == payload
    assert b"\r\r\n" not in (output / "netlist.scs").read_bytes()
    assert all((output / name).is_file() for name in module._HB_RAW_FILES)
