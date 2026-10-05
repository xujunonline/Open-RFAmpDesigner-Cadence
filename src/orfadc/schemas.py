from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Spec:
    id: str
    fc_ghz: float
    fbw_ratio: float
    power_ma: float
    gain_db: float
    nf_max_db: float
    ip1db_min_dbm: float

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("spec id must not be empty")
        for name in ("fc_ghz", "fbw_ratio", "power_ma", "gain_db", "nf_max_db", "ip1db_min_dbm"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.fc_ghz <= 0 or not 0 < self.fbw_ratio < 2 or self.power_ma <= 0:
            raise ValueError("spec frequency, fractional bandwidth, and current budget must be positive")

    @property
    def band_edges_ghz(self) -> tuple[float, float]:
        half = self.fc_ghz * self.fbw_ratio / 2.0
        return self.fc_ghz - half, self.fc_ghz + half
