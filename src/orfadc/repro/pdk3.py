"""Three-terminal (gate, drain, source; bulk grounded) Y tables for the stage-1 cascode (docs/123).

The grounded-source two-port fit cannot see what changes when the source is lifted off the bulk: the
degenerated CS (source on Ls) and the common-gate device (source at VDD - Vgs) both put the body and the
source-side parasitics of the RF cell into the signal path.  Here the cell is characterised as a 3-port at
its in-circuit bias and the engine uses the measured Y3 directly (interpolated in W, Vgs and frequency);
noise still comes from the fitted two-port model.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath

import numpy as np

from . import pdk_v2 as P

# Stage-1 noise of the fitted grounded-source model, scaled to match Spectre in circuit (source on Ls / lifted
# above the bulk).  Calibrated on S2 (critical + full chain) and checked on S6/S7 Spectre runs: NF@fc within
# +-0.1 dB (docs/123 §8).  Override with ORFADC_PDK_NOISE1_SCALE.
NOISE1_SCALE = 1.2

MODES = ("cs3", "cg3", "cs2")   # cs2: grounded-source two-port at the diff-stage bias (docs/123 §7)
CHAR3_MODES = ("cs3", "cg3")    # measured by characterize3; cs2 rows come from twoport_rows() of a pdk_char table


def char3_netlist(cfg: dict, lay: dict, vbs: list[float], mode: str, freqs: list[float],
                  vds_cs: float | None = None) -> str:
    """mode cs3: gate = vb, source = 0, drain = vds_cs.  mode cg3: gate = drain = VDD, source = VDD - vb.
    ``vds_cs`` defaults to the config's ``vds_cs`` (crn40lp: 0.5 V; N65: 0.6 V = VDD/2, docs/132)."""
    vdd = float(cfg["vdd"])
    vds_cs = float(cfg.get("vds_cs", 0.5)) if vds_cs is None else vds_cs
    vals = " ".join(f"{v:.4g}" for v in vbs)
    if mode == "cs3":
        bias = ["VG (vg 0) vsource dc=vb", f"VD (vd 0) vsource dc={vds_cs:g}", "VS (vs 0) vsource dc=0"]
    elif mode == "cg3":
        bias = [f"VG (vg 0) vsource dc={vdd:g}", f"VD (vd 0) vsource dc={vdd:g}", f"VS (vs 0) vsource dc={vdd:g}-vb"]
    else:
        raise ValueError(mode)
    lines = P._header(cfg) + [f"parameters vb={vbs[0]:.4g}"] + bias + [
        "LBG (vg g) inductor l=1", "LBD (vd d) inductor l=1", "LBS (vs s) inductor l=1",
        "CBG (p1 g) capacitor c=1", "CBD (p2 d) capacitor c=1", "CBS (p3 s) capacitor c=1",
        "P1 (p1 0) port r=50 num=1", "P2 (p2 0) port r=50 num=2", "P3 (p3 0) port r=50 num=3",
        P._inst(cfg, "M1", "d", "g", "s", "0", lay),
        f"swp sweep param=vb values=[{vals}] {{",
        f"  sp1 sp values=[{' '.join(f'{f:.6g}' for f in sorted(freqs))}] ports=[P1 P2 P3]",
        "}", "save VD:p"]
    return "\n".join(lines) + "\n"


def s_to_y3(s: np.ndarray, z0: float = 50.0) -> np.ndarray:
    eye = np.eye(3)
    return (eye - s) @ np.linalg.inv(eye + s) / z0


def extract3(local: Path, lay: dict, vbs: list[float], mode: str) -> list[dict]:
    from orfadc.cadence.psfascii_reader import parse_complex_trace
    psf = local / "psf"
    files = sorted((p for p in psf.iterdir() if p.name.endswith("sp1.sp")),
                   key=lambda p: [int(x) for x in re.findall(r"-(\d+)_", p.name)] or [0])
    if len(files) != len(vbs):
        raise ValueError(f"expected {len(vbs)} sp results, found {len(files)}")
    rows = []
    for vb, f in zip(vbs, files):
        fs = None
        sm = {}
        for i in range(3):
            for j in range(3):
                fs, v = parse_complex_trace(f, f"s{i + 1}{j + 1}")
                sm[(i, j)] = v
        ys = []
        for k in range(len(fs)):
            s = np.array([[sm[(i, j)][k] for j in range(3)] for i in range(3)])
            y = s_to_y3(s)
            ys.append([[[float(y[i, j].real), float(y[i, j].imag)] for j in range(3)] for i in range(3)])
        rows.append({"mode": mode, "w_um": lay["w_um"], "nr": lay["nr"], "multi": lay["multi"], "vgs_v": vb,
                     "f_hz": [float(x) for x in fs], "y3": ys})
    return rows


def characterize3(runner, cfg: dict, widths: list[float], vbs: list[float], freqs: list[float],
                  out_root: Path | None = None, usable_nr: list[int] | None = None) -> dict:
    ts = time.strftime("%Y%m%dT%H%M%S")
    local = (out_root or P.ROOT / "results" / "runs" / "pdk_char3") / ts
    rroot = str(PurePosixPath(runner.config.remote_root) / f"pdk_char3_{ts}")
    usable = usable_nr or list(range(2, 65, 2))
    rep: dict = {"ts": ts, "local_dir": str(local), "spectre_runs": 0, "runs": {}, "rows": []}
    for mode in CHAR3_MODES:
        for w in widths:
            lay = P.layout_for(w, float(cfg["wr_um"]), usable)
            tag = f"{mode}_w{w:g}"
            st = P.run_spectre(runner, char3_netlist(cfg, lay, vbs, mode, freqs), f"{rroot}/{tag}", local / tag)
            rep["spectre_runs"] += 1
            entry = {"layout": lay, "steps": st}
            if st["ok"]:
                try:
                    r = extract3(local / tag, lay, vbs, mode)
                    for x in r:
                        x["w_target_um"] = w
                    rep["rows"] += r
                except Exception as exc:
                    entry["parse_error"] = repr(exc)[:400]
            rep["runs"][tag] = entry
    local.mkdir(parents=True, exist_ok=True)
    (local / "y3_table.json").write_text(json.dumps(rep), encoding="utf-8")
    return rep


class Y3Table:
    """Y3(f) per (mode, W, Vgs); per-micron scaling in W, linear in Vgs and frequency (inside the grid)."""

    def __init__(self, rows: list[dict]):
        self.tabs: dict[str, dict] = {}
        for mode in MODES:
            rr = [r for r in rows if r["mode"] == mode]
            if not rr:
                continue
            by_w: dict[float, list] = defaultdict(list)
            for r in rr:
                by_w[float(r["w_um"])].append(r)
            widths = np.array(sorted(by_w))
            vgs = np.array(sorted({float(r["vgs_v"]) for r in rr}))
            f = np.array(rr[0]["f_hz"])
            n = len(rr[0]["y3"][0])
            data = np.full((len(widths), len(vgs), len(f), n, n), np.nan, dtype=complex)
            for i, w in enumerate(widths):
                for r in by_w[w]:
                    j = int(np.argmin(np.abs(vgs - r["vgs_v"])))
                    y = np.array(r["y3"])
                    data[i, j] = (y[..., 0] + 1j * y[..., 1]) / w
            self.tabs[mode] = {"w": widths, "vgs": vgs, "f": f, "y": data}

    @classmethod
    def from_json(cls, path: Path) -> "Y3Table":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["rows"])

    def has(self, mode: str) -> bool:
        return mode in self.tabs

    def y3(self, mode: str, w_um: float, vgs: float, f_hz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returns (Y3 of shape (N,3,3), mask of frequencies inside the characterised range)."""
        t = self.tabs[mode]
        ws, vs, fs, y = t["w"], t["vgs"], t["f"], t["y"]
        i = int(np.clip(np.searchsorted(ws, w_um), 1, len(ws) - 1))
        a = float(np.clip((w_um - ws[i - 1]) / (ws[i] - ws[i - 1]), 0, 1))
        j = int(np.clip(np.searchsorted(vs, vgs), 1, len(vs) - 1))
        b = float(np.clip((vgs - vs[j - 1]) / (vs[j] - vs[j - 1]), 0, 1))
        yw = (1 - a) * ((1 - b) * y[i - 1, j - 1] + b * y[i - 1, j]) + a * ((1 - b) * y[i, j - 1] + b * y[i, j])
        f = np.asarray(f_hz, float)
        n = y.shape[-1]
        out = np.empty((f.size, n, n), dtype=complex)
        for p in range(n):
            for q in range(n):
                out[:, p, q] = np.interp(f, fs, yw[:, p, q].real) + 1j * np.interp(f, fs, yw[:, p, q].imag)
        return out * w_um, (f >= fs[0]) & (f <= fs[-1])


def kron(y3: np.ndarray, keep: list[int], drop: int, y_drop_extra: np.ndarray | None = None) -> np.ndarray:
    """Eliminate node ``drop`` (optionally after adding a shunt admittance to it)."""
    y = y3.copy()
    if y_drop_extra is not None:
        y[:, drop, drop] += y_drop_extra
    a = y[:, keep][:, :, keep]
    b = y[:, keep][:, :, [drop]]
    c = y[:, [drop]][:, :, keep]
    d = y[:, drop, drop][:, None, None]
    return a - b @ c / d


def twoport_rows(char_dir: Path, mode: str = "cs2") -> list[dict]:
    """Measured grounded-source Y (all characterised frequencies) of a ``pdk-characterize`` run, as Y3Table rows."""
    from .pdk_fit import read_point
    rep = json.loads((Path(char_dir) / "device_table.json").read_text(encoding="utf-8"))
    rows = []
    by: dict = defaultdict(list)
    for r in rep["rows"]:
        by[r["w_target_um"]].append(r)
    for w, rr in by.items():
        psf = Path(char_dir) / f"w{w:g}" / "psf"
        sps = sorted((p for p in psf.iterdir() if p.name.endswith("sp1.sp") and "noise" not in p.name),
                     key=lambda p: int(re.findall(r"-(\d+)_", p.name)[0]))
        vbs = sorted({float(x["vgs_v"]) for x in rep["rows"] if x["w_target_um"] == w})
        for r in rr:
            pt = read_point(sps[vbs.index(float(r["vgs_v"]))])
            rows.append({"mode": mode, "w_um": r["w_um"], "nr": r["nr"], "multi": r["multi"], "vgs_v": r["vgs_v"],
                         "f_hz": pt["f"],
                         "y3": [[[[float(y[a, b].real), float(y[a, b].imag)] for b in range(2)] for a in range(2)]
                                for y in pt["y"]]})
    return rows


def install_y3(path: Path | None = None, diff_char: Path | None = None):
    """Attach the newest 3-port table (stage 1) and, when a multi-frequency full-Vds characterisation exists, the
    measured diff-stage two-port Y (``cs2``) to the active PDK provider."""
    from . import device as D
    prov = D.device_provider()
    if prov is None:
        raise RuntimeError("install a PDK provider first (pdk_v2.install_table)")
    cands = sorted((P.ROOT / "results" / "runs" / "pdk_char3").glob("*/y3_table.json"))
    path = path or (cands[-1] if cands else None)
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["rows"] if path else []
    if diff_char is None and os.environ.get("ORFADC_PDK_Y2", "1") != "0":
        diff_char = latest_multifreq_char(float(getattr(prov, "vdd", 0.0)))
    if diff_char is not None:
        rows = rows + twoport_rows(diff_char)
    if not rows:
        return None
    prov.y3 = Y3Table(rows)
    if path:
        prov.noise1_scale = float(os.environ.get("ORFADC_PDK_NOISE1_SCALE", NOISE1_SCALE))
    prov.name += ("_y3" if path else "") + ("_y2" if diff_char is not None else "") + \
        (f"_n{prov.noise1_scale:g}" if path and prov.noise1_scale != 1.0 else "")
    return prov.y3


def latest_multifreq_char(vds: float) -> Path | None:
    """Newest raw characterisation at drain bias ``vds`` with more than two frequencies (psf kept)."""
    best = None
    for p in sorted((P.ROOT / "results" / "runs" / "pdk_char").glob("*/device_table.json")):
        try:
            rep = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if len(rep.get("freqs_hz") or []) > 2 and abs(float(rep.get("vds_v") or 0) - vds) < 1e-6 and \
                any((p.parent / d).is_dir() for d in ("w45", "w45.0")):
            best = p.parent
    return best


# ---------------------------------------------------------------------------------------------------------------
# Stage-1 cascode-cell noise (docs/123 §11): replaces the global NOISE1_SCALE by a per-(W, Vgs, f) factor measured
# on the in-circuit cell (CS + CG of equal width, CG gate at VDD, source grounded) with Spectre's two-port noise.
# ---------------------------------------------------------------------------------------------------------------

def casc_netlist(cfg: dict, lay: dict, vbs: list[float], freqs: list[float]) -> str:
    from .backend_cadence import T_NOISE_C
    vdd = float(cfg["vdd"])
    vals = " ".join(f"{v:.4g}" for v in vbs)
    lines = P._header(cfg) + [f"opts options temp={T_NOISE_C} tnom=27", f"parameters vb={vbs[0]:.4g}",
                              "VG (vg 0) vsource dc=vb", f"VD (vd 0) vsource dc={vdd:g}", f"VC (vc 0) vsource dc={vdd:g}",
                              "LBG (vg g) inductor l=1", "LBD (vd d) inductor l=1",
                              "CBG (p1 g) capacitor c=1", "CBD (p2 d) capacitor c=1",
                              "P1 (p1 0) port r=50 num=1", "P2 (p2 0) port r=50 num=2",
                              P._inst(cfg, "M1", "cas", "g", "0", "0", lay),
                              P._inst(cfg, "MCG", "d", "vc", "cas", "0", lay),
                              f"swp sweep param=vb values=[{vals}] {{",
                              f"  sp1 sp values=[{' '.join(f'{f:.6g}' for f in sorted(freqs))}] ports=[P1 P2] "
                              "donoise=yes oprobe=P2 iprobe=P1",
                              "}", "save VD:p"]
    return "\n".join(lines) + "\n"


def characterize_casc(runner, cfg: dict, widths: list[float], vbs: list[float], freqs: list[float],
                      out_root: Path | None = None, usable_nr: list[int] | None = None) -> dict:
    from .pdk_fit import read_point
    ts = time.strftime("%Y%m%dT%H%M%S")
    local = (out_root or P.ROOT / "results" / "runs" / "pdk_casc") / ts
    rroot = str(PurePosixPath(runner.config.remote_root) / f"pdk_casc_{ts}")
    usable = usable_nr or list(range(2, 65, 2))
    rep: dict = {"ts": ts, "local_dir": str(local), "spectre_runs": 0, "runs": {}, "rows": []}
    for w in widths:
        lay = P.layout_for(w, float(cfg["wr_um"]), usable)
        tag = f"casc_w{w:g}"
        st = P.run_spectre(runner, casc_netlist(cfg, lay, vbs, freqs), f"{rroot}/{tag}", local / tag)
        rep["spectre_runs"] += 1
        entry = {"layout": lay, "steps": st}
        if st["ok"]:
            try:
                psf = local / tag / "psf"
                sps = sorted((p for p in psf.iterdir() if p.name.endswith("sp1.sp") and "noise" not in p.name),
                             key=lambda p: [int(x) for x in re.findall(r"-(\d+)_", p.name)] or [0])
                for vb, sp in zip(vbs, sps):
                    pt = read_point(sp)
                    rep["rows"].append({"w_um": lay["w_um"], "w_target_um": w, "vgs_v": vb, "f_hz": pt["f"],
                                        "fmin": pt["fmin"], "rn": pt["rn"], "gopt": pt["gopt"], "bopt": pt["bopt"],
                                        "y": [[[float(v.real), float(v.imag)] for v in row] for y in pt["y"] for row in y]})
            except Exception as exc:
                entry["parse_error"] = repr(exc)[:400]
        rep["runs"][tag] = entry
    local.mkdir(parents=True, exist_ok=True)
    (local / "casc_noise.json").write_text(json.dumps(rep), encoding="utf-8")
    return rep


class CascNoise:
    """Measured Fmin of the stage-1 cell -> per-(W, Vgs, f) noise factor for the engine's stage-1 model.

    k is chosen so that the engine's cell (Rg + CS + CG, Ls = 0) reaches the measured Fmin when its stage-1
    correlation matrix is multiplied by k (Fmin - 1 scales linearly with a common factor on CA)."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.ws = np.array(sorted({float(r["w_um"]) for r in rows}))
        self.vs = np.array(sorted({float(r["vgs_v"]) for r in rows}))
        self.f = np.array(rows[0]["f_hz"])
        self._k: dict | None = None

    @classmethod
    def from_json(cls, path: Path) -> "CascNoise":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["rows"])

    def _table(self):
        """k[w, v, f] from the model at each characterised point (built lazily with the active provider)."""
        if self._k is not None:
            return self._k
        from . import circuit as ck, device as D
        prov = D.device_provider()
        saved = getattr(prov, "noise1_scale", 1.0), getattr(prov, "casc_noise", None)
        prov.noise1_scale, prov.casc_noise = 1.0, None
        s = 2j * np.pi * self.f
        k = np.full((len(self.ws), len(self.vs), len(self.f)), np.nan)
        try:
            for r in self.rows:
                i = int(np.argmin(abs(self.ws - r["w_um"])))
                j = int(np.argmin(abs(self.vs - r["vgs_v"])))
                op = D.device_op("cascode", float(r["w_um"]), float(r["vgs_v"]))
                rg, cs, cg = ck.stage1_cascode(s, op, 0.0, 30e9)
                fm_model = (rg @ cs @ cg).fmin()
                fm_meas = np.asarray(r["fmin"], float)                  # linear, as in pdk_fit.read_point
                k[i, j] = np.clip((fm_meas - 1) / np.maximum(fm_model - 1, 1e-6), 0.5, 3.0)
        finally:
            prov.noise1_scale, prov.casc_noise = saved
        self._k = k
        return k

    def k(self, w_um: float, vgs: float, f_hz: np.ndarray) -> np.ndarray:
        k = self._table()
        i = int(np.clip(np.searchsorted(self.ws, w_um), 1, len(self.ws) - 1))
        a = float(np.clip((w_um - self.ws[i - 1]) / (self.ws[i] - self.ws[i - 1]), 0, 1))
        j = int(np.clip(np.searchsorted(self.vs, vgs), 1, len(self.vs) - 1))
        b = float(np.clip((vgs - self.vs[j - 1]) / (self.vs[j] - self.vs[j - 1]), 0, 1))
        kk = (1 - a) * ((1 - b) * k[i - 1, j - 1] + b * k[i - 1, j]) + a * ((1 - b) * k[i, j - 1] + b * k[i, j])
        kk = np.where(np.isfinite(kk), kk, NOISE1_SCALE)
        return np.interp(np.asarray(f_hz, float), self.f, kk)
