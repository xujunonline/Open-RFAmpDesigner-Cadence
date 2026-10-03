from __future__ import annotations

import pytest

from orfadc.cadence.rf_low_drive_netlist import render_rf_default_hb_netlist, render_rf_hb_netlist


_SOURCE = (
    'simulator lang=spectre\ninclude "ade_e.scs"\n'
    'PORT1 (in 0) port r=50 num=1 type=sine\n'
    'PORT2 (outp outn) port r=1787 num=2 type=sine\n'
    'R1 (in outp) resistor r=100\n'
)


def test_rf_hb_derivation_changes_only_port_modes_and_adds_fixed_analyses() -> None:
    derived = render_rf_default_hb_netlist(_SOURCE.encode()).decode()
    assert 'PORT1 (in 0) port r=50 num=1 type=sine dbm=-70 freq=10G\n' in derived
    assert 'PORT2 (outp outn) port r=1787 num=2 type=dc\n' in derived
    assert 'R1 (in outp) resistor r=100\n' in derived
    assert 'hb hb fundfreqs=[10G] maxharms=[7] annotate=status\n' in derived
    assert derived.count('sp sp start=8G stop=12G lin=160') == 1
    assert b"dbm=-40 freq=10G" in render_rf_hb_netlist(_SOURCE.encode(), -40)
    assert b"maxharms=[9]" in render_rf_hb_netlist(_SOURCE.encode(), -11, harmonics=9)
    assert b"maxharms=[11]" in render_rf_hb_netlist(_SOURCE.encode(), -10, harmonics=11)


@pytest.mark.parametrize("input_dbm", [True, -100.0, -101, 1, "-40"])
def test_rf_hb_derivation_rejects_invalid_power(input_dbm: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        render_rf_hb_netlist(_SOURCE.encode(), input_dbm)


@pytest.mark.parametrize("harmonics", [True, 0, 8, 13, "9"])
def test_rf_hb_derivation_rejects_invalid_harmonics(harmonics: object) -> None:
    with pytest.raises(ValueError, match="harmonics"):
        render_rf_hb_netlist(_SOURCE.encode(), -11, harmonics=harmonics)


@pytest.mark.parametrize("source", [
    _SOURCE.replace('PORT1 (in 0)', 'PORT1 (other 0)'),
    _SOURCE.replace('PORT2 (outp outn)', 'PORT2 (outp 0)'),
    _SOURCE.replace('include "ade_e.scs"\n', ''),
    _SOURCE + 'hb hb fundfreqs=[10G]\n',
])
def test_rf_hb_derivation_rejects_changed_source(source: str) -> None:
    with pytest.raises(ValueError):
        render_rf_default_hb_netlist(source.encode())
