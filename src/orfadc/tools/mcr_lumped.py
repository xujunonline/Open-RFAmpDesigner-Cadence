from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SymmetricParallelMCR:
    inductance_h: float
    capacitance_f: float
    resistance_ohm: float
    mutual_inductance_h: float
    coupling_k: float

    def __post_init__(self) -> None:
        values = vars(self)
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in values.values()):
            raise ValueError("lumped MCR parameters must be finite real numbers")
        if any(values[name] <= 0 for name in ("inductance_h", "capacitance_f", "resistance_ohm")):
            raise ValueError("lumped L, C and R must be positive")
        if not 0 <= self.coupling_k < 1:
            raise ValueError("coupling_k must be in [0, 1)")
        if not math.isclose(
            self.mutual_inductance_h, self.coupling_k * self.inductance_h,
            rel_tol=1e-12, abs_tol=0.0,
        ):
            raise ValueError("mutual inductance disagrees with coupling_k")


@dataclass(frozen=True)
class LumpedResponse:
    frequency_hz: float
    input_admittance_s: complex
    transfer_impedance_ohm: complex


def symmetric_parallel_mcr(
    omega0_rad_s: float, q0: float, capacitance_f: float, coupling_k: float
) -> SymmetricParallelMCR:
    """Map a project-chosen symmetric parallel RLC model, not the paper's private mapper."""
    for name, value in (
        ("omega0_rad_s", omega0_rad_s), ("q0", q0),
        ("capacitance_f", capacitance_f), ("coupling_k", coupling_k),
    ):
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite real number")
    if omega0_rad_s <= 0 or q0 <= 0 or capacitance_f <= 0:
        raise ValueError("omega0_rad_s, q0 and capacitance_f must be positive")
    if not 0 <= coupling_k < 1:
        raise ValueError("coupling_k must be in [0, 1)")
    inductance_h = 1 / (omega0_rad_s**2 * capacitance_f)
    resistance_ohm = q0 / (omega0_rad_s * capacitance_f)
    if not math.isfinite(inductance_h) or not math.isfinite(resistance_ohm):
        raise ValueError("MCR physical parameters overflowed")
    return SymmetricParallelMCR(
        inductance_h=inductance_h,
        capacitance_f=float(capacitance_f),
        resistance_ohm=resistance_ohm,
        mutual_inductance_h=coupling_k * inductance_h,
        coupling_k=float(coupling_k),
    )


def lumped_mcr_response(frequency_hz: float, model: SymmetricParallelMCR) -> LumpedResponse:
    """Solve the two-node Fig. 4-style circuit for a unit Norton current at port 1."""
    if type(frequency_hz) not in {int, float} or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("frequency_hz must be finite and positive")
    if not isinstance(model, SymmetricParallelMCR):
        raise TypeError("model must be SymmetricParallelMCR")
    s = 1j * 2 * math.pi * frequency_hz
    inductor_admittance = 1 / (s * model.inductance_h * (1 - model.coupling_k**2))
    diagonal = 1 / model.resistance_ohm + s * model.capacitance_f + inductor_admittance
    off_diagonal = -model.coupling_k * inductor_admittance
    determinant = diagonal**2 - off_diagonal**2
    if determinant == 0:
        raise ValueError("MCR nodal admittance is singular")
    input_admittance = determinant / diagonal
    transfer_impedance = -off_diagonal / determinant
    if any(not math.isfinite(part) for value in (input_admittance, transfer_impedance)
           for part in (value.real, value.imag)):
        raise ValueError("MCR nodal response is nonfinite")
    return LumpedResponse(float(frequency_hz), input_admittance, transfer_impedance)
