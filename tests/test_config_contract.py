from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.config_loader import load_specs, write_json
from orfadc.schemas import Spec


def test_spec_rejects_invalid_frequency_and_bandwidth() -> None:
    fields = dict(id="S1", fc_ghz=10, fbw_ratio=0.2, power_ma=30, gain_db=25,
                  nf_max_db=5, ip1db_min_dbm=-25)
    with pytest.raises(ValueError, match="frequency"):
        Spec(**{**fields, "fc_ghz": 0})
    with pytest.raises(ValueError, match="finite"):
        Spec(**{**fields, "fbw_ratio": float("nan")})


def test_specs_must_have_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "specs.yaml"
    row = "  - {id: S1, fc_ghz: 10, fbw_ratio: 0.2, power_ma: 30, gain_db: 25, nf_max_db: 5, ip1db_min_dbm: -25}\n"
    source.write_text("specs:\n" + row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_specs(source)


def test_json_writer_rejects_nonfinite_metrics(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Out of range"):
        write_json(tmp_path / "bad.json", {"nf_db": float("nan")})
