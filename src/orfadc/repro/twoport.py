"""Vectorised two-port algebra with noise-correlation matrices.

Every block is an ``ABCD`` matrix plus an ABCD-form noise correlation matrix
``CA`` sampled on a common frequency grid (shape ``(N, 2, 2)``).  Noise is
normalised to ``4 k T0 df`` so that for a series resistor ``CA[0,0] = R``.
Cascading follows Hillbrand & Russer (1976):

    A = A1 @ A2,   CA = CA1 + A1 @ CA2 @ A1^H

This is the "high-fidelity" engine of the surrogate backend.  It is not a
SPICE simulator: it solves linear small-signal two-ports only.  Large-signal
compression is estimated separately in :mod:`orfadc.repro.circuit`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Z0 = 50.0


def _herm(m: np.ndarray) -> np.ndarray:
    return np.conj(np.swapaxes(m, -1, -2))


@dataclass
class TwoPort:
    abcd: np.ndarray  # (N,2,2) complex
    ca: np.ndarray    # (N,2,2) complex, ABCD-form noise correlation / (4kT0 df)

    def __matmul__(self, other: "TwoPort") -> "TwoPort":
        a = self.abcd @ other.abcd
        ca = self.ca + self.abcd @ other.ca @ _herm(self.abcd)
        return TwoPort(a, ca)

    # --- derived quantities -------------------------------------------------
    def zin(self, zl: np.ndarray | complex) -> np.ndarray:
        a, b, c, d = self.abcd[:, 0, 0], self.abcd[:, 0, 1], self.abcd[:, 1, 0], self.abcd[:, 1, 1]
        return (a * zl + b) / (c * zl + d)

    def voltage_gain(self, zs: complex, zl: np.ndarray | complex) -> np.ndarray:
        """2*Vload/Vs, i.e. |S21| when zs = zl = 50 ohm."""
        a, b, c, d = self.abcd[:, 0, 0], self.abcd[:, 0, 1], self.abcd[:, 1, 0], self.abcd[:, 1, 1]
        return 2.0 * zl / (a * zl + b + c * zs * zl + d * zs)

    def noise_factor(self, zs: complex = Z0) -> np.ndarray:
        c11, c12, c22 = self.ca[:, 0, 0].real, self.ca[:, 0, 1], self.ca[:, 1, 1].real
        num = c11 + 2.0 * np.real(c12 * np.conj(zs)) + c22 * abs(zs) ** 2
        return 1.0 + num / np.real(zs)

    def fmin(self) -> np.ndarray:
        c11, c12, c22 = self.ca[:, 0, 0].real, self.ca[:, 0, 1], self.ca[:, 1, 1].real
        rad = np.maximum(c11 * c22 - np.imag(c12) ** 2, 0.0)
        return 1.0 + 2.0 * (np.real(c12) + np.sqrt(rad))


# --- primitive blocks -------------------------------------------------------

def _eye(n: int) -> np.ndarray:
    m = np.zeros((n, 2, 2), dtype=complex)
    m[:, 0, 0] = 1.0
    m[:, 1, 1] = 1.0
    return m


def series(z: np.ndarray) -> TwoPort:
    z = np.asarray(z, dtype=complex)
    a = _eye(z.size)
    a[:, 0, 1] = z
    ca = np.zeros_like(a)
    ca[:, 0, 0] = np.maximum(z.real, 0.0)
    return TwoPort(a, ca)


def shunt(y: np.ndarray) -> TwoPort:
    y = np.asarray(y, dtype=complex)
    a = _eye(y.size)
    a[:, 1, 0] = y
    ca = np.zeros_like(a)
    ca[:, 1, 1] = np.maximum(y.real, 0.0)
    return TwoPort(a, ca)


def from_y(y: np.ndarray, cy: np.ndarray) -> TwoPort:
    """Build a two-port from its Y matrix and Y-form noise correlation."""
    y11, y12, y21, y22 = y[:, 0, 0], y[:, 0, 1], y[:, 1, 0], y[:, 1, 1]
    det = y11 * y22 - y12 * y21
    a = np.empty_like(y)
    a[:, 0, 0] = -y22 / y21
    a[:, 0, 1] = -1.0 / y21
    a[:, 1, 0] = -det / y21
    a[:, 1, 1] = -y11 / y21
    t = np.zeros_like(y)
    t[:, 0, 1] = a[:, 0, 1]
    t[:, 1, 0] = 1.0
    t[:, 1, 1] = a[:, 1, 1]
    return TwoPort(a, t @ cy @ _herm(t))


def from_z(z: np.ndarray, cz: np.ndarray) -> TwoPort:
    z11, z12, z21, z22 = z[:, 0, 0], z[:, 0, 1], z[:, 1, 0], z[:, 1, 1]
    det = z11 * z22 - z12 * z21
    a = np.empty_like(z)
    a[:, 0, 0] = z11 / z21
    a[:, 0, 1] = det / z21
    a[:, 1, 0] = 1.0 / z21
    a[:, 1, 1] = z22 / z21
    t = np.zeros_like(z)
    t[:, 0, 0] = 1.0
    t[:, 0, 1] = -a[:, 0, 0]
    t[:, 1, 1] = -a[:, 1, 0]
    return TwoPort(a, t @ cz @ _herm(t))


def passive_y(y: np.ndarray) -> TwoPort:
    """Reciprocal passive network: thermal noise C_Y = Re(Y) (normalised)."""
    cy = 0.5 * (y + _herm(y))
    return from_y(y, cy.astype(complex))


def coupled_resonator(s: np.ndarray, l1: float, l2: float, k: float,
                      g1: float, c1: float, g2: float, c2: float) -> TwoPort:
    """Magnetically coupled resonator (Fig. 4): shunt G/C at both sides of a
    transformer with self inductances l1, l2 and coupling k."""
    m = k * np.sqrt(l1 * l2)
    det = l1 * l2 - m * m
    y = np.empty((s.size, 2, 2), dtype=complex)
    y[:, 0, 0] = l2 / det / s + g1 + s * c1
    y[:, 1, 1] = l1 / det / s + g2 + s * c2
    y[:, 0, 1] = -m / det / s
    y[:, 1, 0] = -m / det / s
    return passive_y(y)


def s11_db(zin: np.ndarray, z0: float = Z0) -> np.ndarray:
    g = (zin - z0) / (zin + z0)
    return 20 * np.log10(np.maximum(np.abs(g), 1e-9))


def db20(x: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


def db10(x: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.maximum(x, 1e-15))


def to_y(t: TwoPort) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of :func:`from_y`: Y matrix and Y-form noise correlation of a two-port."""
    a = t.abcd
    A, B, C, D = a[:, 0, 0], a[:, 0, 1], a[:, 1, 0], a[:, 1, 1]
    y = np.empty_like(a)
    y[:, 0, 0] = D / B
    y[:, 0, 1] = (B * C - A * D) / B
    y[:, 1, 0] = -1.0 / B
    y[:, 1, 1] = A / B
    tm = np.zeros_like(a)
    tm[:, 0, 1] = B
    tm[:, 1, 0] = 1.0
    tm[:, 1, 1] = D
    ti = np.linalg.inv(tm)
    return y, ti @ t.ca @ _herm(ti)


def common_gate(y: np.ndarray, cy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Common-source two-port (gate, drain; source common) -> common-gate (source, drain; gate grounded)
    through the indefinite admittance matrix, noise included."""
    n = y.shape[0]
    y3 = np.zeros((n, 3, 3), dtype=complex)          # node order g, d, s
    y3[:, :2, :2] = y
    y3[:, :2, 2] = -y.sum(axis=2)
    y3[:, 2, :2] = -y.sum(axis=1)
    y3[:, 2, 2] = y.sum(axis=(1, 2))
    m = np.array([[1, 0], [0, 1], [-1, -1]], dtype=complex)
    c3 = m[None] @ cy @ m.conj().T[None]
    keep = [2, 1]                                     # port 1 = source, port 2 = drain
    return y3[:, keep][:, :, keep], c3[:, keep][:, :, keep]
