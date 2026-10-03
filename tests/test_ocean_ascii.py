from __future__ import annotations

import math
from pathlib import Path

import pytest

from orfadc.cadence.ocean_ascii import read_ocean_rf_data, read_ocean_rf_rows, read_ocnprint_trace
from orfadc.experiments.extract_ocean_oa import extract_ocean_oa


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    export = root / "export"
    export.mkdir()
    samples = "\n 1.00000e+09      {first}\n 2.00000e+09      {second}\n"
    for signal, value in (("s11", 0.1), ("s21", 0.5), ("s22", 0.2)):
        for component, component_value in (("real", value), ("imag", 0.0)):
            header = f'freq (Hz) {component}(getData("{signal}" ?resultsDir "/run/a/psf" ?result "sp"))'
            (export / f"{signal}_{component}.txt").write_text(
                header + samples.format(first=component_value, second=component_value),
                encoding="utf-8",
            )
    for signal, value in (("NF", 10 * math.log10(2)), ("NFmin", 0.0), ("F", 2.0), ("Fmin", 1.0)):
        header = f'freq (Hz) getData("{signal}" ?resultsDir "/run/a/psf" ?result "sp_noise")'
        if signal in {"NF", "NFmin"}:
            header += " (dB)"
        (export / f"{signal}.txt").write_text(
            header + samples.format(first=value, second=value), encoding="utf-8"
        )
    (export / "report.txt").write_text("vdd_current=-0.0005\n", encoding="utf-8")
    ocean_log = root / "ocean.log"
    spectre_log = root / "spectre.log"
    ocean_log.write_text("INFO (ADE-3071): Simulation completed successfully.\n", encoding="utf-8")
    spectre_log.write_text("spectre completes with 0 errors, 5 warnings\n", encoding="utf-8")
    return export, ocean_log, spectre_log


def test_extract_ocean_oa_preserves_smoke_boundary(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    rows, payload = extract_ocean_oa(
        export, ocean_log=ocean_log, spectre_log=spectre_log,
        run_id="ocean-smoke", supply_voltage_v=1.1, low_ghz=1, high_ghz=2,
    )
    assert len(rows) == 2
    assert payload["source_run_kind"] == "oa_schematic_ocean_classic_batch"
    assert payload["raw_format"] == "ocean_ocnprint_from_psfxl"
    assert payload["not_lna_result"] is True
    assert payload["spec_pass"] is None
    assert payload["metrics"]["s21_db"] == pytest.approx(20 * math.log10(0.5))
    assert payload["metrics"]["nf_db"] == pytest.approx(10 * math.log10(2))
    assert payload["metrics"]["supply_power_mw"] == pytest.approx(0.55)
    assert payload["stability"] is None
    assert any("S12 was not exported" in warning for warning in payload["warnings"])


def test_extract_ocean_oa_labels_public_teaching_model(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    _, payload = extract_ocean_oa(
        export, ocean_log=ocean_log, spectre_log=spectre_log,
        run_id="teaching-oa", supply_voltage_v=1.2,
        low_ghz=1, high_ghz=2, teaching_model=True,
    )
    assert payload["model_kind"] == "teaching_model"
    assert payload["source_run_kind"] == "teaching_mos1_oa_ocean_classic_batch"
    assert payload["circuit_class"] == "teaching_mos1_common_source"
    assert payload["not_lna_result"] is True and payload["spec_pass"] is None
    assert "PDK" in payload["warnings"][0]
    with pytest.raises(ValueError, match="teaching_model"):
        extract_ocean_oa(
            export, ocean_log=ocean_log, spectre_log=spectre_log,
            run_id="bad", supply_voltage_v=1.2, teaching_model="yes",
        )


def test_extract_ocean_oa_distinguishes_inductive_teaching_topology(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    _, payload = extract_ocean_oa(
        export, ocean_log=ocean_log, spectre_log=spectre_log,
        run_id="inductive-oa", supply_voltage_v=1.2,
        low_ghz=1, high_ghz=2, teaching_model=True, teaching_topology="inductive",
    )
    assert payload["teaching_topology"] == "inductive"
    assert payload["source_run_kind"] == "teaching_mos1_inductive_oa_ocean_classic_batch"
    assert payload["circuit_class"] == "teaching_mos1_inductive_common_source"
    assert payload["spec_pass"] is None
    with pytest.raises(ValueError, match="teaching_topology"):
        extract_ocean_oa(
            export, ocean_log=ocean_log, spectre_log=spectre_log,
            run_id="bad", supply_voltage_v=1.2, teaching_topology="inductive",
        )


def test_ocean_ascii_uses_s12_for_sampled_stability(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    for component, value in (("real", 0.01), ("imag", 0.0)):
        (export / f"s12_{component}.txt").write_text(
            f'freq (Hz) {component}(getData("s12" ?resultsDir "/run/a/psf" ?result "sp"))\n'
            f' 1.00000e+09 {value}\n 2.00000e+09 {value}\n',
            encoding="utf-8",
        )
    rows, stability = read_ocean_rf_data(export)
    assert len(rows) == 2
    assert stability is not None
    assert stability["unconditionally_stable_on_sampled_grid"] is True
    _, payload = extract_ocean_oa(
        export, ocean_log=ocean_log, spectre_log=spectre_log,
        run_id="with-s12", supply_voltage_v=1.1, low_ghz=1, high_ghz=2,
    )
    assert payload["stability"] == stability
    assert payload["stability_quality"] == "insufficient_export_precision"


def test_high_precision_ocean_export_labels_sampled_stability(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    for part, value in (("real", 0.01), ("imag", 0.0)):
        (export / f"s12_{part}.txt").write_text(
            f'freq (Hz) {part}(getData("s12" ?resultsDir "/run/a/psf" ?result "sp"))\n'
            f" 1.00000000000000e+09 {value:.14e}\n 2.00000000000000e+09 {value:.14e}\n",
            encoding="utf-8",
        )
    for path in export.glob("*.txt"):
        if path.name == "report.txt":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[1:]:
            fields = line.split()
            rows.append(f" {float(fields[0]):.14e} {float(fields[1]):.14e}" if len(fields) == 2 else line)
        path.write_text(lines[0] + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    _, payload = extract_ocean_oa(
        export, ocean_log=ocean_log, spectre_log=spectre_log,
        run_id="precise", supply_voltage_v=1.2, low_ghz=1, high_ghz=2,
        teaching_model=True, ocn_precision_digits=15,
    )
    assert payload["ocn_precision_digits"] == 15
    assert payload["stability_quality"] == "sampled_grid_only"
    assert not any("six-digit" in warning for warning in payload["warnings"])
    trace = export / "s21_real.txt"
    trace.write_text(trace.read_text(encoding="utf-8").replace("5.00000000000000e-01", "5.00000e-01"), encoding="utf-8")
    with pytest.raises(ValueError, match="15-digit OCEAN export"):
        extract_ocean_oa(
            export, ocean_log=ocean_log, spectre_log=spectre_log,
            run_id="imprecise", supply_voltage_v=1.2, low_ghz=1, high_ghz=2,
            teaching_model=True, ocn_precision_digits=15,
        )


def test_ocean_ascii_rejects_partial_s12(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    (export / "s12_real.txt").write_text(
        'freq (Hz) real(getData("s12" ?result "sp"))\n 1.00000e+09 0.01\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="present together"):
        read_ocean_rf_data(export)


def test_ocean_ascii_rejects_s12_from_another_run(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    for component, value in (("real", 0.01), ("imag", 0.0)):
        (export / f"s12_{component}.txt").write_text(
            f'freq (Hz) {component}(getData("s12" ?resultsDir "/run/b/psf" ?result "sp"))\n'
            f' 1.00000e+09 {value}\n 2.00000e+09 {value}\n',
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match="different resultsDir provenance"):
        read_ocean_rf_data(export)


def test_ocean_ascii_rejects_s12_without_provenance(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    for path in export.glob("*.txt"):
        if path.name != "report.txt":
            path.write_text(path.read_text(encoding="utf-8").replace(' ?resultsDir "/run/a/psf"', ''), encoding="utf-8")
    for component, value in (("real", 0.01), ("imag", 0.0)):
        (export / f"s12_{component}.txt").write_text(
            f'freq (Hz) {component}(getData("s12" ?result "sp"))\n'
            f' 1.00000e+09 {value}\n 2.00000e+09 {value}\n',
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match="requires explicit resultsDir provenance"):
        read_ocean_rf_data(export)


def test_ocean_ascii_rejects_frequency_grid_mismatch(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    path = export / "s21_imag.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("2.00000e+09", "2.10000e+09"), encoding="utf-8")
    with pytest.raises(ValueError, match="frequency grid differs"):
        read_ocean_rf_rows(export)


def test_ocean_ascii_rejects_factor_mismatch(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    path = export / "F.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("2.0\n", "3.0\n"), encoding="utf-8")
    with pytest.raises(ValueError, match="F disagrees with NF"):
        read_ocean_rf_rows(export)


def test_ocean_ascii_rejects_bad_header_and_nonfinite_sample(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    path = export / "NF.txt"
    with pytest.raises(ValueError, match="invalid ocnPrint header"):
        read_ocnprint_trace(path, header_fragment='getData("s11"')
    path.write_text(path.read_text(encoding="utf-8").replace("3.010299956639812", "nan"), encoding="utf-8")
    with pytest.raises(ValueError, match="nonfinite"):
        read_ocean_rf_rows(export)


def test_ocean_ascii_rejects_nf_without_db_header(tmp_path: Path) -> None:
    export, _, _ = _fixture(tmp_path)
    path = export / "NF.txt"
    path.write_text(path.read_text(encoding="utf-8").replace(" (dB)", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="lacks dB units"):
        read_ocean_rf_rows(export)


def test_ocean_oa_rejects_unclean_spectre_log(tmp_path: Path) -> None:
    export, ocean_log, spectre_log = _fixture(tmp_path)
    spectre_log.write_text("spectre completes with 0 errors\nSPECTRE-25\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean completion"):
        extract_ocean_oa(
            export, ocean_log=ocean_log, spectre_log=spectre_log,
            run_id="bad-log", supply_voltage_v=1.1,
        )
