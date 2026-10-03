from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import CommandResult, RemoteCadenceConfig
from orfadc.experiments import run_teaching_lna as module
from orfadc.experiments.audit_teaching_lna import _validate_damping


def test_public_teaching_netlist_is_standalone_and_has_dc_input_block() -> None:
    raw = module.validate_teaching_netlist()
    assert b"model n_teach mos1" in raw
    assert b"CIN (in rf_in) capacitor c=5p" in raw
    assert b"sp sp" in raw and b"donoise=yes" in raw
    assert b"dcOpInfo info what=oppoint where=rawfile" in raw
    assert b"include " not in raw.lower()


def test_runner_rejects_alternate_netlist_even_with_matching_text(tmp_path: Path) -> None:
    copied = tmp_path / "copy.scs"
    copied.write_bytes(module.validate_teaching_netlist())
    with pytest.raises(ValueError, match="checked-in"):
        module.validate_teaching_netlist(copied)


def test_bias_renderer_is_bounded_and_changes_only_bias() -> None:
    original = module.validate_teaching_netlist().decode("ascii")
    rendered = module.render_teaching_lna_netlist(0.55).decode("ascii")
    assert rendered == original.replace("VBIAS=0.65", "VBIAS=0.55000000000000004", 1)
    for invalid in (0.49, 0.71, float("nan"), True):
        with pytest.raises(ValueError, match="VBIAS"):
            module.render_teaching_lna_netlist(invalid)


def test_width_renderer_is_bounded_and_changes_only_mos_width() -> None:
    original = module.render_teaching_lna_netlist().decode("ascii")
    rendered = module.render_teaching_lna_netlist(wmos_um=200).decode("ascii")
    assert rendered == original.replace("WMOS=300u", "WMOS=200u", 1)
    for invalid in (99, 501, float("inf"), True):
        with pytest.raises(ValueError, match="WMOS"):
            module.render_teaching_lna_netlist(wmos_um=invalid)


def test_output_matching_renderer_changes_only_whitelisted_values() -> None:
    original = module.render_teaching_lna_netlist().decode("ascii")
    matched = module.render_teaching_lna_netlist(ldd_nh=9.4, cblock_ff=27).decode("ascii")
    assert matched == original.replace("LDD=2n", "LDD=9.4000000000000004n").replace(
        "CBLOCK (drain out) capacitor c=5p", "CBLOCK (drain out) capacitor c=27f"
    )
    for args in ({"ldd_nh": 17}, {"ldd_nh": float("nan")}, {"cblock_ff": 1}, {"cblock_ff": True}):
        with pytest.raises(ValueError, match="LDD|CBLOCK"):
            module.render_teaching_lna_netlist(**args)


def test_input_matching_renderer_changes_only_whitelisted_values() -> None:
    original = module.render_teaching_lna_netlist().decode("ascii")
    changed = module.render_teaching_lna_netlist(lgs_nh=0.8, lss_ph=300).decode("ascii")
    assert changed == original.replace("LGS=1n", "LGS=0.80000000000000004n").replace(
        "LSS=240p", "LSS=300p"
    )
    for args in ({"lgs_nh": 0.1}, {"lgs_nh": float("nan")}, {"lss_ph": 99}, {"lss_ph": True}):
        with pytest.raises(ValueError, match="LGS|LSS"):
            module.render_teaching_lna_netlist(**args)


def test_optional_output_damping_is_bounded_and_does_not_change_default() -> None:
    original = module.render_teaching_lna_netlist()
    damped = module.render_teaching_lna_netlist(rdamp_ohm=500).decode("ascii")
    assert damped.count("RDAMP (vdd drain) resistor r=500") == 1
    assert damped.replace("RDAMP (vdd drain) resistor r=500\n", "").encode("ascii") == original
    for invalid in (99, 10001, float("nan"), True):
        with pytest.raises(ValueError, match="RDAMP"):
            module.render_teaching_lna_netlist(rdamp_ohm=invalid)


def test_cascode_renderer_adds_only_controlled_upper_device_and_bias() -> None:
    common = module.render_teaching_lna_netlist().decode("ascii")
    cascode = module.render_teaching_lna_netlist(topology="cascode", vcas_v=0.95).decode("ascii")
    assert cascode.count("M1 (cas gate source 0) n_teach w=WMOS l=LMOS") == 1
    assert cascode.count("M2 (drain casgate cas 0) n_teach w=WMOS l=LMOS") == 1
    assert cascode.count("VCAS_SRC (casgate 0) vsource dc=0.94999999999999996") == 1
    assert "M2 (" not in common and "VCAS_SRC" not in common
    assert cascode.count("model n_teach mos1") == 1
    for invalid in (0.79, 1.11, float("nan"), True):
        with pytest.raises(ValueError, match="VCAS"):
            module.render_teaching_lna_netlist(topology="cascode", vcas_v=invalid)
    with pytest.raises(ValueError, match="VCAS is only used"):
        module.render_teaching_lna_netlist(vcas_v=1.0)
    with pytest.raises(ValueError, match="topology"):
        module.render_teaching_lna_netlist(topology="three_stage")


def test_damping_auditor_rejects_missing_or_miswired_resistor() -> None:
    source = module.render_teaching_lna_netlist(rdamp_ohm=500).decode("ascii")
    _validate_damping(source, {"rdamp_ohm": 500})
    with pytest.raises(ValueError, match="damping"):
        _validate_damping(source, {})
    with pytest.raises(ValueError, match="damping"):
        _validate_damping(source.replace("(vdd drain)", "(vdd out)"), {"rdamp_ohm": 500})
    with pytest.raises(ValueError, match="RDAMP"):
        _validate_damping(source, {"rdamp_ohm": 600})


def test_dense_sp_renderer_preserves_default_and_enforces_budget() -> None:
    original = module.render_teaching_lna_netlist().decode("ascii")
    dense = module.render_teaching_lna_netlist(sp_intervals=799).decode("ascii")
    assert dense == original.replace("stop=20G lin=199 ports=", "stop=20G lin=799 ports=")
    band = module.render_teaching_lna_netlist(
        sp_start_ghz=8.0, sp_stop_ghz=12.0, sp_intervals=160,
    ).decode("ascii")
    assert "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2]" in band
    for invalid in (39, 1000, 799.0, True):
        with pytest.raises(ValueError, match="SP intervals"):
            module.render_teaching_lna_netlist(sp_intervals=invalid)
    for kwargs in ({"sp_start_ghz": 0.0}, {"sp_stop_ghz": 21.0},
                   {"sp_start_ghz": 12.0, "sp_stop_ghz": 8.0},
                   {"sp_intervals": 40}):
        with pytest.raises(ValueError, match="SP range"):
            module.render_teaching_lna_netlist(**kwargs)


@pytest.mark.parametrize("topology", ["common_source", "cascode"])
def test_runner_archives_remote_mkdir_failure_without_claiming_simulation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, topology: str,
) -> None:
    class FailedRunner:
        config = RemoteCadenceConfig(host="example.test", user="test", remote_root="/tmp/test")

        @staticmethod
        def ensure_remote_dir(path: str) -> CommandResult:
            return CommandResult("mkdir", (), 1, "", "private diagnostic text")

    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 4.0)
    output = tmp_path / "failure01"
    payload = module.run_teaching_lna(tmp_path / "unused", output, topology=topology, runner=FailedRunner())
    assert payload["status"] == "mkdir_failed"
    assert payload["simulation_status"] == "unknown"
    assert payload["spec_pass"] is None and payload["not_lna_result"] is True
    if topology == "cascode":
        assert payload["design_parameters"]["vcas_v"] == 0.95
        assert payload["circuit_class"] == "teaching_mos1_cascode"
    assert "private diagnostic text" not in (output / "metrics.json").read_text(encoding="utf-8")
    assert read_evidenced_metrics(output) == payload


def test_runner_memory_gate_precedes_output_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 1.0)
    output = tmp_path / "not_created"
    with pytest.raises(RuntimeError, match="physical-memory gate"):
        module.run_teaching_lna(tmp_path / "unused", output)
    assert not output.exists()


def test_small_signal_warning_archives_raw_without_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class WarningRunner:
        config = RemoteCadenceConfig(host="example.test", user="test", remote_root="/tmp/test")

        @staticmethod
        def ensure_remote_dir(path: str) -> CommandResult:
            return CommandResult("mkdir", (), 0, "", "")

        @staticmethod
        def upload(source: Path, destination: str) -> CommandResult:
            return CommandResult("upload", (), 0, "", "")

        @staticmethod
        def run_remote(command: list[str], *, cwd: str) -> CommandResult:
            return CommandResult("run", (), 0, "", "")

        @staticmethod
        def download(source: str, destination: Path) -> CommandResult:
            if destination.name == "spectre.log":
                destination.write_text(
                    "WARNING (CMI-2377): model limit\n"
                    "spectre completes with 0 errors, 1 warnings, and 0 notices.\n",
                    encoding="utf-8",
                )
            else:
                destination.write_text("raw diagnostic", encoding="utf-8")
            return CommandResult("download", (), 0, "", "")

    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "available_physical_memory_gb", lambda: 4.0)
    output = tmp_path / "warning01"
    payload = module.run_teaching_lna(tmp_path / "unused", output, vbias_v=0.55, runner=WarningRunner())
    assert payload["status"] == "model_validity_warning"
    assert payload["quality_flags"] == ["spectre_warnings", "CMI-2377"]
    assert payload["design_parameters"] == {
        "vbias_v": 0.55, "wmos_um": 300.0, "lgs_nh": 1.0, "lss_ph": 240.0,
        "ldd_nh": 2.0, "cblock_ff": 5000.0,
    }
    assert "metrics" not in payload
    assert (output / "sp.sp").is_file()
    assert read_evidenced_metrics(output) == payload
