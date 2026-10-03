"""Vectorised paper Eq. (3): low-fidelity response of one gain stage + MCR.

Derivation check (symmetric coupled parallel-RLC tanks, R = Rs = R2,
L = R/(w0 Q), C = Q/(w0 R)): nodal analysis gives exactly the printed
numerator and Z21, but the Y11 denominator's last term is ``Rs*w0^3*Q*s`` --
the printed ``Rs*w0^3*Q`` (no ``s``) is dimensionally inconsistent.  The
``corrected`` variant (default) uses the derived form; ``printed`` is kept
for traceability.

Interpretation used here (the paper does not spell it out):
  * R (Rs = R2 in Y11/Z21) is the total tank resistance Q0/(w0*C);
  * in I11, Rs/Cs are the driver's output resistance/capacitance and gm is
    the transconductance characterised with a 50-ohm load (Sec. II-A);
  * V = I11*Z21/2 is the stage voltage gain (V per V at the gate).
"""
from __future__ import annotations

import numpy as np


def eq3_voltage(f_hz: np.ndarray, *, k: float, w0: float, q0: float, c_f: float,
                gm50_s: float, rs_drv_ohm: float, cs_drv_f: float, rref: float = 50.0,
                variant: str = "corrected", half: bool = True) -> dict:
    s = 2j * np.pi * np.asarray(f_hz, float)
    r = q0 / (w0 * c_f)
    one = 1 - k * k
    num = one * q0**2 * s**4 + 2 * one * q0 * w0 * s**3 + (one + 2 * q0**2) * w0**2 * s**2 \
        + 2 * q0 * w0**3 * s + q0**2 * w0**4
    last = r * w0**3 * q0 * (s if variant == "corrected" else 1.0)
    den = one * r * w0 * q0 * s**3 + one * r * w0**2 * s**2 + last
    y11 = num / den
    rl = 1.0 / np.real(y11)
    cl = np.imag(y11) / np.imag(s)
    z21 = k * q0 * w0**3 * r * s / num
    rs, cs = rs_drv_ohm, cs_drv_f
    i11 = gm50_s * (rref * rs * cs * s + rs + rref) / rs * rs * (rl * cl * s + 1) / (rs * rl * (cs + cl) * s + rs + rl)
    v = i11 * z21 / (2.0 if half else 1.0)
    return {"v": v, "gain_db": 20 * np.log10(np.maximum(np.abs(v), 1e-12)), "y11": y11, "z21": z21, "r_tank": r}
