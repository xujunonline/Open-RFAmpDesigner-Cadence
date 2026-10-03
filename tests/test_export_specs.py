from __future__ import annotations

import csv
from pathlib import Path

import pytest

from orfadc.experiments.export_specs import export_table_iii_specs


ROOT = Path(__file__).resolve().parents[1]


def test_export_table_iii_has_only_paper_specs_and_no_simulation_results(tmp_path: Path) -> None:
    output = tmp_path / "table_iii_specs.csv"
    count = export_table_iii_specs(ROOT / "config/specs_table_iii.yaml", output)
    assert count == 10
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["spec_id"] for row in rows] == [f"S{i}" for i in range(1, 11)]
    assert rows[0]["band_low_ghz"] == "9.0"
    assert rows[0]["band_high_ghz"] == "11.0"
    assert all(row["source_type"] == "paper_table_iii_transcription" for row in rows)
    assert "spec_pass" not in rows[0] and "s21_db" not in rows[0]
    with pytest.raises(FileExistsError):
        export_table_iii_specs(ROOT / "config/specs_table_iii.yaml", output)


def test_export_refuses_empty_spec_config(tmp_path: Path) -> None:
    source = tmp_path / "empty.yaml"
    source.write_text("specs: []\n", encoding="ascii")
    output = tmp_path / "table_iii_specs.csv"
    with pytest.raises(ValueError, match="empty"):
        export_table_iii_specs(source, output)
    assert not output.exists()
