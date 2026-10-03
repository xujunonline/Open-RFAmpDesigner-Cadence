from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.experiments.audit_pdk_rf_default_three_stage import (
    default_rf_geometry, validate_oa_source_loaded,
)


def _public_synthetic_six_device_netlist() -> str:
    return "\n".join(
        f"M{index} (d g s 0) public_rf_model lr=81n wr=3.5u nr=7 multi=1"
        for index in range(1, 7)
    )


def test_default_rf_geometry_requires_six_matching_devices() -> None:
    assert default_rf_geometry(_public_synthetic_six_device_netlist()) == (
        "public_rf_model", "81n", "3.5u", "7",
    )


def test_default_rf_geometry_rejects_missing_or_changed_device() -> None:
    source = _public_synthetic_six_device_netlist()
    with pytest.raises(ValueError, match="six instances"):
        default_rf_geometry(source.replace("M6 (", "X6 ("))
    with pytest.raises(ValueError, match="six instances"):
        default_rf_geometry(source.replace("M6 (d g s 0) public_rf_model lr=81n wr=3.5u nr=7",
                                        "M6 (d g s 0) public_rf_model lr=81n wr=4u nr=7"))


def test_oa_source_loaded_ties_wrapper_and_log_to_creation_report(tmp_path: Path) -> None:
    source = "/public/sim/demo/spectre/schematic/netlist/input.scs"
    companion = source.rsplit("/", 1)[0] + "/ade_e.scs"
    (tmp_path / "netlist_report.txt").write_text(
        f'netlist_result="{source}"\nstatus=ok\n', encoding="utf-8",
    )
    wrapper = f'simulator lang=spectre\ninclude "{source}"\nac ac start=8G stop=12G lin=160\n'
    log = f"Reading file:  /public/wrapper.scs\nReading file:  {source}\nReading file:  {companion}\n"
    validate_oa_source_loaded(tmp_path, wrapper, log)
    with pytest.raises(ValueError, match="did not load"):
        validate_oa_source_loaded(tmp_path, wrapper.replace(source, "/public/other/input.scs"), log)
    with pytest.raises(ValueError, match="did not load"):
        validate_oa_source_loaded(tmp_path, wrapper, log.replace(companion, "/public/other/ade_e.scs"))
    with pytest.raises(ValueError, match="did not load"):
        validate_oa_source_loaded(tmp_path, wrapper, log.replace(source, "/public/other/input.scs"))
