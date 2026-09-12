from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Spec:
    id: str
    fc_ghz: float
    fbw_ratio: float
    power_ma: float
    gain_db: float
    nf_max_db: float
    ip1db_min_dbm: float

    @property
    def band_edges_ghz(self) -> tuple[float, float]:
        half = self.fc_ghz * self.fbw_ratio / 2.0
        return self.fc_ghz - half, self.fc_ghz + half


@dataclass
class SimResult:
    s11_db: float | None = None
    s21_db: float | None = None
    s22_db: float | None = None
    nf_db: float | None = None
    nfmin_db: float | None = None
    ip1db_dbm: float | None = None
    op1db_dbm: float | None = None
    power_ma: float | None = None
    ripple_db: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    candidate_id: str
    spec_id: str
    seed: int
    power_ratio_list: list[float]
    active_params: dict[str, Any] = field(default_factory=dict)
    passive_params: dict[str, Any] = field(default_factory=dict)
    sim_result: SimResult | None = None
    status: str = "created"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunConfig:
    work_root: Path
    ocean_bin: str = "ocean"
    spectre_bin: str = "spectre"
    dry_run: bool = True
    timeout_seconds: int = 3600

