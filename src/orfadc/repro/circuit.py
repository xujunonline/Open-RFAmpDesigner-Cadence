"""Three-stage LNA of Fig. 3 on the surrogate two-port engine.

Chain (half-circuit / single-ended equivalent):

    RFin -> shunt Lpar -> series Lg -> [Stage1: Rg, CS+Ls, CG cascode]
         -> MCR1 (balun, Stage-2 variables k,L1,L2,R1,R2,C1,C2)
         -> [Stage2: Rg, neutralised CS] -> MCR2 (k,w0,Q0,C)
         -> [Stage3: Rg, neutralised CS] -> MCR3 (k,w0,Q0,C) -> RL || CL

"Gain" is the voltage gain 2*Vload/Vs relative to the 50-ohm source, which
equals S21 for a 50-ohm load and is the natural reading of the paper's gain
for the 1787 ohm || 62 fF load.
"""
from __future__ import annotations

import math
import os
from dataclasses import replace, asdict, dataclass, field
from functools import reduce

import numpy as np

from . import twoport as tp
from .device import TECH, DeviceOP, K_B_T0, device_op, drain_current_ma
from .device import vdd as device_vdd

Q_IND = float(os.environ.get("ORFADC_Q_IND", "15"))      # on-chip (MCR) inductor Q (docs/126 sensitivity)
Q_MATCH = float(os.environ.get("ORFADC_Q_MATCH", "25"))   # input-matching inductor Q (docs/126 sensitivity)
DEFAULT_LOAD = (1787.0, 62e-15)
HARD_CLIP_1DB = 1.262  # drive/clip ratio at which a hard limiter's fundamental is compressed by 1 dB


@dataclass
class MCRPhysical:
    k: float
    l1_h: float
    l2_h: float
    r1_ohm: float      # added shunt resistor, primary (inf = none)
    r2_ohm: float
    c1_f: float        # added shunt capacitance, primary
    c2_f: float
    q_ind: float = Q_IND
    f_loss_hz: float = 30e9   # frequency at which the inductor series loss is fixed
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(l1_ph=self.l1_h * 1e12, l2_ph=self.l2_h * 1e12,
                 c1_ff=self.c1_f * 1e15, c2_ff=self.c2_f * 1e15)
        return d


@dataclass
class LNADesign:
    ops: list[DeviceOP]                 # stage1 cascode, stage2 diff-half, stage3 diff-half
    stage_currents_ma: list[float]
    ls_h: float
    lg_h: float
    lpar_h: float
    mcr1: MCRPhysical
    mcr2: MCRPhysical
    mcr3: MCRPhysical
    fc_hz: float
    load: tuple[float, float] = DEFAULT_LOAD
    meta: dict = field(default_factory=dict)

    @property
    def power_ma(self) -> float:
        return float(sum(self.stage_currents_ma))

    @classmethod
    def from_summary(cls, d: dict, fc_hz: float, load: tuple[float, float] = DEFAULT_LOAD) -> "LNADesign":
        """Rebuild a design from ``summary()`` (operating points come from the active device provider)."""
        ops = [device_op(a["kind"], a["w_um"], a["vb_v"]) for a in d["active"]]

        def mcr(m):
            return MCRPhysical(k=m["k"], l1_h=m["l1_h"], l2_h=m["l2_h"], r1_ohm=float(m["r1_ohm"]),
                               r2_ohm=float(m["r2_ohm"]), c1_f=m["c1_f"], c2_f=m["c2_f"], q_ind=m.get("q_ind", Q_IND),
                               f_loss_hz=m.get("f_loss_hz", 30e9), flags=list(m.get("flags", [])))
        return cls(ops=ops, stage_currents_ma=[a["stage_current_ma"] for a in d["active"]], ls_h=d["ls_ph"] * 1e-12,
                   lg_h=d["lg_ph"] * 1e-12, lpar_h=d["lpar_ph"] * 1e-12, mcr1=mcr(d["mcr1"]), mcr2=mcr(d["mcr2"]),
                   mcr3=mcr(d["mcr3"]), fc_hz=fc_hz, load=load, meta=dict(d.get("meta") or {}))

    def summary(self) -> dict:
        return {
            "active": [{"kind": op.kind, "w_um": op.w_um, "vb_v": op.vgs_v,
                        "stage_current_ma": i} for op, i in zip(self.ops, self.stage_currents_ma)],
            "ls_ph": self.ls_h * 1e12, "lg_ph": self.lg_h * 1e12, "lpar_ph": self.lpar_h * 1e12,
            "mcr1": self.mcr1.to_dict(), "mcr2": self.mcr2.to_dict(), "mcr3": self.mcr3.to_dict(),
            "power_ma": self.power_ma, "meta": self.meta,
        }


# --------------------------------------------------------------------------
# primitive blocks
# --------------------------------------------------------------------------

def _lossy_l(s: np.ndarray, l_h: float, q: float, f_ref: float) -> np.ndarray:
    return s * l_h + 2 * math.pi * f_ref * l_h / q


def fet_cs(s: np.ndarray, op: DeviceOP, cgd_factor: float = 1.0, include_cdb: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Intrinsic common-source Y matrix and Y-form noise correlation.

    PDK-fitted devices may carry a transconductance delay, an NQS channel resistance and their own
    noise factors; for the surrogate these are zero/None and the equations are the classic ones."""
    n = s.size
    cgd = op.cgd_f * cgd_factor
    nqs = 1.0 / (1.0 + s * op.cgs_f * op.ri_ohm) if op.ri_ohm else np.ones(n)
    y = np.zeros((n, 2, 2), dtype=complex)
    y[:, 0, 0] = s * op.cgs_f * nqs + s * cgd
    y[:, 0, 1] = -s * cgd
    y[:, 1, 0] = op.gm_s * (np.exp(-s * op.tau_s) if op.tau_s else 1.0) * nqs - s * cgd
    y[:, 1, 1] = op.gds_s + s * (cgd + (op.cdb_f if include_cdb else 0.0))
    gamma = TECH.gamma if op.gamma is None else op.gamma
    dg = TECH.delta_over_gamma if op.dg is None else op.dg
    gd0 = op.gm_s / TECH.alpha
    sdd = gamma * gd0
    w = np.abs(s)
    sgg = dg * gamma * (w * op.cgs_f) ** 2 / (5 * gd0)
    cy = np.zeros_like(y)
    cy[:, 0, 0] = sgg
    cy[:, 1, 1] = sdd
    cy[:, 0, 1] = TECH.corr_c * np.sqrt(sgg * sdd)
    cy[:, 1, 0] = np.conj(cy[:, 0, 1])
    return y, cy


CASCODE_RATIO = 0.45


def cascode_device(op: DeviceOP) -> DeviceOP:
    """Common-gate device sized CASCODE_RATIO*W carrying the same current."""
    from .device import device_provider
    w = op.w_um * getattr(device_provider(), "cascode_ratio", CASCODE_RATIO)
    lo, hi = 0.2, 0.9
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if drain_current_ma(w, mid) < op.id_ma:
            lo = mid
        else:
            hi = mid
    return device_op("cascode", round(w, 3), round(0.5 * (lo + hi), 6))


def _measured_y3(mode: str, op: DeviceOP, s: np.ndarray):
    """(Y3 over the band, in-range mask) from the provider's 3-port table, or None (docs/123)."""
    from .device import device_provider
    tab = getattr(device_provider(), "y3", None)
    if tab is None or not tab.has(mode):
        return None
    y3, ok = tab.y3(mode, op.w_um, op.vgs_v, np.abs(s) / (2 * math.pi))
    return (y3, ok) if ok.any() else None


def _with_measured_y(model: tp.TwoPort, y: np.ndarray, ok: np.ndarray) -> tp.TwoPort:
    """Signal ABCD from the measured Y (where in range); input-referred noise (ABCD form) from the model."""
    meas = tp.from_y(y, np.zeros_like(y))
    abcd = np.where(ok[:, None, None], meas.abcd, model.abcd)
    return tp.TwoPort(abcd, model.ca.copy())


def stage1_cascode(s: np.ndarray, op: DeviceOP, ls_h: float, f_ref: float) -> tuple[tp.TwoPort, tp.TwoPort, tp.TwoPort]:
    """Returns (Rg series, degenerated CS, common-gate cascode).

    With a measured 3-port table on the provider (``pdk3.Y3Table``) the CS (source on Ls) and the CG (gate
    AC-grounded) are the Kron-reduced measured Y3 -- gate resistance included, so the Rg block becomes zero --
    while noise stays the fitted model's (docs/123)."""
    rg_cs, cs, cgp = _stage1_model(s, op, ls_h, f_ref)
    from .device import device_provider
    casc = getattr(device_provider(), "casc_noise", None)       # measured cell noise (docs/123 §11)
    if casc is not None:
        k_n = casc.k(op.w_um, op.vgs_v, np.abs(s) / (2 * math.pi))[:, None, None]
        rg_cs, cs, cgp = (tp.TwoPort(b.abcd, b.ca * k_n) for b in (rg_cs, cs, cgp))
    else:
        k_n = float(getattr(device_provider(), "noise1_scale", 1.0))   # Spectre-calibrated stage-1 noise (§8)
        if k_n != 1.0:
            rg_cs, cs, cgp = (tp.TwoPort(b.abcd, b.ca * k_n) for b in (rg_cs, cs, cgp))
    m_cs = _measured_y3("cs3", op, s)
    m_cg = _measured_y3("cg3", cascode_device(op), s)
    if m_cs is None and m_cg is None:
        return rg_cs, cs, cgp
    from . import pdk3
    zero = tp.series(np.zeros(s.size, dtype=complex))
    if m_cs is not None:
        y3, ok = m_cs
        zls = _lossy_l(s, ls_h, Q_MATCH, f_ref) if ls_h > 0 else None
        if zls is None:       # source grounded: just drop the source row/column
            y2 = y3[:, :2, :2]
        else:
            y2 = pdk3.kron(y3, keep=[0, 1], drop=2, y_drop_extra=1.0 / zls)
        k = ok[:, None, None]
        meas = _with_measured_y(rg_cs @ cs, y2, ok)       # Rg is inside the measured Y and the model noise
        cs = tp.TwoPort(np.where(k, meas.abcd, cs.abcd), np.where(k, meas.ca, cs.ca))
        rg_cs = tp.TwoPort(np.where(k, zero.abcd, rg_cs.abcd), np.where(k, zero.ca, rg_cs.ca))
    if m_cg is not None:
        y3, ok = m_cg
        y2 = y3[:, [2, 1]][:, :, [2, 1]]          # gate AC-grounded: ports (source, drain)
        cgp = _with_measured_y(cgp, y2, ok)
    return rg_cs, cs, cgp


def _stage1_model(s: np.ndarray, op: DeviceOP, ls_h: float, f_ref: float) -> tuple[tp.TwoPort, tp.TwoPort, tp.TwoPort]:
    from .device import device_provider
    physical_cdb = bool(getattr(device_provider(), "physical_cdb", False))   # PDK: Cdb is a drain-bulk junction
    cgb_frac = float(getattr(device_provider(), "cgb_frac", 0.0))     # part of the grounded-source Cgs that is Cgb
    op_cs = replace(op, cgs_f=op.cgs_f * (1.0 - cgb_frac)) if cgb_frac else op
    y, cy = fet_cs(s, op_cs, include_cdb=not physical_cdb)
    z = np.linalg.inv(y)
    cz = z @ cy @ np.conj(np.swapaxes(z, -1, -2))
    zls = _lossy_l(s, ls_h, Q_MATCH, f_ref) if ls_h > 0 else np.zeros_like(s)
    z = z + zls[:, None, None]
    cz = cz + np.maximum(zls.real, 0)[:, None, None] * np.ones((1, 2, 2))
    cs = tp.from_z(z, cz)
    if physical_cdb:
        cs = cs @ tp.shunt(s * op.cdb_f)
    if cgb_frac:
        cs = tp.shunt(s * op.cgs_f * cgb_frac) @ cs
    # common-gate device (CASCODE_RATIO x width, same current) -- port1 = source, port2 = drain
    cg = cascode_device(op)
    from .device import device_provider
    if cg.gamma is not None:   # PDK-fitted device: exact common-gate view of the full model (Rg, Ri, delay, noise)
        yf, cyf = fet_cs(s, cg, include_cdb=False)          # Cdb is drain-bulk (ground), not drain-source
        full = tp.series(np.full(s.size, cg.rg_ohm, dtype=complex)) @ tp.from_y(yf, cyf)
        ycg, cycg = tp.common_gate(*tp.to_y(full))
        ycg[:, 1, 1] += s * cg.cdb_f
        gmb = cg.gm_s * float(getattr(device_provider(), "gmb_ratio", 0.0))   # body effect: source above bulk
        ycg[:, 0, 0] += gmb
        ycg[:, 1, 0] -= gmb
        return tp.series(np.full(s.size, op.rg_ohm, dtype=complex)), cs, tp.from_y(ycg, cycg)
    gm, gds = cg.gm_s, cg.gds_s
    ycg = np.zeros((s.size, 2, 2), dtype=complex)
    ycg[:, 0, 0] = gm + gds + s * cg.cgs_f
    ycg[:, 0, 1] = -gds
    ycg[:, 1, 0] = -(gm + gds)
    ycg[:, 1, 1] = gds + s * (cg.cdb_f + cg.cgd_f)
    sdd = (TECH.gamma if cg.gamma is None else cg.gamma) * gm / TECH.alpha
    cycg = sdd * np.array([[1, -1], [-1, 1]], dtype=complex)[None].repeat(s.size, 0)
    cg = tp.from_y(ycg, cycg)
    return tp.series(np.full(s.size, op.rg_ohm, dtype=complex)), cs, cg


def _large_signal_table() -> bool:
    from .device import device_provider
    return bool(getattr(device_provider(), "large_signal_table", False))


def _cross_coupled() -> bool:
    from .device import device_provider
    return getattr(device_provider(), "neutralization", "residual") == "cross_coupled"


def neutral_cap_factor() -> float:
    """Gate/drain node capacitance of a neutralised stage in units of Cgd.

    ``residual`` (surrogate default): only the un-cancelled 12 % of Cgd is seen.  ``cross_coupled`` (PDK path,
    physical half circuit of the paper's pair): Cgd to the own drain plus CN = 0.88 Cgd to the opposite drain,
    i.e. 1.88 Cgd at both gate and drain, while the gate-drain coupling is still only 0.12 Cgd."""
    r = TECH.neutralization_residual
    return 2.0 - r if _cross_coupled() else r


def stage_diff(s: np.ndarray, op: DeviceOP) -> tuple[tp.TwoPort, tp.TwoPort]:
    """Neutralised differential stage (half circuit).

    With a measured grounded-source Y of the PDK cell on the provider (``cs2`` rows of ``pdk3.Y3Table``) the
    half circuit is that Y plus the two neutralisation capacitors CN = (1 - r) Cgd to the inverted opposite
    nodes, Y += s CN [[1, 1], [1, 1]] (exactly what the PDK netlist instantiates); Rg is inside the measured Y and
    the noise stays the fitted model's (docs/123 §7)."""
    y, cy = fet_cs(s, op, cgd_factor=TECH.neutralization_residual)
    if _cross_coupled():
        extra = s * op.cgd_f * (2.0 - 2.0 * TECH.neutralization_residual)   # CN + (1 - r) Cgd on each node
        y[:, 0, 0] += extra
        y[:, 1, 1] += extra
    rg, dev = tp.series(np.full(s.size, op.rg_ohm, dtype=complex)), tp.from_y(y, cy)
    m = _measured_y3("cs2", op, s) if _cross_coupled() else None
    if m is None:
        return rg, dev
    y2, ok = m
    y2 = y2 + (s * op.cgd_f * (1.0 - TECH.neutralization_residual))[:, None, None] * np.ones((1, 2, 2))
    k = ok[:, None, None]
    meas = _with_measured_y(rg @ dev, y2, ok)
    zero = tp.series(np.zeros(s.size, dtype=complex))
    return (tp.TwoPort(np.where(k, zero.abcd, rg.abcd), np.where(k, zero.ca, rg.ca)),
            tp.TwoPort(np.where(k, meas.abcd, dev.abcd), np.where(k, meas.ca, dev.ca)))


def mcr_block(s: np.ndarray, m: MCRPhysical) -> tp.TwoPort:
    wl = 2 * math.pi * m.f_loss_hz
    r1 = wl * m.l1_h / m.q_ind
    r2 = wl * m.l2_h / m.q_ind
    mm = m.k * math.sqrt(m.l1_h * m.l2_h)
    zl = np.empty((s.size, 2, 2), dtype=complex)
    zl[:, 0, 0] = s * m.l1_h + r1
    zl[:, 1, 1] = s * m.l2_h + r2
    zl[:, 0, 1] = s * mm
    zl[:, 1, 0] = s * mm
    y = np.linalg.inv(zl)
    g1 = 0.0 if not math.isfinite(m.r1_ohm) else 1.0 / m.r1_ohm
    g2 = 0.0 if not math.isfinite(m.r2_ohm) else 1.0 / m.r2_ohm
    y[:, 0, 0] += g1 + s * m.c1_f
    y[:, 1, 1] += g2 + s * m.c2_f
    return tp.passive_y(y)


# --------------------------------------------------------------------------
# Stage-3 variable (k, w0, Q0, C) -> physical mapping (binary search)
# --------------------------------------------------------------------------

def node_parasitics(op_drv: DeviceOP | None, op_next: DeviceOP | None, load: tuple[float, float] | None,
                    drv_is_cascode: bool = False) -> dict:
    cgd_f = neutral_cap_factor()
    c_pri = (op_drv.cdb_f + op_drv.cgd_f * (1.0 if drv_is_cascode else cgd_f)) if op_drv else 0.0
    g_pri = (op_drv.gds_s * (op_drv.gds_s / op_drv.gm_s) if drv_is_cascode else op_drv.gds_s) if op_drv else 0.0
    if op_next is not None:
        c_sec = op_next.cgs_f + op_next.cgd_f * cgd_f
        g_sec = 0.0
    elif load is not None:
        c_sec = load[1]
        g_sec = 1.0 / load[0]
    else:
        c_sec, g_sec = 0.0, 0.0
    return {"c_pri_f": c_pri, "g_pri_s": g_pri, "c_sec_f": c_sec, "g_sec_s": g_sec}


def map_mcr(k: float, w0: float, q0: float, c_f: float, par: dict,
            q_ind: float = Q_IND) -> MCRPhysical:
    """Map the abstract symmetric MCR (k, w0, Q0, C_total) onto added L/R/C.

    L is found by bisection so the loaded, lossy tank resonates at w0; C is the
    total node capacitance (paper range [C2, 200 fF]) so the added capacitor is
    C - C_parasitic.  An added resistor sets Q0 if the node is not already
    lossier than that; otherwise Q0 is flagged as unattainable.
    """
    flags: list[str] = []
    c_tot = c_f
    c_min = max(par["c_pri_f"], par["c_sec_f"])
    if c_tot < c_min:
        flags.append("c_below_parasitic")
        c_tot = c_min

    def w_res(l_h: float) -> float:
        r = w0 * l_h / q_ind
        val = 1.0 / (l_h * c_tot) - (r / l_h) ** 2
        return math.sqrt(val) if val > 0 else 0.0

    lo, hi = 1e-13, 1e-8
    for _ in range(80):  # w_res decreases with L
        mid = math.sqrt(lo * hi)
        if w_res(mid) > w0:
            lo = mid
        else:
            hi = mid
    l_h = math.sqrt(lo * hi)
    g_req = w0 * c_tot / q0
    g_ind = 1.0 / (q_ind * w0 * l_h)
    added = []
    for side in ("pri", "sec"):
        g_add = g_req - g_ind - par[f"g_{side}_s"]
        if g_add <= 0:
            flags.append(f"q0_unattainable_{side}")
            added.append(float("inf"))
        else:
            added.append(1.0 / g_add)
    return MCRPhysical(
        k=k, l1_h=l_h, l2_h=l_h, r1_ohm=added[0], r2_ohm=added[1],
        c1_f=max(c_tot - par["c_pri_f"], 0.0), c2_f=max(c_tot - par["c_sec_f"], 0.0),
        q_ind=q_ind, f_loss_hz=w0 / (2 * math.pi), flags=flags,
    )


# --------------------------------------------------------------------------
# simulation
# --------------------------------------------------------------------------

def _chain(design: LNADesign, s: np.ndarray, upto: str | None = None,
           include_match: bool = True) -> list[tuple[str, tp.TwoPort]]:
    f_ref = design.fc_hz
    op1, op2, op3 = design.ops
    blocks: list[tuple[str, tp.TwoPort]] = []
    if include_match:
        blocks.append(("lpar", tp.shunt(1.0 / _lossy_l(s, design.lpar_h, Q_MATCH, f_ref))))
        blocks.append(("lg", tp.series(_lossy_l(s, design.lg_h, Q_MATCH, f_ref))))
    rg1, cs1, cg1 = stage1_cascode(s, op1, design.ls_h, f_ref)
    blocks += [("rg1", rg1), ("dev1", cs1), ("cg1", cg1), ("mcr1", mcr_block(s, design.mcr1))]
    rg2, d2 = stage_diff(s, op2)
    blocks += [("rg2", rg2), ("dev2", d2)]
    if upto == "stage2":
        return blocks
    rg3, d3 = stage_diff(s, op3)
    blocks += [("mcr2", mcr_block(s, design.mcr2)), ("rg3", rg3), ("dev3", d3),
               ("mcr3", mcr_block(s, design.mcr3))]
    return blocks


def _load_z(s: np.ndarray, load: tuple[float, float]) -> np.ndarray:
    return 1.0 / (1.0 / load[0] + s * load[1])


def _node_voltages(blocks: list[tuple[str, tp.TwoPort]], idx: int, zl: complex) -> dict[str, complex]:
    """Voltages/currents at each block's input, normalised to Vs=1 (50-ohm source)."""
    vec = np.array([1.0, 1.0 / zl], dtype=complex)
    inputs: dict[str, np.ndarray] = {}
    for name, blk in reversed(blocks):
        vec = blk.abcd[idx] @ vec
        inputs[name] = vec.copy()
    vs = vec[0] + tp.Z0 * vec[1]
    return {name: v / vs for name, v in inputs.items()} | {"__load__": np.array([1.0, 1.0 / zl]) / vs}


def compression(design: LNADesign, blocks, idx: int, zl: complex, w: float) -> dict:
    nv = _node_voltages(blocks, idx, zl)
    names = [n for n, _ in blocks]

    def out_of(name: str) -> np.ndarray:
        i = names.index(name)
        return nv[names[i + 1]] if i + 1 < len(names) else nv["__load__"]

    limits = []
    op1, op2, op3 = design.ops
    # stage 1: gate-source voltage ~ gate current / (jw Cgs)
    ig = nv["dev1"][1]
    vgs1 = abs(ig / (w * op1.cgs_f))
    vd1 = abs(out_of("cg1")[0])
    swing1 = device_vdd() - 2 * op1.vdsat_v - 0.05
    limits.append(("stage1", op1, vgs1, vd1, swing1))
    for tag, op in (("stage2", op2), ("stage3", op3)):
        if f"dev{tag[-1]}" not in nv:
            continue
        vg = abs(nv[f"dev{tag[-1]}"][0])
        vd = abs(out_of(f"dev{tag[-1]}")[0])
        limits.append((tag, op, vg, vd, device_vdd() - op.vdsat_v))
    parts = {}
    inv2 = 0.0
    for tag, op, vg, vd, swing in limits:
        lim_g = op.a1db_v / max(vg, 1e-12)
        # hard clipping (current cut-off or supply rail) reduces the fundamental by 1 dB when the
        # linear drive amplitude is HARD_CLIP_1DB x the clip level: (2/pi)(asin x + x sqrt(1-x^2)) = 0.891
        lim_i = HARD_CLIP_1DB * op.id_ma * 1e-3 / max(op.gm_s * vg, 1e-15)
        lim_v = HARD_CLIP_1DB * swing / max(vd, 1e-12)
        if _large_signal_table():   # PDK: a1db_v is the measured 1-dB point of the DC transfer curve (cut-off
            lim_i = math.inf        # and gm saturation already included), so no separate current-clip rule
        vs_lim = min(lim_g, lim_i, lim_v)
        parts[tag] = {"vs_limit_v": vs_lim,
                      "mechanism": ["gm_compression", "current_clip", "voltage_swing"][
                          int(np.argmin([lim_g, lim_i, lim_v]))]}
        inv2 += 1.0 / vs_lim ** 2
    vs_1db = 1.0 / math.sqrt(inv2)
    p_w = vs_1db ** 2 / (8 * tp.Z0)
    from .device import device_provider
    off = float(getattr(device_provider(), "ip1db_offset_db", 0.0))  # PDK: calibrated against Spectre HB (docs/121)
    ip1db = 10 * math.log10(p_w / 1e-3) + off
    for tag in parts:
        parts[tag]["ip1db_dbm_if_alone"] = 10 * math.log10(parts[tag]["vs_limit_v"] ** 2 / (8 * tp.Z0) / 1e-3) + off
    return {"ip1db_dbm": ip1db, "stages": parts}


def simulate(design: LNADesign, f_hz: np.ndarray, *, upto: str | None = None,
             include_match: bool = True, nominal_load: tuple[float, float] | None = None) -> dict:
    """Small-signal + noise sweep (and 1-dB compression at fc) of the chain."""
    f_hz = np.asarray(f_hz, dtype=float)
    s = 2j * math.pi * f_hz
    blocks = _chain(design, s, upto=upto, include_match=include_match)
    total = reduce(lambda a, b: a @ b, (b for _, b in blocks))
    load = nominal_load if upto == "stage2" else design.load
    zl = _load_z(s, load)
    gain = total.voltage_gain(tp.Z0, zl)
    zin = total.zin(zl)
    out = {
        "f_hz": f_hz,
        "gain_db": tp.db20(gain),
        "s11_db": tp.s11_db(zin),
        "zin": zin,
        "nf_db": tp.db10(total.noise_factor(tp.Z0)),
        "nfmin_db": tp.db10(total.fmin()),
    }
    idx = int(np.argmin(np.abs(f_hz - design.fc_hz)))
    out["compression"] = compression(design, blocks, idx, complex(zl[idx]), 2 * math.pi * f_hz[idx])
    # gain up to the stage-2 gate (used by the multi-fidelity band planner)
    names = [n for n, _ in blocks]
    pre = reduce(lambda a, b: a @ b, (b for n, b in blocks[: names.index("rg2")]))
    rest = reduce(lambda a, b: a @ b, (b for n, b in blocks[names.index("rg2"):]))
    zin_rest = rest.zin(zl)
    out["gain_to_g2_db"] = tp.db20(pre.voltage_gain(tp.Z0, zin_rest))
    if "rg3" in names:
        pre3 = reduce(lambda a, b: a @ b, (b for n, b in blocks[: names.index("rg3")]))
        rest3 = reduce(lambda a, b: a @ b, (b for n, b in blocks[names.index("rg3"):]))
        out["gain_to_g3_db"] = tp.db20(pre3.voltage_gain(tp.Z0, rest3.zin(zl)))
        g = [out["gain_to_g2_db"][idx], out["gain_to_g3_db"][idx] - out["gain_to_g2_db"][idx],
             out["gain_db"][idx] - out["gain_to_g3_db"][idx]]
        out["stage_gain_db_at_fc"] = [float(x) for x in g]
    return out


def band_metrics(res: dict, fc_hz: float, fbw: float) -> dict:
    f = res["f_hz"]
    lo, hi = fc_hz * (1 - fbw / 2), fc_hz * (1 + fbw / 2)
    band = (f >= lo * (1 - 1e-9)) & (f <= hi * (1 + 1e-9))
    idx = int(np.argmin(np.abs(f - fc_hz)))
    g = res["gain_db"][band]
    return {
        "gain_fc_db": float(res["gain_db"][idx]),
        "gain_min_db": float(g.min()),
        "gain_max_db": float(g.max()),
        "ripple_db": float(g.max() - g.min()),
        "s11_fc_db": float(res["s11_db"][idx]),
        "s11_max_inband_db": float(res["s11_db"][band].max()),
        "nf_fc_db": float(res["nf_db"][idx]),
        "nfmin_fc_db": float(res["nfmin_db"][idx]),
        "nf_max_inband_db": float(res["nf_db"][band].max()),
        "ip1db_dbm": float(res["compression"]["ip1db_dbm"]),
    }


def sweep_grid(fc_hz: float, fbw: float, n_band: int = 21, span: float = 2.0) -> np.ndarray:
    """Frequency grid: dense in-band points + a coarse wide view."""
    lo, hi = fc_hz * (1 - fbw / 2), fc_hz * (1 + fbw / 2)
    band = np.linspace(lo, hi, n_band)
    wide = np.linspace(fc_hz / span, fc_hz * span, 41)
    return np.unique(np.concatenate([band, wide, [fc_hz]]))


__all__ = ["LNADesign", "MCRPhysical", "simulate", "band_metrics", "map_mcr", "node_parasitics",
           "sweep_grid", "Q_IND", "DEFAULT_LOAD", "K_B_T0"]
