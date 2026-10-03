"""Cadence Spectre backend for the repro pipeline (same contract as SurrogateBackend).

v1 = "Spectre macromodel" backend.  Every block of ``circuit._chain`` is written as a
Spectre netlist of ideal elements:

* passives: lossy inductors (series R fixed at f_ref), ``mutual_inductor`` coupled
  resonators (MCR1-3), shunt R/C, 50-ohm input port, RL port + CL at the output;
* transistors: small-signal macromodels built from the same ``DeviceOP`` the Stage-1
  knowledge base uses (vccs gm, noiseless gds, Cgs/Cgd/Cdb, noisy Rg) with van der Ziel
  channel noise (gamma*gd0), induced gate noise (delta) and their 0.395j correlation
  realised with shorted noisy resistors + current mirrors + capacitor differentiators.

Spectre therefore solves the *same* circuit as the Python two-port engine, which makes
this backend an independent commercial-simulator cross-check of S21/S11/NF/NFmin and of
the internal node transfer functions (used for the compression estimate).  It is NOT a
PDK/transistor-level result: device nonlinearity and layout parasitics are out of scope
until PDK device cards replace the macromodels (``device_card`` hook, v2).

Runs go through ``orfadc.cadence.remote_runner.RemoteRunner`` (SSH/SCP, unique remote
run directory, timeouts).  Every simulation leaves netlist + raw PSF + metrics locally.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from ..cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace
from . import circuit as ck
from .device import TECH, DeviceOP
from .device import vdd as device_vdd

CGD_NEUTRAL = TECH.neutralization_residual
T_NOISE_C = 16.85  # 290 K, the IEEE noise-figure reference temperature
ROOT = Path(__file__).resolve().parents[3]


def _g(x: float) -> str:
    return f"{x:.12g}"


class _Net:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._n = 0

    def uid(self, p: str) -> str:
        self._n += 1
        return f"{p}{self._n}"

    def add(self, line: str) -> None:
        self.lines.append(line)

    # --- primitives -------------------------------------------------------------
    def lossy_l(self, a: str, b: str, l_h: float, q: float, f_ref: float) -> None:
        m = self.uid("xl")
        self.add(f"L{m} ({a} {m}) inductor l={_g(l_h)}")
        self.add(f"R{m} ({m} {b}) resistor r={_g(2 * math.pi * f_ref * l_h / q)}")

    def white_current(self, r_ohm: float) -> str:
        """Shorted noisy resistor; returns the name of the 0-V source carrying its noise current."""
        m = self.uid("wn")
        self.add(f"V{m} ({m} 0) vsource dc=0")
        self.add(f"R{m} ({m} 0) resistor r={_g(r_ohm)}")
        return f"V{m}"

    def differentiate(self, probe: str, c_f: float) -> str:
        """Current = s*c_f*i(probe) through the returned 0-V source."""
        a, b = self.uid("dx"), self.uid("dy")
        self.add(f"H{a} ({a} 0) ccvs probe={probe} rm=1")
        self.add(f"C{a} ({a} {b}) capacitor c={_g(c_f)}")
        self.add(f"V{b} ({b} 0) vsource dc=0")
        return f"V{b}"

    def mosfet(self, op: DeviceOP, g: str, s: str, d: str, cgd_factor: float = 1.0, gate_noise: bool = True,
               cdb_ref: str = "0") -> None:
        m = self.uid("m")
        gd0 = op.gm_s / TECH.alpha
        self.add(f"G{m} ({d} {s} {g} {s}) vccs gm={_g(op.gm_s)}")
        self.add(f"R{m}ds ({d} {s}) resistor r={_g(1.0 / op.gds_s)} isnoisy=no")
        self.add(f"C{m}gs ({g} {s}) capacitor c={_g(op.cgs_f)}")
        if cgd_factor > 0:
            self.add(f"C{m}gd ({g} {d}) capacitor c={_g(op.cgd_f * cgd_factor)}")
        self.add(f"C{m}db ({d} {cdb_ref}) capacitor c={_g(op.cdb_f)}")
        vd = self.white_current(1.0 / (TECH.gamma * gd0))           # 4kT*gamma*gd0
        self.add(f"F{m}d ({d} {s}) cccs probe={vd} gain=1")
        if gate_noise:
            delta = TECH.delta_over_gamma * TECH.gamma
            c = abs(TECH.corr_c)
            k_corr = c * op.cgs_f * math.sqrt(delta / (5 * TECH.gamma)) / gd0
            k_unc = op.cgs_f * math.sqrt(delta * (1 - c * c) / (5 * gd0))
            v1 = self.differentiate(vd, k_corr)                    # correlated part: s*K*i_d
            self.add(f"F{m}gc ({g} {s}) cccs probe={v1} gain=1")
            vw = self.white_current(1.0)                           # 4kT * 1 S
            v2 = self.differentiate(vw, k_unc)
            self.add(f"F{m}gu ({g} {s}) cccs probe={v2} gain=1")

    def mcr(self, m: ck.MCRPhysical, a: str, b: str) -> None:
        u = self.uid("k")
        wl = 2 * math.pi * m.f_loss_hz
        self.add(f"L{u}p ({a} {u}p) inductor l={_g(m.l1_h)}")
        self.add(f"R{u}p ({u}p 0) resistor r={_g(wl * m.l1_h / m.q_ind)}")
        self.add(f"L{u}s ({b} {u}s) inductor l={_g(m.l2_h)}")
        self.add(f"R{u}s ({u}s 0) resistor r={_g(wl * m.l2_h / m.q_ind)}")
        self.add(f"K{u} mutual_inductor coupling={_g(m.k)} ind1=L{u}p ind2=L{u}s")
        for node, r, c in ((a, m.r1_ohm, m.c1_f), (b, m.r2_ohm, m.c2_f)):
            if math.isfinite(r):
                self.add(f"R{u}{node} ({node} 0) resistor r={_g(r)}")
            if c > 0:
                self.add(f"C{u}{node} ({node} 0) capacitor c={_g(c)}")


SAVE_NODES = ("in", "g1i", "s1", "d1", "g2", "g2i", "d2", "g3", "g3i", "d3", "out")


def render_netlist(design: ck.LNADesign, f_hz: np.ndarray, *, upto: str | None = None,
                   include_match: bool = True, nominal_load: tuple[float, float] | None = None,
                   physical_cdb: bool = False) -> tuple[str, float]:
    """Spectre netlist for the chain; returns (text, output port resistance).

    ``physical_cdb=False`` (default) reproduces the engine topology exactly (stage-1 Cdb to the source node);
    ``True`` ties it to ground as a real drain-bulk junction would be."""
    n = _Net()
    f_ref = design.fc_hz
    op1, op2, op3 = design.ops
    n.add("// orfadc.repro Spectre macromodel netlist (auto-generated; not a PDK netlist)")
    n.add("simulator lang=spectre")
    n.add("global 0")
    n.add(f"opts options temp={T_NOISE_C} tnom={T_NOISE_C}")
    n.add("PORT1 (in 0) port r=50 num=1 mag=1")
    if include_match:
        n.lossy_l("in", "0", design.lpar_h, ck.Q_MATCH, f_ref)
        n.lossy_l("in", "g1", design.lg_h, ck.Q_MATCH, f_ref)
    else:
        n.add("RSHORT (in g1) resistor r=1e-6 isnoisy=no")
    n.add(f"RG1 (g1 g1i) resistor r={_g(op1.rg_ohm)}")
    # The engine (circuit.stage1_cascode) adds Ls to the common terminal of the intrinsic CS Y-matrix,
    # which places Cdb drain->source.  Mirror that here so Spectre checks the engine's equations exactly;
    # the physical drain->bulk(ground) placement shifts S2 gain by ~0.4 dB (docs/119 sec. 4, audit B11).
    n.mosfet(op1, "g1i", "s1", "cas", cdb_ref="0" if physical_cdb else "s1")
    if design.ls_h > 0:
        n.lossy_l("s1", "0", design.ls_h, ck.Q_MATCH, f_ref)
    else:
        n.add("RLS0 (s1 0) resistor r=1e-6 isnoisy=no")
    cg = ck.cascode_device(op1)
    n.add(f"GCG (d1 cas 0 cas) vccs gm={_g(cg.gm_s)}")
    n.add(f"RCGds (d1 cas) resistor r={_g(1.0 / cg.gds_s)} isnoisy=no")
    n.add(f"CCGgs (cas 0) capacitor c={_g(cg.cgs_f)}")
    n.add(f"CCGdb (d1 0) capacitor c={_g(cg.cdb_f + cg.cgd_f)}")
    vcg = n.white_current(1.0 / (TECH.gamma * cg.gm_s / TECH.alpha))
    n.add(f"FCG (d1 cas) cccs probe={vcg} gain=1")
    n.mcr(design.mcr1, "d1", "g2")
    n.add(f"RG2 (g2 g2i) resistor r={_g(op2.rg_ohm)}")
    n.mosfet(op2, "g2i", "0", "d2", cgd_factor=CGD_NEUTRAL)
    if upto == "stage2":
        rl, cl = nominal_load or (250.0, 0.0)
        out = "d2"
    else:
        n.mcr(design.mcr2, "d2", "g3")
        n.add(f"RG3 (g3 g3i) resistor r={_g(op3.rg_ohm)}")
        n.mosfet(op3, "g3i", "0", "d3", cgd_factor=CGD_NEUTRAL)
        n.mcr(design.mcr3, "d3", "out")
        rl, cl = design.load
        out = "out"
    n.add(f"PORT2 ({out} 0) port r={_g(rl)} num=2")
    if cl > 0:
        n.add(f"CLOAD ({out} 0) capacitor c={_g(cl)}")
    freqs = " ".join(_g(f) for f in np.asarray(f_hz, float))
    n.add(f"sp1 sp values=[{freqs}] ports=[PORT1 PORT2] donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport")
    present = [x for x in SAVE_NODES if x != "out" or out == "out"]
    present = [x for x in present if upto != "stage2" or x not in ("g3", "g3i", "d3")]
    n.add(f"ac1 ac values=[{freqs}]")
    n.add("save " + " ".join(present))
    return "\n".join(n.lines) + "\n", rl


# ---------------------------------------------------------------------------
# result parsing (pure, unit-testable)
# ---------------------------------------------------------------------------

def parse_results(run_dir: Path, design: ck.LNADesign, f_hz: np.ndarray, r_out: float,
                  upto: str | None) -> dict:
    sp_path, nz_path, ac_path = run_dir / "sp1.sp", run_dir / "sp1.noise.sp", run_dir / "ac1.ac"
    fs, s11 = parse_complex_trace(sp_path, "s11")
    _, s21 = parse_complex_trace(sp_path, "s21")
    _, nf = parse_scalar_trace(nz_path, "NF", require_each_sweep=True)
    _, nfmin = parse_scalar_trace(nz_path, "NFmin", require_each_sweep=True)
    fs = np.asarray(fs)
    if len(fs) != len(f_hz) or not np.allclose(fs, f_hz, rtol=1e-9):
        raise ValueError("Spectre frequency grid differs from the request")
    s11, s21 = np.asarray(s11), np.asarray(s21)
    zin = 50.0 * (1 + s11) / (1 - s11)
    gain = np.abs(s21) * math.sqrt(r_out / 50.0)          # power-wave S21 -> 2*Vload/Vs
    node = {}
    for name in SAVE_NODES:
        try:
            node[name] = np.asarray(parse_complex_trace(ac_path, name)[1])
        except ValueError:
            continue
    vs = node["in"] * (zin + 50.0) / zin                    # Thevenin source voltage of the AC run
    out = {
        "f_hz": np.asarray(f_hz, float), "gain_db": 20 * np.log10(np.maximum(gain, 1e-12)),
        "s11_db": 20 * np.log10(np.maximum(np.abs(s11), 1e-9)), "zin": zin,
        "nf_db": np.asarray(nf, float), "nfmin_db": np.asarray(nfmin, float),
        "gain_to_g2_db": 20 * np.log10(np.maximum(2 * np.abs(node["g2"] / vs), 1e-12)),
        "source": "cadence_spectre_macromodel",
    }
    if "g3" in node:
        out["gain_to_g3_db"] = 20 * np.log10(np.maximum(2 * np.abs(node["g3"] / vs), 1e-12))
    idx = int(np.argmin(np.abs(out["f_hz"] - design.fc_hz)))
    if "g3" in node:
        g = [out["gain_to_g2_db"][idx], out["gain_to_g3_db"][idx] - out["gain_to_g2_db"][idx],
             out["gain_db"][idx] - out["gain_to_g3_db"][idx]]
        out["stage_gain_db_at_fc"] = [float(x) for x in g]
    out["compression"] = _compression(design, {k: v[idx] / vs[idx] for k, v in node.items()})
    return out


def _compression(design: ck.LNADesign, v: dict[str, complex]) -> dict:
    """Same limit model as circuit.compression, fed with Spectre node voltages per 1 V source."""
    op1, op2, op3 = design.ops
    rows = [("stage1", op1, abs(v["g1i"] - v["s1"]), abs(v["d1"]), device_vdd() - 2 * op1.vdsat_v - 0.05)]
    rows.append(("stage2", op2, abs(v["g2i"]), abs(v["d2"]), device_vdd() - op2.vdsat_v))
    if "g3i" in v:
        rows.append(("stage3", op3, abs(v["g3i"]), abs(v["d3"]), device_vdd() - op3.vdsat_v))
    parts, inv2 = {}, 0.0
    for tag, op, vg, vd, swing in rows:
        lims = [op.a1db_v / max(vg, 1e-12),
                ck.HARD_CLIP_1DB * op.id_ma * 1e-3 / max(op.gm_s * vg, 1e-15),
                ck.HARD_CLIP_1DB * swing / max(vd, 1e-12)]
        vs_lim = min(lims)
        parts[tag] = {"vs_limit_v": vs_lim, "mechanism": ["gm_compression", "current_clip", "voltage_swing"][int(np.argmin(lims))],
                      "ip1db_dbm_if_alone": 10 * math.log10(vs_lim**2 / 400 / 1e-3)}
        inv2 += 1.0 / vs_lim**2
    vs1 = 1.0 / math.sqrt(inv2)
    return {"ip1db_dbm": 10 * math.log10(vs1**2 / 400 / 1e-3), "stages": parts,
            "note": "estimate from Spectre node transfer functions + device limits (macromodel is linear)"}


def _expand(out: dict, inv: np.ndarray, n_unique: int) -> dict:
    """Map per-frequency arrays from the unique grid back to the requested (possibly repeated) grid."""
    for k, v in list(out.items()):
        if isinstance(v, np.ndarray) and v.ndim == 1 and len(v) == n_unique:
            out[k] = v[inv]
    return out


# ---------------------------------------------------------------------------
# backend
# ---------------------------------------------------------------------------

@dataclass
class CadenceBackend:
    config_path: Path = ROOT / "config" / "remote_cadence.local.yaml"
    local_root: Path = ROOT / "results" / "runs" / "repro_cadence"
    name: str = "cadence_spectre_macromodel_v1"
    timeout_s: int = 300
    runner: Any = None
    run_id: str = field(default_factory=lambda: time.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6])
    n_calls: int = 0
    wall_s: float = 0.0
    physical_cdb: bool = False

    def __post_init__(self) -> None:
        if self.runner is None:
            from ..cadence.remote_runner import RemoteRunner, load_remote_config
            self.runner = RemoteRunner(load_remote_config(self.config_path))
        self.remote_root = str(PurePosixPath(self.runner.config.remote_root) / f"repro_{self.run_id}")
        mk = self.runner.ensure_remote_dir(self.remote_root)
        if not mk.ok:
            raise RuntimeError(f"cannot create remote run dir: {mk.stderr.strip()[:300]}")

    def probe(self) -> dict:
        return self.runner.probe(("spectre",))

    def simulate(self, design: ck.LNADesign, f_hz: np.ndarray, *, upto: str | None = None,
                 include_match: bool = True, nominal_load: tuple[float, float] | None = None) -> dict:
        t0 = time.perf_counter()
        self.n_calls += 1
        tag = f"sim{self.n_calls:05d}"
        local = self.local_root / self.run_id / tag
        local.mkdir(parents=True, exist_ok=False)
        f_req = np.asarray(f_hz, float)
        # Spectre de-duplicates and sorts a `values=[...]` sweep (band grids repeat the band edges),
        # so simulate the unique sorted grid and map the results back onto the requested points.
        # (keys use the netlist's 12-significant-digit formatting, so near-equal floats such as a band edge
        # computed twice collapse exactly as Spectre collapses them)
        f_u, inv = np.unique(np.array([float(_g(x)) for x in f_req]), return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
        text, r_out = render_netlist(design, f_u, upto=upto, include_match=include_match, nominal_load=nominal_load,
                                     physical_cdb=self.physical_cdb)
        (local / "netlist.scs").write_text(text, encoding="ascii")
        (local / "design.json").write_text(json.dumps(design.summary(), default=float, indent=1), encoding="utf-8")
        rdir = str(PurePosixPath(self.remote_root) / tag)
        steps = {}
        for name, res in (("mkdir", lambda: self.runner.ensure_remote_dir(rdir)),
                          ("upload", lambda: self.runner.upload(local / "netlist.scs", rdir + "/netlist.scs")),
                          ("spectre", lambda: self.runner.run_remote(
                              [self.runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
                               "+log", "spectre.log", "netlist.scs"], cwd=rdir, timeout_seconds=self.timeout_s))):
            r = res()
            steps[name] = {"rc": r.returncode, "stderr": r.stderr[-400:]}
            if not r.ok:
                self.runner.download(rdir + "/spectre.log", local / "spectre.log")
                (local / "metrics.json").write_text(json.dumps({"status": f"{name}_failed", "steps": steps}, indent=1))
                raise RuntimeError(f"Cadence {name} failed (rc={r.returncode}): {r.stderr.strip()[-300:]}")
        for f in ("spectre.log", "psf/sp1.sp", "psf/sp1.noise.sp", "psf/ac1.ac"):
            r = self.runner.download(f"{rdir}/{f}", local / PurePosixPath(f).name)
            steps["dl:" + f] = {"rc": r.returncode}
            if not r.ok:
                raise RuntimeError(f"Cadence download of {f} failed: {r.stderr.strip()[-300:]}")
        out = _expand(parse_results(local, design, f_u, r_out, upto), inv, len(f_u))
        out["f_hz"] = f_req
        dt = time.perf_counter() - t0
        self.wall_s += dt
        (local / "metrics.json").write_text(json.dumps({
            "status": "ok", "backend": self.name, "wall_s": dt, "upto": upto, "steps": steps,
            "gain_db": out["gain_db"].tolist(), "s11_db": out["s11_db"].tolist(), "nf_db": out["nf_db"].tolist(),
            "ip1db_dbm": out["compression"]["ip1db_dbm"], "not_lna_result": True,
            "note": "Spectre-solved macromodel (surrogate devices); not a PDK or silicon result"}, indent=1, default=float),
            encoding="utf-8")
        return out


class HybridBackend:
    """Surrogate for the inner Stage-2/3 loops, Cadence for Stage-4 full-chain evaluation
    (the paper's multi-fidelity split with Spectre as the highest fidelity)."""

    def __init__(self, inner, final) -> None:
        self.inner, self.final = inner, final
        self.name = f"hybrid({inner.name}->{final.name})"

    def simulate(self, design, f_hz, **kw):
        return self.inner.simulate(design, f_hz, **kw)
