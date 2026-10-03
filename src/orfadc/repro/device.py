"""Surrogate 65-nm-class NMOS model and the Stage-1 knowledge database.

The paper characterises TSMC N65 cascode / neutralised differential cells
with OCEAN sweeps (Sec. II-A).  That data is proprietary, so this module
provides an *open, clearly labelled surrogate*: an EKV-style drain-current
equation with short-channel output conductance and per-micron parasitics.
Numbers are representative of a generic 65 nm RF NMOS, not of any PDK.

Grid (paper Sec. II-A): cascode W 45..180 um step 9, differential CS W
45..117 um step 9, gate bias 300..500 mV step 25 mV.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np

UT = 0.02585  # thermal voltage at 300 K
K_B_T0 = 1.380649e-23 * 290.0


@dataclass(frozen=True)
class TechParams:
    vth: float = 0.32
    n_slope: float = 1.3
    i0_ma_per_um: float = 0.021   # specific current scale
    theta: float = 1.6            # mobility/velocity-saturation degradation (1/V)
    lambda_clm: float = 0.45      # 1/V, short-channel output conductance
    cgs_ff_per_um: float = 1.05
    cgd_ff_per_um: float = 0.38
    cdb_ff_per_um: float = 0.55
    rg_ohm_um: float = 90.0      # effective gate+source resistance x width
    gamma: float = 1.1
    alpha: float = 0.8
    delta_over_gamma: float = 2.0
    corr_c: complex = 0.395j
    vdd: float = 1.2
    neutralization_residual: float = 0.12


TECH = TechParams()


def drain_current_ma(w_um: float | np.ndarray, vgs: float | np.ndarray, tech: TechParams = TECH) -> np.ndarray:
    if _PROVIDER is not None:
        return np.asarray(_PROVIDER.id_ma(w_um, vgs))
    x = (np.asarray(vgs) - tech.vth) / (2 * tech.n_slope * UT)
    f = np.logaddexp(0.0, x) ** 2
    vov = np.maximum(np.asarray(vgs) - tech.vth, 0.0)
    return np.asarray(w_um) * tech.i0_ma_per_um * f / (1.0 + tech.theta * vov)


@dataclass(frozen=True)
class DeviceOP:
    """Small-signal operating point of one transistor (half circuit)."""
    kind: str          # "cascode" | "diff"
    w_um: float
    vgs_v: float
    id_ma: float
    gm_s: float
    gds_s: float
    cgs_f: float
    cgd_f: float
    cdb_f: float
    rg_ohm: float
    a1db_v: float      # gate-voltage amplitude at 1 dB gm compression
    vdsat_v: float
    # optional PDK-fitted extras (docs/121 B16); defaults reproduce the surrogate equations exactly
    tau_s: float = 0.0          # transconductance delay
    ri_ohm: float = 0.0         # channel (NQS) resistance in series with Cgs
    gamma: float | None = None  # drain-noise factor (None -> TECH.gamma)
    dg: float | None = None     # delta/gamma (None -> TECH.delta_over_gamma)

    @property
    def ft_ghz(self) -> float:
        return self.gm_s / (2 * math.pi * (self.cgs_f + self.cgd_f)) / 1e9

    @property
    def gm_over_id(self) -> float:
        return self.gm_s / (self.id_ma * 1e-3)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ft_ghz"] = self.ft_ghz
        return d


# ---------------------------------------------------------------------------
# Optional device provider (docs/120 V2-3): a PDK-characterised table replaces the EKV surrogate
# everywhere the engine asks for an operating point, a drain current, the bias grid or VDD.
# ---------------------------------------------------------------------------
_PROVIDER = None


def set_device_provider(provider) -> None:
    """``provider`` needs ``op(kind, w_um, vgs_v) -> DeviceOP``, ``id_ma(w_um, vgs)``, ``vb_grid`` and ``vdd``;
    ``None`` restores the surrogate."""
    global _PROVIDER
    _PROVIDER = provider
    knowledge_database.cache_clear()
    _surrogate_device_op.cache_clear()


def device_provider():
    return _PROVIDER


def vdd() -> float:
    return float(_PROVIDER.vdd) if _PROVIDER is not None else TECH.vdd


def device_source() -> str:
    return getattr(_PROVIDER, "name", "pdk_table") if _PROVIDER is not None else "surrogate_ekv_65nm_class"


def device_op(kind: str, w_um: float, vgs_v: float, tech: TechParams = TECH) -> DeviceOP:
    if _PROVIDER is not None:
        return _PROVIDER.op(kind, float(w_um), float(vgs_v))
    return _surrogate_device_op(kind, w_um, vgs_v, tech)


@lru_cache(maxsize=4096)
def _surrogate_device_op(kind: str, w_um: float, vgs_v: float, tech: TechParams = TECH) -> DeviceOP:
    h = 2e-3
    v = vgs_v + h * np.arange(-2, 3)
    i = drain_current_ma(w_um, v, tech) * 1e-3  # A
    id_a = float(i[2])
    g1 = float((i[3] - i[1]) / (2 * h))
    g3 = float((i[4] - 2 * i[3] + 2 * i[1] - i[0]) / (2 * h**3)) / 6.0
    a_iip3 = math.sqrt(4.0 / 3.0 * abs(g1 / g3)) if abs(g3) > 1e-12 else 1.0
    a1db = min(0.33 * a_iip3, 0.35)
    vov = max(vgs_v - tech.vth, 0.0)
    vdsat = max(2 * tech.n_slope * UT, vov)
    return DeviceOP(
        kind=kind, w_um=float(w_um), vgs_v=float(vgs_v), id_ma=id_a * 1e3,
        gm_s=g1, gds_s=tech.lambda_clm * id_a,
        cgs_f=tech.cgs_ff_per_um * w_um * 1e-15,
        cgd_f=tech.cgd_ff_per_um * w_um * 1e-15,
        cdb_f=tech.cdb_ff_per_um * w_um * 1e-15,
        rg_ohm=tech.rg_ohm_um / w_um,
        a1db_v=a1db, vdsat_v=vdsat,
    )


def cascode_widths() -> list[float]:
    return [float(w) for w in range(45, 181, 9)]


def diff_widths() -> list[float]:
    return [float(w) for w in range(45, 118, 9)]


def bias_grid() -> list[float]:
    if _PROVIDER is not None:
        return [float(v) for v in _PROVIDER.vb_grid]
    return [round(0.300 + 0.025 * i, 3) for i in range(9)]


@lru_cache(maxsize=1)
def knowledge_database() -> tuple[dict, ...]:
    """Power-performance lookup table (the yellow block of Fig. 2)."""
    rows = []
    for kind, widths in (("cascode", cascode_widths()), ("diff", diff_widths())):
        for w in widths:
            for vb in bias_grid():
                op = device_op(kind, w, vb)
                # diff pair: table stores the *pair* current (two halves)
                stage_current = op.id_ma * (2.0 if kind == "diff" else 1.0)
                rows.append({
                    "kind": kind, "w_um": w, "vb_v": vb, "stage_current_ma": stage_current,
                    "gm_s": op.gm_s, "gds_s": op.gds_s, "ft_ghz": op.ft_ghz,
                    "cgs_ff": op.cgs_f * 1e15, "cdb_ff": op.cdb_f * 1e15,
                    "source": device_source(),
                })
    return tuple(rows)


def op_for_row(row: dict) -> DeviceOP:
    return device_op(row["kind"], row["w_um"], row["vb_v"])
