"""B16: PDK device-model fit, cross-coupled neutralisation, design round trip."""
from __future__ import annotations

import math

import numpy as np
import pytest

from orfadc.repro import circuit as ck, device as D, pdk_fit as F
from orfadc.repro import tools as T


def _point_from_model(p):
    f = np.array(F.FREQS)
    t = F.model_twoport(f, p)
    pt = {"f": list(f), "y": [], "fmin": [], "rn": [], "gopt": [], "bopt": []}
    for k in range(len(f)):
        pt["y"].append(F._abcd_to_y(t.abcd[k]))
        fm, rn, yo = F.noise_params(t, k)
        pt["fmin"].append(fm), pt["rn"].append(rn), pt["gopt"].append(yo.real), pt["bopt"].append(yo.imag)
    return pt


def test_noise_param_roundtrip():
    ca = F.ca_from_noise_params(1.25, 20.0, 5e-3, -1.1e-2)
    t = type("T", (), {"ca": ca[None]})
    fm, rn, yo = F.noise_params(t, 0)
    assert fm == pytest.approx(1.25) and rn == pytest.approx(20.0) and yo == pytest.approx(complex(5e-3, -1.1e-2))


def test_fit_recovers_known_device():
    p = {"cgs": 50e-15, "cgd": 24e-15, "cdb": 38e-15, "gm": 0.075, "tau": 0.18e-12, "gds": 0.01, "rg": 0.6,
         "ri": 6.0, "gamma": 1.05, "dg": 3.3}
    fit = F.fit_point(_point_from_model(p))
    assert fit["fit_rms"] < 1e-3
    for k in ("cgs", "cgd", "cdb", "gm", "gds"):
        assert fit[k] == pytest.approx(p[k], rel=0.03), k
    f = np.array(F.FREQS)
    a, b = F.model_twoport(f, p), F.model_twoport(f, fit)
    assert np.allclose(a.fmin(), b.fmin(), rtol=2e-3)


def test_fet_cs_defaults_unchanged_for_surrogate():
    op = D.device_op("diff", 81.0, 0.4)
    s = 2j * math.pi * np.array([30e9])
    y, _ = ck.fet_cs(s, op)
    assert y[0, 0, 0] == pytest.approx(s[0] * (op.cgs_f + op.cgd_f))
    assert y[0, 1, 0] == pytest.approx(op.gm_s - s[0] * op.cgd_f)


def test_cross_coupled_neutralisation_capacitances():
    class Prov:
        neutralization = "cross_coupled"
        vdd, vb_grid, name = 1.2, D.bias_grid(), "x"

        def op(self, kind, w, v):
            return D._surrogate_device_op(kind, w, v)

    op = D.device_op("diff", 81.0, 0.4)
    s = 2j * math.pi * np.array([30e9])
    D.set_device_provider(Prov())
    try:
        _, dev = ck.stage_diff(s, op)
        r = D.TECH.neutralization_residual
        A, B, C, Dd = dev.abcd[0, 0, 0], dev.abcd[0, 0, 1], dev.abcd[0, 1, 0], dev.abcd[0, 1, 1]
        y11, y12 = Dd / B, (B * C - A * Dd) / B
        assert y11 == pytest.approx(s[0] * (op.cgs_f + (2 - r) * op.cgd_f))
        assert y12 == pytest.approx(-s[0] * r * op.cgd_f)
        assert ck.neutral_cap_factor() == pytest.approx(2 - r)
    finally:
        D.set_device_provider(None)
    assert ck.neutral_cap_factor() == pytest.approx(D.TECH.neutralization_residual)


def test_design_summary_roundtrip():
    from orfadc.config_loader import load_specs
    from pathlib import Path
    sp = {s.id: s for s in load_specs(Path(__file__).resolve().parents[1] / "config" / "specs_table_iii.yaml")}["S2"]
    ctx = T.ToolContext(sp)
    cfg = T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0]
    s2 = T.impedance_matching(ctx, cfg, iters=3, n_particles=4)
    d = T.band_planning(ctx, cfg, s2, sa_iters=60, max_rounds=1)["_design"]
    d2 = ck.LNADesign.from_summary(d.summary(), d.fc_hz, d.load)
    f = ck.sweep_grid(d.fc_hz, 0.2)
    a, b = ck.simulate(d, f), ck.simulate(d2, f)
    assert np.allclose(a["gain_db"], b["gain_db"], atol=1e-6) and np.allclose(a["nf_db"], b["nf_db"], atol=1e-6)


def test_large_signal_a1db_square_law_with_cutoff():
    vg = np.arange(0.0, 1.2, 0.005)
    i_d = 1e-2 * np.maximum(vg - 0.4, 0) ** 2           # square law, Vth = 0.4 V
    a = F.large_signal_a1db(vg, i_d, 0.6)               # square law + cut-off: class-AB expansion, never -1 dB
    assert a > 0.99                                      # -> search bound (the swing limit takes over in circuit)
    tanh = 1e-3 * (1 + np.tanh((vg - 0.6) / 0.1))        # saturating curve compresses early
    assert F.large_signal_a1db(vg, tanh, 0.6) < 0.1


def test_common_gate_matches_hand_formula_and_to_y_roundtrip():
    from orfadc.repro import twoport as tp
    op = D.device_op("cascode", 90.0, 0.45)
    s = 2j * math.pi * np.array([30e9])
    y, cy = ck.fet_cs(s, op)
    y2, cy2 = tp.to_y(tp.from_y(y, cy))
    assert np.allclose(y, y2) and np.allclose(cy, cy2)
    y, cy = ck.fet_cs(s, op, include_cdb=False)
    ycg, _ = tp.common_gate(y, cy)
    ycg[:, 1, 1] += s * op.cdb_f
    gm, gds = op.gm_s, op.gds_s
    ref = np.array([[gm + gds + s[0] * op.cgs_f, -gds], [-(gm + gds), gds + s[0] * (op.cdb_f + op.cgd_f)]])
    assert np.allclose(ycg[0], ref)


def test_final_backend_call_cap_stops_the_design_loop():
    from orfadc.config_loader import load_specs
    from pathlib import Path
    sp = {s.id: s for s in load_specs(Path(__file__).resolve().parents[1] / "config" / "specs_table_iii.yaml")}["S2"]

    class Final(T.SurrogateBackend):
        name, n_calls, max_calls = "capped", 0, 2

        def simulate(self, *a, **k):
            self.n_calls += 1
            return super().simulate(*a, **k)

    class Hybrid:
        def __init__(self):
            self.inner, self.final, self.name = T.SurrogateBackend(), Final(), "h"

        def simulate(self, *a, **k):
            return self.inner.simulate(*a, **k)
    ctx = T.ToolContext(sp, backend=Hybrid())
    d = ck.LNADesign.from_summary(  # any design will do
        T.band_planning(ctx, T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0],
                        T.impedance_matching(ctx, T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0],
                                             iters=2, n_particles=3), sa_iters=20, max_rounds=1)["_design"].summary(),
        sp.fc_ghz * 1e9)
    T.fullchain_evaluation(ctx, d)
    assert not ctx.counter.exhausted()
    T.fullchain_evaluation(ctx, d)
    assert ctx.counter.exhausted() and "2 calls" in ctx.counter.hard_stop


def _indefinite(y):
    n = y.shape[0]
    y3 = np.zeros((n, 3, 3), dtype=complex)
    y3[:, :2, :2] = y
    y3[:, :2, 2] = -y.sum(axis=2)
    y3[:, 2, :2] = -y.sum(axis=1)
    y3[:, 2, 2] = y.sum(axis=(1, 2))
    return y3


def test_measured_y3_of_the_model_reproduces_the_model_stage1():
    """A 3-port table built from the engine's own device model must give back the model stage 1 (docs/123)."""
    from dataclasses import replace
    from orfadc.repro import twoport as tp

    def fitted(kind, w, v):
        return replace(D._surrogate_device_op(kind, w, v), gamma=1.3, dg=1.5, tau_s=2e-13, ri_ohm=4.0)

    class Y3:
        def has(self, mode):
            return True

        def y3(self, mode, w, v, f):
            op = fitted("cs" if mode == "cs3" else "cascode", w, v)
            s = 2j * math.pi * np.asarray(f)
            yf, cyf = ck.fet_cs(s, op, include_cdb=(mode == "cs3"))
            y, _ = tp.to_y(tp.series(np.full(s.size, op.rg_ohm, dtype=complex)) @ tp.from_y(yf, cyf))
            y3 = _indefinite(y)
            if mode == "cg3":
                y3[:, 1, 1] += s * op.cdb_f
            return y3, (np.asarray(f) >= 10e9) & (np.asarray(f) <= 50e9)

    class Prov:
        vdd, vb_grid, name = 1.2, D.bias_grid(), "x"

        def op(self, kind, w, v):
            return fitted(kind, w, v)

        def id_ma(self, w, v):
            saved, D._PROVIDER = D._PROVIDER, None
            try:
                return D.drain_current_ma(w, v)
            finally:
                D._PROVIDER = saved

    f = np.array([5e9, 20e9, 30e9, 45e9, 60e9])
    s = 2j * math.pi * f
    prov = Prov()
    D.set_device_provider(prov)
    try:
        op = D.device_op("cs", 60.0, 0.45)
        ref = ck.stage1_cascode(s, op, 150e-12, 30e9)
        prov.y3 = Y3()
        got = ck.stage1_cascode(s, op, 150e-12, 30e9)
    finally:
        D.set_device_provider(None)
    a_ref = (ref[0] @ ref[1] @ ref[2])
    a_got = (got[0] @ got[1] @ got[2])
    assert np.allclose(a_got.abcd, a_ref.abcd, rtol=1e-9, atol=1e-12)
    assert np.allclose(a_got.ca, a_ref.ca, rtol=1e-9, atol=1e-15)
    assert np.allclose(got[0].abcd[1:4, 0, 1], 0)            # Rg folded into the measured CS in range
    assert got[0].abcd[0, 0, 1] == pytest.approx(op.rg_ohm)  # model outside the table (5 GHz)


def test_y3table_interpolation_and_range():
    from orfadc.repro import pdk3
    f = [10e9, 30e9, 50e9]
    rows = []
    for w in (40.0, 80.0):
        for v in (0.4, 0.6):
            y = [[[[w * v * (1 + i + 3 * j) * fk / 1e10, w * 0.001] for j in range(3)] for i in range(3)] for fk in f]
            rows.append({"mode": "cs3", "w_um": w, "nr": 2, "multi": 1, "vgs_v": v, "f_hz": f, "y3": y})
    t = pdk3.Y3Table(rows)
    assert t.has("cs3") and not t.has("cg3")
    y, ok = t.y3("cs3", 60.0, 0.5, np.array([5e9, 20e9, 30e9, 60e9]))
    assert list(ok) == [False, True, True, False]
    assert y[2, 0, 0].real == pytest.approx(60 * 0.5 * 3, rel=1e-9)     # per-micron scaling, linear in Vgs
    assert y[1, 0, 1].real == pytest.approx(60 * 0.5 * 4 * 2, rel=1e-9)  # linear in frequency
    red = pdk3.kron(y, keep=[0, 1], drop=2)
    assert red.shape == (4, 2, 2)


def test_measured_diff_y2_of_the_model_reproduces_the_model_diff_stage():
    """cs2 rows (grounded-source Y incl. Rg) + the netlist's CN terms must equal the cross-coupled model stage."""
    from dataclasses import replace
    from orfadc.repro import twoport as tp

    def fitted(kind, w, v):
        return replace(D._surrogate_device_op(kind, w, v), gamma=1.3, dg=1.5, tau_s=2e-13, ri_ohm=4.0)

    class Y2:
        def has(self, mode):
            return mode == "cs2"

        def y3(self, mode, w, v, f):
            op = fitted("diff", w, v)
            s = 2j * math.pi * np.asarray(f)
            yf, cyf = ck.fet_cs(s, op)
            y, _ = tp.to_y(tp.series(np.full(s.size, op.rg_ohm, dtype=complex)) @ tp.from_y(yf, cyf))
            return y, np.ones(s.size, bool)

    class Prov:
        vdd, vb_grid, name, neutralization = 1.2, D.bias_grid(), "x", "cross_coupled"

        def op(self, kind, w, v):
            return fitted(kind, w, v)

        def id_ma(self, w, v):
            saved, D._PROVIDER = D._PROVIDER, None
            try:
                return D.drain_current_ma(w, v)
            finally:
                D._PROVIDER = saved

    s = 2j * math.pi * np.array([10e9, 30e9, 50e9])
    prov = Prov()
    D.set_device_provider(prov)
    try:
        op = D.device_op("diff", 81.0, 0.45)
        rg, dev = ck.stage_diff(s, op)
        ref = rg @ dev
        prov.y3 = Y2()
        rg2, dev2 = ck.stage_diff(s, op)
    finally:
        D.set_device_provider(None)
    # the model puts CN behind Rg, the netlist (and the measured path) at the gate terminal: compare against that
    yf, cyf = ck.fet_cs(s, op)
    y, _ = tp.to_y(tp.series(np.full(s.size, op.rg_ohm, dtype=complex)) @ tp.from_y(yf, cyf))
    y = y + (s * op.cgd_f * (1 - D.TECH.neutralization_residual))[:, None, None]
    got = rg2 @ dev2
    assert np.allclose(got.abcd, tp.from_y(y, np.zeros_like(y)).abcd, rtol=1e-9)
    assert np.allclose(got.ca, ref.ca)                       # noise kept from the model


def test_stage1_noise_scale_scales_only_the_noise():
    class Prov:
        vdd, vb_grid, name, noise1_scale = 1.2, D.bias_grid(), "x", 1.2

        def op(self, kind, w, v):
            return D._surrogate_device_op(kind, w, v)

        def id_ma(self, w, v):
            saved, D._PROVIDER = D._PROVIDER, None
            try:
                return D.drain_current_ma(w, v)
            finally:
                D._PROVIDER = saved
    s = 2j * math.pi * np.array([30e9])
    op = D.device_op("cs", 60.0, 0.45)
    ref = ck.stage1_cascode(s, op, 150e-12, 30e9)
    D.set_device_provider(Prov())
    try:
        got = ck.stage1_cascode(s, op, 150e-12, 30e9)
    finally:
        D.set_device_provider(None)
    for a, b in zip(ref, got):
        assert np.allclose(a.abcd, b.abcd) and np.allclose(1.2 * a.ca, b.ca)


def test_casc_netlist_and_noise_factor_identity():
    from orfadc.repro import pdk3, pdk_v2 as P
    cfg = {"vdd": 1.1, "toplevel": "/x.scs", "section": "tt", "nmos": "nmos_rf", "lr": "40n", "wr_um": 2.0}
    lay = P.layout_for(72, 2.0, list(range(2, 65, 2)))
    net = pdk3.casc_netlist(cfg, lay, [0.5, 0.6], [5e9, 30e9])
    assert "M1 (cas g 0 0)" in net and "MCG (d vc cas 0)" in net and "donoise=yes" in net and "opts options temp=" in net

    class Prov:
        vdd, vb_grid, name = 1.2, D.bias_grid(), "x"

        def op(self, kind, w, v):
            return D._surrogate_device_op(kind, w, v)

        def id_ma(self, w, v):
            saved, D._PROVIDER = D._PROVIDER, None
            try:
                return D.drain_current_ma(w, v)
            finally:
                D._PROVIDER = saved
    prov = Prov()
    D.set_device_provider(prov)
    try:
        f = np.array([10e9, 30e9])
        rows = []
        for w in (45.0, 90.0):
            for v in (0.45, 0.6):
                op = D.device_op("cascode", w, v)
                rg, cs, cg = ck.stage1_cascode(2j * math.pi * f, op, 0.0, 30e9)
                fm = (rg @ cs @ cg).fmin()
                rows.append({"w_um": w, "vgs_v": v, "f_hz": list(f), "fmin": list(1 + 1.3 * (fm - 1))})
        cn = pdk3.CascNoise(rows)
        assert np.allclose(cn.k(60.0, 0.5, f), 1.3, rtol=1e-6)
        prov.casc_noise = cn
        op = D.device_op("cascode", 45.0, 0.45)
        rg, cs, cg = ck.stage1_cascode(2j * math.pi * f, op, 0.0, 30e9)
        assert np.allclose((rg @ cs @ cg).fmin(), rows[0]["fmin"], rtol=1e-9)
    finally:
        D.set_device_provider(None)
