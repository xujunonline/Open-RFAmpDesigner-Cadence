from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.experiments.extract_active_oa import extract_active_oa, write_active_oa_results


def _psf_fixture(path: Path) -> None:
    path.mkdir()
    (path / "dcOp.dc").write_text(
        'VALUE\n"VDD:p" "I" -5.0e-4\nEND\n', encoding="utf-8"
    )
    (path / "sp.sp").write_text(
        'VALUE\n'
        '"freq" 1.0e9\n"s11" (0.1 0.0)\n"s21" (0.5 0.0)\n"s12" (0.01 0.0)\n"s22" (0.2 0.0)\n'
        '"freq" 2.0e9\n"s11" (0.2 0.0)\n"s21" (0.4 0.0)\n"s12" (0.01 0.0)\n"s22" (0.3 0.0)\n'
        'END\n',
        encoding="utf-8",
    )
    (path / "sp.noise.sp").write_text(
        'TRACE\n"NF" "dB"\n"NFmin" "dB"\n"F" "Noise factor"\n'
        '"Fmin" "Noise factor"\nVALUE\n'
        '"freq" 1.0e9\n"NF" 3.010299956639812\n"NFmin" 0.0\n"F" 2.0\n"Fmin" 1.0\n'
        '"freq" 2.0e9\n"NF" 3.010299956639812\n"NFmin" 0.0\n"F" 2.0\n"Fmin" 1.0\n'
        'END\n',
        encoding="utf-8",
    )
    (path / "dcOpInfo.info").write_text(
        'TYPE\n"bsim4" STRUCT(\n'
        '"ids" FLOAT DOUBLE PROP(\n)\n"vgs" FLOAT DOUBLE PROP(\n)\n'
        '"vds" FLOAT DOUBLE PROP(\n)\n"vth" FLOAT DOUBLE PROP(\n)\n'
        '"vdsat" FLOAT DOUBLE PROP(\n)\n"gm" FLOAT DOUBLE PROP(\n)\n'
        '"gds" FLOAT DOUBLE PROP(\n)\n) PROP(\n)\n'
        'VALUE\n"M1" "bsim4" (\n0.0005\n0.65\n0.81\n0.52\n0.16\n0.004\n0.0002\n'
        ') PROP(\n)\nEND\n',
        encoding="utf-8",
    )


def test_extract_active_oa_preserves_smoke_boundary(tmp_path: Path) -> None:
    psf = tmp_path / "psf"
    _psf_fixture(psf)

    rows, payload = extract_active_oa(
        psf, run_id="oa-smoke", supply_voltage_v=1.1, low_ghz=1.0, high_ghz=2.0,
        op_info_path=psf / "dcOpInfo.info", device_instance="M1", device_type="bsim4",
    )

    assert len(rows) == 2
    assert payload["not_lna_result"] is True
    assert payload["spec_pass"] is None
    assert payload["source_run_kind"] == "oa_generated_netlist_direct_spectre"
    assert payload["metrics"]["supply_current_ma"] == pytest.approx(0.5)
    assert payload["metrics"]["supply_power_mw"] == pytest.approx(0.55)
    assert payload["metrics"]["nf_db"] == pytest.approx(3.010299956639812)
    assert payload["device_operating_point"]["gm_over_id_per_v"] == pytest.approx(8.0)
    assert payload["device_operating_point"]["vds_minus_vdsat_v"] == pytest.approx(0.65)
    assert payload["stability"]["unconditionally_stable_on_sampled_grid"] is True

    output = tmp_path / "result"
    write_active_oa_results(output, rows, payload)
    assert (output / "waveforms.csv").read_text(encoding="utf-8").count("\n") == 3
    assert (output / "metrics.json").is_file()
    with pytest.raises(FileExistsError):
        write_active_oa_results(output, rows, payload)


def test_extract_active_oa_rejects_inconsistent_noise_factor(tmp_path: Path) -> None:
    psf = tmp_path / "psf"
    _psf_fixture(psf)
    noise = psf / "sp.noise.sp"
    noise.write_text(noise.read_text(encoding="utf-8").replace('"F" 2.0', '"F" 3.0'), encoding="utf-8")

    with pytest.raises(ValueError, match="disagrees"):
        extract_active_oa(psf, run_id="bad-noise", supply_voltage_v=1.1, low_ghz=1, high_ghz=2)


def test_extract_active_oa_rejects_wrong_supply_polarity(tmp_path: Path) -> None:
    psf = tmp_path / "psf"
    _psf_fixture(psf)
    dc = psf / "dcOp.dc"
    dc.write_text(dc.read_text(encoding="utf-8").replace("-5.0e-4", "5.0e-4"), encoding="utf-8")

    with pytest.raises(ValueError, match="supply current"):
        extract_active_oa(psf, run_id="bad-current", supply_voltage_v=1.1, low_ghz=1, high_ghz=2)


def test_extract_active_oa_labels_ideal_matching_derivative(tmp_path: Path) -> None:
    psf = tmp_path / "psf"
    _psf_fixture(psf)
    _, payload = extract_active_oa(
        psf, run_id="derived", supply_voltage_v=1.1, low_ghz=1, high_ghz=2,
        source_run_kind="oa_netlist_derivative_ideal_matching_direct_spectre",
    )
    assert payload["source_run_kind"] == "oa_netlist_derivative_ideal_matching_direct_spectre"
    assert "derived_netlist" in payload["reference_plane_evidence"]
    assert payload["not_lna_result"] is True
    assert payload["spec_pass"] is None
    with pytest.raises(ValueError, match="unsupported source_run_kind"):
        extract_active_oa(
            psf, run_id="wrong", supply_voltage_v=1.1, low_ghz=1, high_ghz=2,
            source_run_kind="claimed_fullchain",
        )


def test_extract_active_oa_labels_inductive_public_netlist(tmp_path: Path) -> None:
    psf = tmp_path / "psf"
    _psf_fixture(psf)
    _, payload = extract_active_oa(
        psf, run_id="public-oa-direct", supply_voltage_v=1.2,
        low_ghz=1, high_ghz=2,
        source_run_kind="teaching_mos1_inductive_oa_netlist_direct_spectre",
    )
    assert payload["model_kind"] == "teaching_model"
    assert payload["teaching_topology"] == "inductive"
    assert payload["circuit_class"] == "teaching_mos1_inductive_common_source"
    assert payload["not_lna_result"] is True and payload["spec_pass"] is None
    assert "PDK" in payload["warnings"][0]
