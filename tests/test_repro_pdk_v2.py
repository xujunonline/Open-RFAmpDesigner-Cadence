"""Cadence v2 helpers offline: inventory parsing, layout choice, netlists, Y-extraction round trip."""
from __future__ import annotations

import math

import numpy as np
import pytest

from orfadc.repro import pdk_v2 as P

CFG = {"toplevel": "/pdk/models/spectre/toplevel.scs", "section": "top_tt", "nmos": "nmos_rf",
       "lr": "40n", "wr_um": 2.0, "vdd": 1.1}


def test_parse_inventory_groups_models_and_flags_nmos():
    raw = "\n".join([
        "##USER\tu", "##MODELFILE\t/p/m.scs|10", "##SECTION\t/p/m.scs|section top_tt",
        "##MODEL\t/p/m.scs|inline subckt nmos_rf ( d g s b )", "##MODEL\t/p/m.scs|model nch_rf bsim4 {",
        "##MODEL\t/p/m.scs|inline subckt pmos_rf ( d g s b )", "##DONE\tok"])
    inv = P.parse_inventory(raw)
    names = {c["model"] for c in inv["nmos_candidates"]}
    assert inv["complete"] and {"nmos_rf", "nch_rf"} <= names and "pmos_rf" not in names


def test_layout_for_picks_closest_width():
    lay = P.layout_for(45.0, 2.0, list(range(2, 33, 2)))
    assert abs(lay["w_um"] - 45.0) <= 1.0 and lay["w_um"] == 2.0 * lay["nr"] * lay["multi"]
    assert P.layout_for(64.0, 2.0, [16, 32])["w_um"] == 64.0


def test_char_netlist_is_ascii_and_has_sweep():
    t = P.char_netlist(CFG, {"nr": 16, "multi": 2, "w_um": 64.0}, [0.3, 0.35])
    assert t.isascii() and "section=top_tt" in t and "swp sweep param=vb values=[0.3 0.35]" in t
    assert "nmos_rf lr=40n wr=2.0u nr=16 multi=2" in t and "donoise=yes" in t
    t65 = P.char_netlist({**CFG, "lr": "60n", "mult_param": "m"}, {"nr": 16, "multi": 2, "w_um": 64.0}, [0.3])
    assert "nmos_rf lr=60n wr=2.0u nr=16 m=2" in t65 and "multi=" not in t65
    t65 = P.char_netlist({**CFG, "section": "tt_lib", "pre_sections": ["pre_simu"]}, {"nr": 4, "multi": 1, "w_um": 8.0}, [0.3])
    inc = [ln for ln in t65.splitlines() if ln.startswith("include")]
    assert inc == ['include "/pdk/models/spectre/toplevel.scs" section=pre_simu',
                   'include "/pdk/models/spectre/toplevel.scs" section=tt_lib']


def _write_sp(path, fs, smats):
    with open(path, "w") as fh:
        fh.write("HEADER\nVALUE\n")
        for f, s in zip(fs, smats):
            fh.write(f'"freq" {f:.15e}\n')
            for (i, j), k in {(0, 0): "s11", (0, 1): "s12", (1, 0): "s21", (1, 1): "s22"}.items():
                fh.write(f'"{k}" ({s[i, j].real:.15e} {s[i, j].imag:.15e})\n')


def test_extract_rows_recovers_small_signal_parameters(tmp_path):
    cgs, cgd, cdb, gds, rg = 60e-15, 20e-15, 30e-15, 2e-3, 5.0
    vbs = [0.35, 0.40]
    psf = tmp_path / "psf"
    psf.mkdir()
    vg = np.arange(0.15, 0.7501, 0.005)
    i_d = 0.02 * np.logaddexp(0, (vg - 0.35) / 0.06) ** 2       # A, smooth square-law-ish
    with open(psf / "dcsw.dc", "w") as fh:
        fh.write("HEADER\nVALUE\n")
        for v, i in zip(vg, i_d):
            fh.write(f'"vb" {v:.15e}\n"VD:p" {-i:.15e}\n')
    for n, vb in enumerate(vbs):
        gm = float(np.interp(vb, vg, np.gradient(i_d, vg[1] - vg[0])))
        fs, smats = [P.F_LO, P.F_HI], []
        for f in fs:
            s = 2j * math.pi * f
            yi = np.array([[s * (cgs + cgd), -s * cgd], [gm - s * cgd, gds + s * (cgd + cdb)]])
            z = np.linalg.inv(yi) + np.array([[rg, 0], [0, 0]])       # series gate resistance
            y = np.linalg.inv(z)
            smats.append((np.eye(2) - 50 * y) @ np.linalg.inv(np.eye(2) + 50 * y))
        _write_sp(psf / f"swp-{n:03d}_sp1.sp", fs, smats)
        with open(psf / f"swp-{n:03d}_sp1.noise.sp", "w") as fh:
            fh.write("HEADER\nVALUE\n")
            for f in fs:
                fh.write(f'"freq" {f:.15e}\n"NF" 3.0\n"NFmin" 1.5\n')
    rows = P.extract_rows(tmp_path, {"nr": 16, "multi": 1, "w_um": 32.0}, vbs, 1.1)
    assert len(rows) == 2
    for r, vb in zip(rows, vbs):
        gm = float(np.interp(vb, vg, np.gradient(i_d, vg[1] - vg[0])))
        assert r["gm_s"] == pytest.approx(gm, rel=0.03) and r["gm_dc_s"] == pytest.approx(gm, rel=0.01)
        assert r["cgd_f"] == pytest.approx(cgd, rel=0.05) and r["cgs_f"] == pytest.approx(cgs, rel=0.05)
        assert r["cdb_f"] == pytest.approx(cdb, rel=0.05) and r["gds_s"] == pytest.approx(gds, rel=0.05)
        assert r["rg_ohm"] == pytest.approx(rg, rel=0.1) and r["nfmin_db_30g"] == 1.5
        assert r["id_ma"] == pytest.approx(float(np.interp(vb, vg, i_d)) * 1e3, rel=1e-6)


def _design():
    from orfadc.config_loader import load_specs
    from orfadc.repro import tools as T
    from pathlib import Path
    sp = {s.id: s for s in load_specs(Path(__file__).resolve().parents[1] / "config" / "specs_table_iii.yaml")}["S2"]
    ctx = T.ToolContext(sp)
    cfg = T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0]
    s2 = T.impedance_matching(ctx, cfg, iters=3, n_particles=4)
    return T.band_planning(ctx, cfg, s2, sa_iters=80, max_rounds=1)["_design"]


def test_pdk_netlist_structure():
    d = _design()
    nr = list(range(2, 65, 2))
    full, rl, lays = P.render_pdk_netlist(d, np.array([27e9, 30e9]), CFG, nr, hb_pin_dbm=[-40, -30, -20])
    crit, rl2, _ = P.render_pdk_netlist(d, np.array([30e9]), CFG, nr, upto="stage2", nominal_load=(250.0, 0.0))
    for t in (full, crit):
        names = [ln.split()[0] for ln in t.splitlines() if ln and not ln.startswith(("//", "simulator", "global",
                 "include", "save", "parameters", "}", "  hb", "opts"))]
        assert t.isascii() and len(names) == len(set(names))
        assert "nmos_rf lr=40n" in t and "VDD (vdd 0) vsource dc=1.1" in t and "CDC1 (p1 in)" in t
    assert set(lays) == {"M1", "MCG", "M2", "M3"} and rl == 1787.0 and rl2 == 250.0
    assert "hbsw sweep param=pin values=[-40 -30 -20]" in full and "hb hb fundfreqs" in full
    assert "PORT2 (p2 0)" in crit and "M3 " not in crit and "EN2 (dn2 0 d2 0) vcvs gain=-1" in crit
    assert "(d1 kx" not in full and " vdd) resistor" in full  # drain inductors return to the supply


def test_hb_sweep_parser(tmp_path):
    pins = [-40.0, -30.0, -20.0, -10.0]
    gains = [20.0, 19.9, 19.2, 17.5]
    for i, (p, g) in enumerate(zip(pins, gains)):
        v = math.sqrt(2 * 100.0 * 1e-3 * 10 ** ((p + g) / 10))
        with open(tmp_path / f"hbsw-{i:03d}_hb.fd.pss_hb", "w") as fh:
            fh.write('HEADER\nVALUE\n"freq" 0\n"out" (0 0)\n"freq" 3e10\n' + f'"out" ({v:.15e} 0)\n')
    hb = P.parse_hb_sweep(tmp_path, "out", 100.0, 30e9, pins)
    assert hb["small_signal_gain_db"] == pytest.approx(20.0) and -20 < hb["ip1db_dbm"] < -10


def test_pdk_table_provider_interpolates_and_restores(tmp_path):
    from orfadc.repro import device as D
    rows = []
    for w in (40.0, 80.0):
        for vg in (0.4, 0.5, 0.6):
            rows.append({"w_um": w, "vgs_v": vg, "vds_v": 1.1, "id_ma": w * 0.01 * (vg - 0.3) ** 2 * 100,
                         "gm_s": w * 1e-4 * (vg - 0.3), "gds_s": w * 1e-5, "cgs_f": w * 1e-15, "cgd_f": w * 0.3e-15,
                         "cdb_f": w * 0.4e-15, "rg_ohm": 400.0 / w, "a1db_v": 0.2, "vdsat_v": 0.15,
                         "nfmin_db_30g": 1.0, "ft_ghz": 50.0})
    tab = P.PdkTable(rows, vdd=1.1)
    op = tab.op("diff", 60.0, 0.45)
    assert op.gm_s == pytest.approx(60 * 1e-4 * 0.15) and op.rg_ohm == pytest.approx(400 / 60)
    assert tab.id_ma(80.0, 0.5) == pytest.approx(80 * 0.01 * 0.04 * 100)
    D.set_device_provider(tab)
    try:
        assert D.vdd() == 1.1 and D.bias_grid() == [0.4, 0.5, 0.6]
        assert D.device_op("diff", 60.0, 0.45).gm_s == pytest.approx(op.gm_s)
        assert all(r["source"] == "pdk_table" for r in D.knowledge_database())
    finally:
        D.set_device_provider(None)
    assert D.vdd() == 1.2 and D.knowledge_database()[0]["source"].startswith("surrogate")


def test_kind_aware_provider_uses_low_vds_table_for_cascode():
    from orfadc.repro import circuit as ck, device as D

    def rows(scale, vds):
        out = []
        for w in (40.0, 80.0):
            for vg in (0.5, 0.6, 0.7):
                out.append({"w_um": w, "vgs_v": vg, "vds_v": vds, "id_ma": scale * w * 0.1 * (vg - 0.4),
                            "gm_s": scale * w * 1e-3, "gds_s": w * 1e-5, "cgs_f": w * 1e-15, "cgd_f": w * 0.3e-15,
                            "cdb_f": w * 0.4e-15, "rg_ohm": 400.0 / w, "a1db_v": 0.2, "vdsat_v": 0.15,
                            "nfmin_db_30g": 1.0, "ft_ghz": 50.0})
        return out
    prov = P.PdkProvider(P.PdkTable(rows(1.0, 1.1), 1.1), P.PdkTable(rows(0.8, 0.5), 1.1), 1.1, "t", cascode_ratio=1.0)
    D.set_device_provider(prov)
    try:
        assert D.device_op("diff", 60, 0.6).gm_s == pytest.approx(0.06)
        assert D.device_op("cascode", 60, 0.6).gm_s == pytest.approx(0.048)
        cg = ck.cascode_device(D.device_op("cascode", 60, 0.6))
        assert cg.w_um == pytest.approx(60.0) and cg.id_ma == pytest.approx(D.device_op("cascode", 60, 0.6).id_ma, rel=1e-3)
    finally:
        D.set_device_provider(None)
