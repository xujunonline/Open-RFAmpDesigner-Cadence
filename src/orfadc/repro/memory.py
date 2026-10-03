"""Knowledge Base (KB) and Experience Base (EB) -- paper Sec. II-C-2.

KB: factual design points (spec, power split, gain distribution, NF, IP1dB,
    full parameter dictionary) -> retrieved top-k as candidate priors.
EB: derived indicators (NF headroom that worked, first-stage gain/NF, per-
    stage IP1dB, the bottleneck) -> initialisation hints and pruning.

Both are append-only JSONL files so they survive across runs (self-evolution).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from ..schemas import Spec

KB_TEMPLATE = "power | gain | power_ratio_list | gain distribution | NF1 | NF | IP1_1 | IP1_2 | IP1_3 | IP1 | params_dict"
EB_TEMPLATE = ("x dB NF1 and y dB gain1 leads to z dB NF. The headroom should be a%. "
               "All stages are compressing, x, y, z of IP1_n and a, b, c of gain_n leads to IP1 of m dBm.")


def spec_vector(spec: Spec) -> list[float]:
    """Retrieval features.  Linearity enters output-referred (IP1dB + gain ~ OP1dB + 1),
    which is what the output stage must deliver; a 5 dB step counts as one unit."""
    return [math.log(spec.fc_ghz), spec.fbw_ratio, spec.power_ma / 30.0, spec.gain_db / 10.0,
            spec.nf_max_db / 2.5, (spec.ip1db_min_dbm + spec.gain_db) / 5.0]


def spec_distance(a: Spec | dict, b: Spec) -> float:
    va = spec_vector(a if isinstance(a, Spec) else Spec(**a))
    vb = spec_vector(b)
    w = [3.0, 2.0, 1.0, 1.0, 1.0, 1.0]
    return math.sqrt(sum(wi * (x - y) ** 2 for wi, x, y in zip(w, va, vb)))


@dataclass
class MemoryStore:
    root: Path

    @property
    def kb_path(self) -> Path:
        return self.root / "kb.jsonl"

    @property
    def eb_path(self) -> Path:
        return self.root / "eb.jsonl"

    def _append(self, path: Path, row: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _read(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # tolerate a torn last line
        return rows

    # ---- KB -------------------------------------------------------------
    def add_design(self, spec: Spec, record: dict) -> None:
        self._append(self.kb_path, {"spec": spec.__dict__, **record})

    def retrieve(self, spec: Spec, k: int = 3, passed_only: bool = True, max_distance: float = 0.8) -> list[dict]:
        """Top-k nearest design points; points farther than ``max_distance`` are not
        relevant priors (e.g. a -25 dBm IP1dB design for a -15 dBm task)."""
        rows = [r for r in self._read(self.kb_path) if (r.get("pass") or not passed_only)
                and spec_distance(r["spec"], spec) <= max_distance]
        rows.sort(key=lambda r: spec_distance(r["spec"], spec))
        return rows[:k]

    # ---- EB -------------------------------------------------------------
    def add_experience(self, spec: Spec, record: dict) -> None:
        self._append(self.eb_path, {"spec": spec.__dict__, **record})

    def insights(self, spec: Spec, k: int = 5, max_distance: float = 0.8) -> dict:
        rows = [r for r in self._read(self.eb_path) if spec_distance(r["spec"], spec) <= max_distance]
        if not rows:
            return {"n": 0}
        rows.sort(key=lambda r: spec_distance(r["spec"], spec))
        near = rows[:k]
        ok = [r for r in near if r.get("pass")]
        hint: dict = {"n": len(near), "n_pass": len(ok), "text": [r.get("text", "") for r in near[:3]]}
        if ok:
            hint["nf_headroom_db"] = max(r.get("nf_headroom_db", 0.2) for r in ok)
            hint["gain_cp_db"] = sorted(r.get("gain_cp_db", 20.0) for r in ok)[len(ok) // 2]
            hint["power_ratio_list"] = ok[0].get("power_ratio_list")
        bad = [r for r in near if not r.get("pass") and r.get("bottleneck")]
        if bad:
            hint["frequent_bottleneck"] = max({b["bottleneck"] for b in bad},
                                              key=lambda x: sum(1 for b in bad if b["bottleneck"] == x))
        return hint

    def n_records(self) -> tuple[int, int]:
        return len(self._read(self.kb_path)), len(self._read(self.eb_path))
