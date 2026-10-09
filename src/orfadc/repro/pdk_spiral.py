"""PDK spiral inductors for the input match (docs/133 §8, experiment D).

docs/126 found S7 limited by the ideal match inductors (constant Q = 25).  This module characterises the PDK's
scalable spiral model (default ``spiral_std_mu_z``: thick top metal, quarter-turn steps) over a geometry grid in ONE
Spectre run -- every spiral is driven by its own 1 A AC current source, so its node voltage is Z(f) -- and picks,
for a target inductance at fc, the realisable geometry with the highest Q.  The table holds PDK model behaviour and
stays in the git-ignored ``results/runs/pdk_spiral/``.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path, PurePosixPath

from . import pdk_v2 as P

MODEL = "spiral_std_mu_z"
LAY = 9
SPACING_UM = 2.0
GDIS_UM = 50.0
# documented valid range of spiral_std_mu_z: w 3-30 um, rad 15-90 um, turns 0.5-5.5 (1/4 steps); w > 20 um needs rad >= 20 um
GRID = {"nr": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0], "rad_um": [15, 20, 30, 45, 60, 90], "w_um": [6, 10, 15]}
FREQS = [10e9, 20e9, 25e9, 30e9, 35e9, 40e9, 50e9, 60e9]


def geometries(grid: dict | None = None) -> list[dict]:
    g = grid or GRID
    out = []
    for nr in g["nr"]:
        for rad in g["rad_um"]:
            for w in g["w_um"]:
                if w > 20 and rad < 20:
                    continue
                out.append({"nr": nr, "rad_um": rad, "w_um": w})
    return out


def instance(name: str, a: str, b: str, geo: dict, model: str = MODEL, lay: int = LAY) -> str:
    return (f"{name} ({a} {b} 0) {model} rad={geo['rad_um']:g}u w={geo['w_um']:g}u nr={geo['nr']:g} "
            f"spacing={SPACING_UM:g}u gdis={GDIS_UM:g}u lay={lay}")


def char_netlist(cfg: dict, geos: list[dict], freqs: list[float] = FREQS, model: str = MODEL, lay: int = LAY) -> str:
    lines = P._header(cfg) + [f"opts options temp={P.T_NOISE_C} tnom=27"]
    for i, g in enumerate(geos):
        lines.append(f"I{i} (0 n{i}) isource dc=0 mag=1")
        lines.append(instance(f"X{i}", f"n{i}", "0", g, model, lay))
    lines.append(f"ac1 ac values=[{' '.join(f'{f:.6g}' for f in freqs)}]")
    lines.append("save " + " ".join(f"n{i}" for i in range(len(geos))))
    return "\n".join(lines) + "\n"


def extract(local: Path, geos: list[dict]) -> list[dict]:
    from orfadc.cadence.psfascii_reader import parse_complex_trace
    ac = next(p for p in (local / "psf").iterdir() if p.name.endswith(".ac"))
    rows = []
    for i, g in enumerate(geos):
        fs, zs = parse_complex_trace(ac, f"n{i}")
        for f, z in zip(fs, zs):
            w = 2 * math.pi * f
            rows.append({**g, "f_hz": f, "l_ph": z.imag / w * 1e12, "r_ohm": z.real,
                         "q": z.imag / z.real if z.real > 0 else float("nan")})
    return rows


def characterize(runner, cfg: dict, out_root: Path | None = None, grid: dict | None = None,
                 model: str = MODEL, lay: int = LAY) -> dict:
    ts = time.strftime("%Y%m%dT%H%M%S")
    local = (out_root or P.ROOT / "results" / "runs" / "pdk_spiral") / ts
    geos = geometries(grid)
    rdir = str(PurePosixPath(runner.config.remote_root) / f"pdk_spiral_{ts}")
    st = P.run_spectre(runner, char_netlist(cfg, geos, FREQS, model, lay), rdir, local)
    rep = {"ts": ts, "model": model, "lay": lay, "spacing_um": SPACING_UM, "gdis_um": GDIS_UM, "geometries": len(geos),
           "freqs_hz": FREQS, "steps": st, "spectre_runs": 1, "rows": []}
    if st["ok"]:
        rep["rows"] = extract(local, geos)
    local.mkdir(parents=True, exist_ok=True)
    (local / "spiral_table.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    rep["local_dir"] = str(local)
    return rep


def latest_table(root: Path | None = None) -> dict | None:
    cands = sorted((root or P.ROOT / "results" / "runs" / "pdk_spiral").glob("*/spiral_table.json"))
    for p in reversed(cands):
        rep = json.loads(p.read_text(encoding="utf-8"))
        if rep.get("rows"):
            return rep
    return None


def pick(table: dict, l_h: float, f_hz: float, tol: float = 0.05) -> dict | None:
    """Geometry whose inductance at the table frequency nearest ``f_hz`` is within ``tol`` of ``l_h``
    (highest Q among those), or None when the target is outside what the grid realises (e.g. a few pH)."""
    freqs = sorted({r["f_hz"] for r in table["rows"]})
    f0 = min(freqs, key=lambda f: abs(f - f_hz))
    target = l_h * 1e12
    ok = [r for r in table["rows"] if r["f_hz"] == f0 and r["l_ph"] > 0 and math.isfinite(r["q"])
          and abs(r["l_ph"] - target) <= tol * target]
    if not ok:
        return None
    best = max(ok, key=lambda r: r["q"])
    return {"nr": best["nr"], "rad_um": best["rad_um"], "w_um": best["w_um"], "l_ph": best["l_ph"], "q": best["q"],
            "f_hz": f0, "target_ph": target}


def q_summary(table: dict, f_hz: float, l_lo_ph: float, l_hi_ph: float) -> dict:
    """Best achievable Q per inductance bin around f_hz (for setting the engine's ORFADC_Q_MATCH)."""
    freqs = sorted({r["f_hz"] for r in table["rows"]})
    f0 = min(freqs, key=lambda f: abs(f - f_hz))
    rows = [r for r in table["rows"] if r["f_hz"] == f0 and l_lo_ph <= r["l_ph"] <= l_hi_ph and math.isfinite(r["q"])]
    qs = sorted(r["q"] for r in rows)
    return {"f_hz": f0, "n": len(rows), "q_max": qs[-1] if qs else None,
            "q_median": qs[len(qs) // 2] if qs else None}
