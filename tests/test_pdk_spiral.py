"""docs/133 §8 (experiment D): PDK spiral characterisation netlist, extraction, geometry choice, and the
optional spiral substitution of the input-match inductors in the Stage-4 PDK netlist (off by default)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from orfadc.repro import pdk_spiral as S
from orfadc.repro import pdk_v2 as P

CFG = {"toplevel": "/pdk/models/spectre/toplevel.scs", "section": "tt_lib", "pre_sections": ["pre_simu"],
       "nmos": "nmos_rf", "lr": "60n", "wr_um": 2.0, "vdd": 1.2, "mult_param": "m"}


def test_geometries_respect_documented_ranges():
    g = S.geometries()
    assert len(g) == 6 * 6 * 3
    assert all(0.5 <= x["nr"] <= 5.5 and 15 <= x["rad_um"] <= 90 and 3 <= x["w_um"] <= 30 for x in g)
    assert all(x["rad_um"] >= 20 for x in S.geometries({"nr": [1], "rad_um": [15, 20], "w_um": [25]}))


def test_char_netlist_drives_each_spiral_with_its_own_current_source():
    geos = S.geometries({"nr": [0.5, 1.0], "rad_um": [30], "w_um": [10]})
    t = S.char_netlist(CFG, geos, [30e9])
    assert t.isascii() and "section=pre_simu" in t and "section=tt_lib" in t
    assert "I0 (0 n0) isource dc=0 mag=1" in t and "I1 (0 n1) isource dc=0 mag=1" in t
    assert "X1 (n1 0 0) spiral_std_mu_z rad=30u w=10u nr=1 spacing=2u gdis=50u lay=9" in t
    assert "ac1 ac values=[3e+10]" in t and t.rstrip().endswith("save n0 n1")


def test_extract_reads_l_and_q(tmp_path):
    geos = [{"nr": 0.5, "rad_um": 30, "w_um": 10}]
    (tmp_path / "psf").mkdir()
    l, r = 100e-12, 0.8
    with open(tmp_path / "psf" / "ac1.ac", "w") as fh:
        fh.write("HEADER\nVALUE\n")
        for f in (20e9, 30e9):
            z = complex(r, 2 * math.pi * f * l)
            fh.write(f'"freq" {f:.15e}\n"n0" ({z.real:.15e} {z.imag:.15e})\n')
    rows = S.extract(tmp_path, geos)
    assert [round(x["l_ph"], 6) for x in rows] == [100.0, 100.0]
    assert rows[1]["q"] == pytest.approx(2 * math.pi * 30e9 * l / r)


def _table():
    rows = []
    for nr, rad, l_ph, q in ((0.5, 30, 60.0, 18.0), (0.5, 45, 100.0, 21.0), (1.0, 30, 101.0, 15.0), (1.0, 60, 180.0, 19.0)):
        rows.append({"nr": nr, "rad_um": rad, "w_um": 10, "f_hz": 30e9, "l_ph": l_ph, "r_ohm": 1.0, "q": q})
    return {"rows": rows}


def test_pick_chooses_highest_q_within_tolerance_or_none():
    t = _table()
    g = S.pick(t, 100e-12, 30e9)
    assert (g["rad_um"], g["nr"], g["q"]) == (45, 0.5, 21.0)
    assert S.pick(t, 3e-12, 30e9) is None                     # a few pH (e.g. Lg) is not realisable -> ideal model
    assert S.pick(t, 150e-12, 30e9) is None
    assert S.q_summary(t, 30e9, 50, 200)["q_max"] == 21.0


def test_render_uses_spirals_only_when_enabled(monkeypatch):
    from test_repro_pdk_v2 import _design
    d = _design()
    nr = list(range(2, 65, 2))
    monkeypatch.delenv("ORFADC_PDK_SPIRAL", raising=False)
    base, _, _ = P.render_pdk_netlist(d, np.array([30e9]), CFG, nr)
    assert "spiral_std_mu_z" not in base
    # a table whose entries match this design's Lpar exactly (and nothing else)
    t = {"rows": [{"nr": 1.0, "rad_um": 60, "w_um": 10, "f_hz": d.fc_hz, "l_ph": d.lpar_h * 1e12, "r_ohm": 1.0, "q": 20.0}]}
    monkeypatch.setenv("ORFADC_PDK_SPIRAL", "1")
    monkeypatch.setitem(P._SPIRAL_CACHE, "t", t)
    info: dict = {}
    text, _, lays = P.render_pdk_netlist(d, np.array([30e9]), CFG, nr, info=info)
    assert "XSlpar (in vb1 0) spiral_std_mu_z rad=60u w=10u nr=1" in text
    assert info["spirals"]["lpar"]["rad_um"] == 60 and "ideal_q" in info["spirals"]["lg"]
    assert "spirals" not in lays and text.count("spiral_std_mu_z") == 1
