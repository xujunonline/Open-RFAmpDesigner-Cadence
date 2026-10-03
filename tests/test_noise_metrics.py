from __future__ import annotations

import math
import json
from pathlib import Path

import pytest

from orfadc.cadence.noise_metrics import (
    noise_rows_from_psfascii,
    normalize_noise_traces,
    require_same_frequency_grid,
    summarize_noise,
    write_noise_csv,
)
from orfadc.experiments.extract_noise import extract_noise
from orfadc.experiments.run_passive_noise import run_passive_noise, validate_passive_noise_files
from orfadc.cadence.psfascii_reader import parse_trace_kinds


def test_normalize_linear_nf_and_optional_nfmin(tmp_path: Path) -> None:
    rows = normalize_noise_traces(([1e9, 2e9], [2.0, 3.0]), nf_unit="linear_factor")
    assert rows[0]["nf_db"] == pytest.approx(10 * math.log10(2.0))
    assert rows[0]["nfmin_db"] is None
    assert summarize_noise(rows, 1.0, 2.0) == {
        "nf_db": pytest.approx(10 * math.log10(3.0)),
        "nfmin_db": None,
        "points_in_band": 2,
    }
    target = tmp_path / "noise.csv"
    write_noise_csv(target, rows)
    assert target.read_text(encoding="utf-8").splitlines()[0] == "freq_hz,freq_ghz,nf_db,nfmin_db"


def test_parse_psfascii_noise_with_explicit_signal_names(tmp_path: Path) -> None:
    source = tmp_path / "sp_noise.sp"
    source.write_text(
        'VALUE\n"freq" 1e9\n"my_nf" 2.0\n"my_nfmin" 1.5\n'
        '"freq" 2e9\n"my_nf" 2.5\n"my_nfmin" 1.8\nEND\n',
        encoding="utf-8",
    )
    rows = noise_rows_from_psfascii(
        source, nf_signal="my_nf", nfmin_signal="my_nfmin", nf_unit="db"
    )
    assert rows[1]["nf_db"] == 2.5
    assert summarize_noise(rows, 1, 2)["nfmin_db"] == 1.8


def test_noise_trace_declaration_is_not_treated_as_malformed_sample(tmp_path: Path) -> None:
    source = tmp_path / "spectre_noise.sp"
    source.write_text(
        'TYPE\n"dB" FLOAT DOUBLE PROP(\n"units" "dB"\n)\n'
        'TRACE\n"NF" "dB"\n"NFmin" "dB"\n'
        'VALUE\n"freq" 1e9\n"NF" 2.0\n"NFmin" 1.0\nEND\n',
        encoding="utf-8",
    )
    rows = noise_rows_from_psfascii(
        source, nf_signal="NF", nfmin_signal="NFmin", nf_unit="db"
    )
    assert parse_trace_kinds(source)["NF"] == "dB"
    assert rows[0]["nf_db"] == 2.0
    assert rows[0]["nfmin_db"] == 1.0


@pytest.mark.parametrize(
    ("trace", "unit", "message"),
    [
        (([1e9, 1e9], [2, 3]), "db", "increasing"),
        (([1e9], [0]), "linear_factor", "positive"),
        (([1e9], [float("nan")]), "db", "finite"),
        (([1e9], [2]), "unknown", "nf_unit"),
    ],
)
def test_reject_invalid_nf_trace(trace, unit, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_noise_traces(trace, nf_unit=unit)


def test_reject_misaligned_nfmin_and_missing_band() -> None:
    with pytest.raises(ValueError, match="grids differ"):
        normalize_noise_traces(
            ([1e9, 2e9], [2, 3]), nf_unit="db", nfmin_trace=([1e9, 2.1e9], [1, 2])
        )
    rows = normalize_noise_traces(([1e9], [2]), nf_unit="db")
    with pytest.raises(ValueError, match="do not cover"):
        summarize_noise(rows, 2, 3)


def test_noise_summary_interpolates_band_edges_and_requires_coverage() -> None:
    rows = normalize_noise_traces(([1e9, 10e9, 100e9], [0.0, 10.0, 20.0]), nf_unit="db")
    summary = summarize_noise(rows, math.sqrt(10), 10 * math.sqrt(10))
    assert summary == {"nf_db": pytest.approx(15.0), "nfmin_db": None, "points_in_band": 3}


def test_noise_and_sparameter_frequency_grid_must_match() -> None:
    rows = normalize_noise_traces(([1e9, 2e9], [2, 3]), nf_unit="db")
    require_same_frequency_grid(rows, [{"freq_hz": 1e9}, {"freq_hz": 2e9}])
    with pytest.raises(ValueError, match="grids differ"):
        require_same_frequency_grid(rows, [{"freq_hz": 1e9}, {"freq_hz": 2.1e9}])


def test_missing_nfmin_is_not_inferred_from_nf(tmp_path: Path) -> None:
    source = tmp_path / "sp_noise.sp"
    source.write_text('VALUE\n"freq" 1e9\n"nf" 2.0\nEND\n', encoding="utf-8")
    rows = noise_rows_from_psfascii(source, nf_signal="nf", nf_unit="db")
    assert rows[0]["nfmin_db"] is None
    with pytest.raises(ValueError, match="nfmin"):
        noise_rows_from_psfascii(source, nf_signal="nf", nfmin_signal="nfmin", nf_unit="db")


def test_missing_one_noise_frequency_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "missing.sp"
    source.write_text(
        'VALUE\n"freq" 1e9\n"nf" 2.0\n"freq" 2e9\nEND\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing at frequency"):
        noise_rows_from_psfascii(source, nf_signal="nf", nf_unit="db")


def test_extract_noise_keeps_unverified_provenance_and_raw_data(tmp_path: Path) -> None:
    source = tmp_path / "raw.sp"
    source.write_text(
        'VALUE\n"freq" 1e9\n"nf" 2.0\n"freq" 2e9\n"nf" 3.0\nEND\n',
        encoding="utf-8",
    )
    output = tmp_path / "result"
    payload = extract_noise(
        source, output, nf_signal="nf", nf_unit="db", low_ghz=1, high_ghz=2
    )
    assert payload["status"] == "parsed_unverified"
    assert payload["spec_pass"] is None
    assert payload["metrics"]["nfmin_db"] is None
    assert (output / "noise_raw.psfascii").read_bytes() == source.read_bytes()
    assert json.loads((output / "metrics.json").read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError, match="not empty"):
        extract_noise(source, output, nf_signal="nf", nf_unit="db", low_ghz=1, high_ghz=2)


def test_validate_passive_noise_crosschecks_factor_and_sparameters(tmp_path: Path) -> None:
    noise = tmp_path / "noise.sp"
    noise.write_text(
        'TRACE\n"NF" "dB"\n"NFmin" "dB"\n'
        '"F" "Noise factor"\n"Fmin" "Noise factor"\n'
        'VALUE\n"freq" 1e9\n"NF" 3.010299956639812\n'
        '"NFmin" 0\n"F" 2\n"Fmin" 1\n'
        '"freq" 2e9\n"NF" 3.010299956639812\n'
        '"NFmin" 0\n"F" 2\n"Fmin" 1\nEND\n',
        encoding="utf-8",
    )
    sparams = tmp_path / "sparams.s2p"
    sparams.write_text(
        '# Hz S RI R 50\n1e9 0 0 0.5 0 0.5 0 0 0\n'
        '2e9 0 0 0.5 0 0.5 0 0 0\n'
        '! NOISE PARAMETERS  :\n1e9 0 1 0 0.1\n',
        encoding="utf-8",
    )
    rows, srows, summary = validate_passive_noise_files(noise, sparams, 1, 2)
    assert len(rows) == len(srows) == 2
    assert summary["nf_db"] == pytest.approx(10 * math.log10(2))

    noise.write_text(noise.read_text(encoding="utf-8").replace('"F" 2', '"F" 3'), encoding="utf-8")
    with pytest.raises(ValueError, match="disagree"):
        validate_passive_noise_files(noise, sparams, 1, 2)


def test_passive_noise_runner_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        run_passive_noise(tmp_path / "private.yaml", tmp_path / "netlist.scs", output)
