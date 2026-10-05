"""B16 fixes (docs/121 §3): fit the engine's device model to PDK two-port data.

For every characterised (W, Vgs, Vds) point the Spectre run gives Y (S) and the two-port noise parameters
(Fmin, Rn, Gopt, Bopt) at 5 and 30 GHz.  We fit the engine's CS model — intrinsic Y with a transit delay
``gm*exp(-j w tau)`` behind a series gate resistance, van der Ziel drain/gate noise with a per-device
``gamma`` and ``delta/gamma`` (|c| = 0.395 fixed) — so that the engine reproduces the PDK cell's input
impedance (S11), gain and noise across the band instead of using lumped values taken at one frequency.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from . import twoport as tp
from .device import TECH

FREQS = (5e9, 30e9)


def ca_from_noise_params(fmin: float, rn: float, gopt: float, bopt: float) -> np.ndarray:
    """ABCD-form correlation matrix (normalised to 4kT0) from (Fmin linear, Rn ohm, Yopt S)."""
    yopt = complex(gopt, bopt)
    c12 = (fmin - 1) / 2 - rn * np.conj(yopt)
    return np.array([[rn, c12], [np.conj(c12), rn * abs(yopt) ** 2]], dtype=complex)


def model_twoport(f_hz: np.ndarray, p: dict) -> tp.TwoPort:
    """Series Rg + intrinsic CS (same equations as circuit.fet_cs, plus delay and per-device noise)."""
    s = 2j * math.pi * np.asarray(f_hz, float)
    cgs, cgd, cdb, gm, tau, gds = (p[k] for k in ("cgs", "cgd", "cdb", "gm", "tau", "gds"))
    nqs = 1.0 / (1.0 + s * cgs * p.get("ri", 0.0))   # channel (NQS) resistance in series with Cgs
    n = s.size
    y = np.zeros((n, 2, 2), dtype=complex)
    y[:, 0, 0] = s * cgs * nqs + s * cgd
    y[:, 0, 1] = -s * cgd
    y[:, 1, 0] = gm * np.exp(-s * tau) * nqs - s * cgd
    y[:, 1, 1] = gds + s * (cgd + cdb)
    gd0 = gm / TECH.alpha
    sdd = p["gamma"] * gd0
    sgg = p["dg"] * p["gamma"] * (np.abs(s) * cgs) ** 2 / (5 * gd0)
    cy = np.zeros_like(y)
    cy[:, 0, 0] = sgg
    cy[:, 1, 1] = sdd
    cy[:, 0, 1] = TECH.corr_c * np.sqrt(sgg * sdd)
    cy[:, 1, 0] = np.conj(cy[:, 0, 1])
    return tp.series(np.full(n, p["rg"], dtype=complex)) @ tp.from_y(y, cy)


def _abcd_to_y(a: np.ndarray) -> np.ndarray:
    A, B, C, D = a[0, 0], a[0, 1], a[1, 0], a[1, 1]
    return np.array([[D / B, (B * C - A * D) / B], [-1 / B, A / B]])


def noise_params(t: tp.TwoPort, k: int) -> tuple[float, float, complex]:
    ca = t.ca[k]
    rn = ca[0, 0].real
    c22 = ca[1, 1].real
    c12 = ca[0, 1]
    gopt = math.sqrt(max(c22 / rn - (c12.imag / rn) ** 2, 1e-30))
    bopt = c12.imag / rn
    fmin = 1 + 2 * (c12.real + rn * gopt)
    return fmin, rn, complex(gopt, bopt)


def read_point(sp: Path) -> dict:
    """Y matrices and noise parameters at both frequencies from one swp-NNN_sp1.sp / .noise.sp pair."""
    from orfadc.cadence.psfascii_reader import parse_complex_trace
    fs, s11 = parse_complex_trace(sp, "s11")
    s12, s21, s22 = (parse_complex_trace(sp, k)[1] for k in ("s12", "s21", "s22"))
    eye = np.eye(2)
    ys = [(eye - S) @ np.linalg.inv(eye + S) / 50.0 for S in
          (np.array([[s11[i], s12[i]], [s21[i], s22[i]]]) for i in range(len(fs)))]
    txt = sp.with_name(sp.name.replace("sp1.sp", "sp1.noise.sp")).read_text(errors="replace")
    val = txt[txt.index("VALUE"):]

    def grab(key):
        return [float(x) for x in re.findall(r'^"%s" ([-+0-9.eE]+)$' % key, val, re.M)]
    return {"f": list(fs), "y": ys, "fmin": grab("Fmin"), "rn": grab("RN"), "gopt": grab("Gopt"), "bopt": grab("Bopt")}


def initial_guess(pt: dict) -> dict:
    y5, y30 = pt["y"][0], pt["y"][-1]
    w5 = 2 * math.pi * pt["f"][0]
    cgd = -y5[0, 1].imag / w5
    cgs = max(y5[0, 0].imag / w5 - cgd, 1e-16)
    cdb = max(y5[1, 1].imag / w5 - cgd, 1e-16)
    gm = abs(y5[1, 0] - y5[0, 1])
    gds = max(y5[1, 1].real, 1e-6)
    rg = max((1 / y30[0, 0]).real, 0.1)
    return {"cgs": cgs, "cgd": cgd, "cdb": cdb, "gm": gm, "tau": 1e-13, "gds": gds, "rg": rg / 2, "ri": rg / 2,
            "gamma": 1.1, "dg": 2.0}


_KEYS = ("cgs", "cgd", "cdb", "gm", "tau", "gds", "rg", "ri", "gamma", "dg")
_SCALE = {"cgs": 1e-14, "cgd": 1e-14, "cdb": 1e-14, "gm": 1e-2, "tau": 1e-12, "gds": 1e-3, "rg": 1.0, "ri": 1.0,
          "gamma": 1.0, "dg": 1.0}


def fit_point(pt: dict) -> dict:
    """Least-squares fit of the 9 model parameters to Y (relative) and noise parameters at both frequencies."""
    from scipy.optimize import least_squares
    f = np.asarray(pt["f"], float)
    p0 = initial_guess(pt)
    x0 = np.array([p0[k] / _SCALE[k] for k in _KEYS])
    lo = np.array([1e-3, 1e-3, 1e-3, 1e-4, -5, 1e-3, 0.0, 0.0, 0.05, 0.05])
    hi = np.array([1e3, 1e3, 1e3, 1e2, 5, 1e3, 1e3, 1e4, 10.0, 20.0])

    def unpack(x):
        return {k: x[i] * _SCALE[k] for i, k in enumerate(_KEYS)}

    def resid(x):
        t = model_twoport(f, unpack(x))
        r = []
        for k in range(len(f)):
            ym = _abcd_to_y(t.abcd[k])
            ys = pt["y"][k]
            d = (ym - ys) / np.maximum(np.abs(ys), 1e-6)          # each Y element relative to its own size
            r += list(d.real.ravel()) + list(d.imag.ravel())
            for i in (0, 1):                                     # input/output conductance set S11/S22 and gain
                r.append((ym[i, i].real - ys[i, i].real) / max(abs(ys[i, i].real), 1e-6))
            fm, rn, yo = noise_params(t, k)
            r += [(fm - pt["fmin"][k]) / max(pt["fmin"][k] - 1, 0.02),
                  (rn - pt["rn"][k]) / pt["rn"][k],
                  (yo.real - pt["gopt"][k]) / abs(complex(pt["gopt"][k], pt["bopt"][k])),
                  (yo.imag - pt["bopt"][k]) / abs(complex(pt["gopt"][k], pt["bopt"][k]))]
        return np.array(r)
    sol = least_squares(resid, np.clip(x0, lo, hi), bounds=(lo, hi), x_scale="jac", max_nfev=400)
    out = unpack(sol.x)
    out["fit_rms"] = float(np.sqrt(np.mean(sol.fun ** 2)))
    return out


def refit_table(char_dir: Path) -> list[dict]:
    """Re-read every width/bias of a characterisation run and attach the fitted model to its rows."""
    import json
    rep = json.loads((char_dir / "device_table.json").read_text(encoding="utf-8"))
    rows = rep["rows"]
    by = {}
    for r in rows:
        by.setdefault(r["w_target_um"], []).append(r)
    for w, rr in by.items():
        psf = char_dir / f"w{w:g}" / "psf"
        sps = sorted((p for p in psf.iterdir() if p.name.endswith("sp1.sp") and "noise" not in p.name),
                     key=lambda p: int(re.findall(r"-(\d+)_", p.name)[0]))
        vbs = sorted(r["vgs_v"] for r in rr)
        for r in rr:
            pt = read_point(sps[vbs.index(r["vgs_v"])])
            fit = fit_point(pt)
            r["fit"] = fit
            r["noise30"] = {"fmin": pt["fmin"][-1], "rn": pt["rn"][-1], "gopt": pt["gopt"][-1], "bopt": pt["bopt"][-1]}
    rep["rows"] = rows
    rep["fit_note"] = "pdk_fit.fit_point: Rg + CS(gm*exp(-jw tau)) + per-device gamma, delta/gamma; |c|=0.395"
    return rep


def large_signal_a1db(vg: np.ndarray, i_d: np.ndarray, vgs0: float, n_theta: int = 256) -> float:
    """Gate amplitude at which the fundamental of Id(Vgs0 + A cos t) is 1 dB below gm*A.

    Uses the measured DC transfer curve (cut-off and gm saturation included); above the sweep the curve is
    extended linearly with its last slope."""
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    slope_hi = (i_d[-1] - i_d[-6]) / (vg[-1] - vg[-6])

    def f(v):
        out = np.interp(v, vg, i_d)
        hi = v > vg[-1]
        out[hi] = i_d[-1] + slope_hi * (v[hi] - vg[-1])
        return np.maximum(out, 0.0)
    h = 1e-3
    gm = (np.interp(vgs0 + h, vg, i_d) - np.interp(vgs0 - h, vg, i_d)) / (2 * h)
    if gm <= 0:
        return float("nan")
    target = 10 ** (-1 / 20)
    lo, hi = 1e-3, 1.0
    for _ in range(60):
        a = 0.5 * (lo + hi)
        i1 = 2 * np.mean(f(vgs0 + a * np.cos(th)) * np.cos(th))
        if i1 / (gm * a) > target:
            lo = a
        else:
            hi = a
    return 0.5 * (lo + hi)


def add_large_signal(char_dir: Path, rep: dict) -> dict:
    from orfadc.cadence.psfascii_reader import parse_scalar_trace
    for w in sorted({r["w_target_um"] for r in rep["rows"]}):
        vg, idp = parse_scalar_trace(char_dir / f"w{w:g}" / "psf" / "dcsw.dc", "VD:p", sweep_variable="vb")
        vg, i_d = np.asarray(vg), -np.asarray(idp)
        for r in rep["rows"]:
            if r["w_target_um"] == w:
                r["a1db_ls_v"] = large_signal_a1db(vg, i_d, float(r["vgs_v"]))
    rep["large_signal_note"] = "a1db_ls_v: 1-dB point of the fundamental from the DC transfer curve (pdk_fit)"
    return rep
