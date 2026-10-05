"""Cadence v2 helpers (docs/120): read-only PDK inventory (V2-0).

The inventory runs ``pdk_inventory.sh`` on the Cadence host through ``RemoteRunner`` (upload + one ssh call,
nothing outside the tool's own work root is written) and keeps the raw listing under the git-ignored
``results/runs/pdk_inventory/<ts>/``.  Paths found on the VM are the user's own; they are summarised for
choosing a device model, and are only ever written to the git-ignored ``config/model_paths.local.yaml``.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_name("pdk_inventory.sh")
NMOS_HINT = re.compile(r"(^|[_.])(n|nch|nmos|nfet|nmos\w*|nch\w*|n\d\w*|nfet\w*|nmosrf\w*)($|[_.])", re.I)


def parse_inventory(text: str) -> dict:
    """Group the ``##TAG<TAB>value`` lines of pdk_inventory.sh."""
    out: dict = defaultdict(list)
    for line in text.splitlines():
        if not line.startswith("##") or "\t" not in line:
            continue
        tag, val = line[2:].split("\t", 1)
        out[tag].append(val.strip())
    files: dict[str, dict] = {}
    for v in out.get("MODELFILE", []):
        path, _, size = v.rpartition("|")
        files[path] = {"bytes": int(size or 0), "sections": [], "models": []}
    for tag, key in (("SECTION", "sections"), ("MODEL", "models")):
        for v in out.get(tag, []):
            path, _, line = v.partition("|")
            tok = line.split()
            if len(tok) >= 2:
                name = tok[2] if tok[0].lower() == "inline" and len(tok) > 2 else tok[1]
                files.setdefault(path, {"bytes": 0, "sections": [], "models": []})[key].append(
                    {"name": name, "kind": " ".join(tok)[:100]})
    nmos = []
    for path, f in files.items():
        for m in f["models"]:
            low = m["kind"].lower()
            if NMOS_HINT.search(m["name"]) or re.search(r"type\s*=\s*n\b", low) or "nmos" in low:
                nmos.append({"file": path, "model": m["name"], "kind": m["kind"], "sections": [s["name"] for s in f["sections"]]})
    return {
        "user": (out.get("USER") or [""])[0], "spectre": (out.get("SPECTRE") or [""])[0],
        "spectre_version": (out.get("SPECTRE_VERSION") or [""])[0], "env": out.get("ENV", []),
        "cds_libs": out.get("CDSLIB", []), "cds_lib_lines": out.get("CDSLIB_LINE", []),
        "pdk_dirs": out.get("PDKDIR", []), "model_files": files, "nmos_candidates": nmos,
        "netlist_lines": out.get("NETLIST_LINE", []), "lib_dirs": out.get("LIBDIR", []),
        "lib_dirs_missing": out.get("LIBDIR_MISSING", []), "pdk_tree": out.get("PDKTREE", []),
        "pdk_models": out.get("PDKMODEL", []),
        "complete": bool(out.get("DONE")),
    }


def run_inventory(runner, out_root: Path | None = None, timeout_s: int = 290) -> dict:
    ts = time.strftime("%Y%m%dT%H%M%S")
    local = (out_root or ROOT / "results" / "runs" / "pdk_inventory") / ts
    local.mkdir(parents=True, exist_ok=True)
    rdir = str(PurePosixPath(runner.config.remote_root) / f"pdk_inventory_{ts}")
    steps = {"mkdir": runner.ensure_remote_dir(rdir).returncode,
             "upload": runner.upload(SCRIPT, rdir + "/pdk_inventory.sh").returncode}
    res = runner.run_shell("bash pdk_inventory.sh", cwd=rdir, timeout_seconds=timeout_s)
    steps["run"] = res.returncode
    (local / "raw.txt").write_text(res.stdout, encoding="utf-8")
    (local / "stderr.txt").write_text(res.stderr[-20000:], encoding="utf-8")
    inv = parse_inventory(res.stdout)
    inv["steps"], inv["local_dir"] = steps, str(local)
    (local / "inventory.json").write_text(json.dumps(inv, indent=1), encoding="utf-8")
    return inv


def summarize(inv: dict, max_rows: int = 40) -> str:
    lines = [f"spectre: {inv['spectre']}  ({inv['spectre_version']})", f"complete: {inv['complete']}  steps: {inv.get('steps')}",
             f"cds.lib files: {len(inv['cds_libs'])}; DEFINE lines: {len(inv['cds_lib_lines'])}",
             f"PDK-like dirs: {len(inv['pdk_dirs'])}"]
    lines += [f"  {d}" for d in inv["pdk_dirs"][:max_rows]]
    lines.append(f"model files: {len(inv['model_files'])}")
    for p, f in list(inv["model_files"].items())[:max_rows]:
        lines.append(f"  {p}  ({f['bytes']} B; sections={[s['name'] for s in f['sections']][:8]}; models={len(f['models'])})")
    lines.append(f"nmos candidates: {len(inv['nmos_candidates'])}")
    lines += [f"  {c['model']:24s} {c['kind'][:60]:60s} {c['file']}" for c in inv["nmos_candidates"][:max_rows]]
    lines += [f"  cds.lib: {x}" for x in sorted(set(l.split("|", 1)[-1] for l in inv["cds_lib_lines"]))[:max_rows]]
    lines.append(f"external libs: {inv.get('lib_dirs')}  missing: {inv.get('lib_dirs_missing')}")
    lines += [f"  tree: {x}" for x in inv.get("pdk_tree", [])[:60]]
    lines += [f"  pdk model file: {x}" for x in inv.get("pdk_models", [])[:60]]
    lines += [f"  netlist: {x}" for x in inv.get("netlist_lines", [])[:80]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# V2-2: PDK device characterisation (black-box: DC sweep + 2-port S/noise per bias)
# ---------------------------------------------------------------------------
import math  # noqa: E402
import tarfile  # noqa: E402

import numpy as np  # noqa: E402

from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace  # noqa: E402

LOCAL_CFG = ROOT / "config" / "model_paths.local.yaml"
F_LO, F_HI = 5e9, 30e9


def load_pdk_config(path: Path = LOCAL_CFG) -> dict:
    """``pdk:`` block of the git-ignored local config (include file, section, RF nmos cell, lr, wr, vdd)."""
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pdk = data.get("pdk") or {}
    need = ("toplevel", "section", "nmos", "lr", "wr_um", "vdd")
    missing = [k for k in need if pdk.get(k) in (None, "")]
    if missing:
        raise ValueError(f"{path.name}: pdk.{missing} not set")
    return pdk


def layout_for(w_um: float, wr_um: float, nr_choices: list[int]) -> dict:
    """Pick (nr, multi) so that wr*nr*multi is closest to the requested width (ties -> fewer multipliers)."""
    best = None
    for nr in nr_choices:
        for multi in range(1, 33):
            w = wr_um * nr * multi
            key = (abs(w - w_um), multi)
            if best is None or key < best[0]:
                best = (key, {"nr": nr, "multi": multi, "w_um": round(w, 6)})
    return best[1]


def _header(cfg: dict) -> list[str]:
    return ["// orfadc.repro v2 PDK characterisation (auto-generated)", "simulator lang=spectre", "global 0",
            f'include "{cfg["toplevel"]}" section={cfg["section"]}']


def _inst(cfg: dict, name: str, d: str, g: str, s: str, b: str, lay: dict) -> str:
    return (f"{name} ({d} {g} {s} {b}) {cfg['nmos']} lr={cfg['lr']} wr={cfg['wr_um']}u "
            f"nr={lay['nr']} multi={lay['multi']}")


def validation_netlist(cfg: dict, lay: dict) -> str:
    lines = _header(cfg) + [f"parameters vb=0.45 vdd={cfg['vdd']}",
                            "VG (g 0) vsource dc=vb", "VD (d 0) vsource dc=vdd",
                            _inst(cfg, "M1", "d", "g", "0", "0", lay), "op1 dc", "save VD:p"]
    return "\n".join(lines) + "\n"


def char_netlist(cfg: dict, lay: dict, vbs: list[float], vds: float | None = None,
                 freqs: list[float] | None = None) -> str:
    vals = " ".join(f"{v:.4g}" for v in vbs)
    lines = _header(cfg) + [
        f"parameters vb={vbs[0]:.4g} vdd={vds if vds is not None else cfg['vdd']}",
        "VG (vg 0) vsource dc=vb", "VD (vd 0) vsource dc=vdd",
        "LBG (vg g) inductor l=1", "LBD (vd d) inductor l=1",           # ideal bias tees
        "CBG (p1 g) capacitor c=1", "CBD (p2 d) capacitor c=1",
        "P1 (p1 0) port r=50 num=1", "P2 (p2 0) port r=50 num=2",
        _inst(cfg, "M1", "d", "g", "0", "0", lay),
        "dcsw dc param=vb start=0.15 stop=1.0 step=0.005",
        f"swp sweep param=vb values=[{vals}] {{",
        f"  sp1 sp values=[{' '.join(f'{f:.6g}' for f in sorted(set((freqs or []) + [F_LO, F_HI])))}] ports=[P1 P2] "
        "donoise=yes oprobe=P2 iprobe=P1",
        "}", "save VD:p"]
    return "\n".join(lines) + "\n"


def run_spectre(runner, text: str, rdir: str, local: Path, timeout_s: int = 290) -> dict:
    """Upload netlist, run Spectre (psfascii), fetch spectre.log + psf/ as one tarball."""
    local.mkdir(parents=True, exist_ok=True)
    (local / "netlist.scs").write_text(text, encoding="ascii")
    steps = {"mkdir": runner.ensure_remote_dir(rdir).returncode,
             "upload": runner.upload(local / "netlist.scs", rdir + "/netlist.scs").returncode}
    sp = runner.run_shell(f"{runner.config.spectre_bin} -64 +escchars -format psfascii -raw psf +log spectre.log netlist.scs"
                          " > /dev/null 2>&1; rc=$?; tar czf out.tgz spectre.log psf 2>/dev/null; exit $rc",
                          cwd=rdir, timeout_seconds=timeout_s)
    steps["spectre"] = sp.returncode
    dl = runner.download(rdir + "/out.tgz", local / "out.tgz")
    steps["download"] = dl.returncode
    if dl.ok:
        with tarfile.open(local / "out.tgz") as tf:
            tf.extractall(local, filter="data")
    log = (local / "spectre.log").read_text(errors="replace") if (local / "spectre.log").exists() else ""
    m = re.search(r"spectre completes with (\d+) errors?, (\d+) warnings?", log)
    steps["errors"], steps["warnings"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    steps["ok"] = sp.ok and dl.ok and m is not None and steps["errors"] == 0
    return steps


def s_to_y(s: np.ndarray, z0: float = 50.0) -> np.ndarray:
    eye = np.eye(2)
    return (eye - s) @ np.linalg.inv(eye + s) / z0


def _sp_files(psf: Path) -> list[Path]:
    files = [p for p in psf.iterdir() if p.name.endswith("sp1.sp") and "noise" not in p.name]
    return sorted(files, key=lambda p: [int(x) for x in re.findall(r"-(\d+)_", p.name)] or [0])


def extract_rows(local: Path, lay: dict, vbs: list[float], vdd: float) -> list[dict]:
    psf = local / "psf"
    vg, idp = parse_scalar_trace(psf / "dcsw.dc", "VD:p", sweep_variable="vb")
    vg, i_d = np.asarray(vg), -np.asarray(idp)                     # current into VD:p is -Id
    rows = []
    sps = _sp_files(psf)
    if len(sps) != len(vbs):
        raise ValueError(f"expected {len(vbs)} sp results, found {len(sps)}")
    for vb, spf in zip(vbs, sps):
        fs, s11 = parse_complex_trace(spf, "s11")
        s12, s21, s22 = (parse_complex_trace(spf, k)[1] for k in ("s12", "s21", "s22"))
        nz = spf.with_name(spf.name.replace("sp1.sp", "sp1.noise.sp"))
        nfmin = parse_scalar_trace(nz, "NFmin", require_each_sweep=True)[1]
        y = [s_to_y(np.array([[s11[k], s12[k]], [s21[k], s22[k]]])) for k in range(len(fs))]
        lo, hi = int(np.argmin(np.abs(np.asarray(fs) - F_LO))), int(np.argmin(np.abs(np.asarray(fs) - F_HI)))
        w_lo = 2 * math.pi * fs[lo]
        ylo, yhi = y[lo], y[hi]
        cgd = -ylo[0, 1].imag / w_lo
        cgs = ylo[0, 0].imag / w_lo - cgd
        cdb = ylo[1, 1].imag / w_lo - cgd
        k = int(np.argmin(np.abs(vg - vb)))
        h = vg[1] - vg[0]
        idk = float(np.interp(vb, vg, i_d))
        g1 = float(np.interp(vb, vg, np.gradient(i_d, h)))
        g3 = float(np.interp(vb, vg, np.gradient(np.gradient(np.gradient(i_d, h), h), h))) / 6.0
        a_iip3 = math.sqrt(4.0 / 3.0 * abs(g1 / g3)) if abs(g3) > 1e-12 else 1.0
        a1db = min(0.33 * a_iip3, 0.35)                            # same rule as device.device_op
        rows.append({
            "w_um": lay["w_um"], "nr": lay["nr"], "multi": lay["multi"], "vgs_v": vb, "vds_v": vdd,
            "id_ma": idk * 1e3, "gm_s": float(ylo[1, 0].real), "gm_dc_s": g1, "gds_s": float(ylo[1, 1].real),
            "cgs_f": cgs, "cgd_f": cgd, "cdb_f": cdb, "rg_ohm": float((1 / yhi[0, 0]).real),
            "ft_ghz": float(abs(yhi[1, 0] / yhi[0, 0]) * fs[hi] / 1e9), "nfmin_db_30g": float(nfmin[hi]),
            "a1db_v": a1db, "vdsat_v": float(2 * idk / g1) if g1 > 0 else float("nan"), "dc_index": k,
            "dc_valid": bool(vb <= vg[-1] - 0.02)})
    return rows


NR_CANDIDATES = [2, 4, 8, 16, 32, 64]  # probed; even counts between the smallest and largest valid one are used


def characterize(runner, cfg: dict, widths: list[float], vbs: list[float], out_root: Path | None = None,
                 nr_candidates: list[int] | None = None, vds: float | None = None,
                 freqs: list[float] | None = None) -> dict:
    """V2-2: validate finger counts once, then one Spectre run per width (DC sweep + S/noise at each bias)."""
    ts = time.strftime("%Y%m%dT%H%M%S")
    local = (out_root or ROOT / "results" / "runs" / "pdk_char") / ts
    rroot = str(PurePosixPath(runner.config.remote_root) / f"pdk_char_{ts}")
    report: dict = {"ts": ts, "local_dir": str(local), "validation": {}, "widths": {}, "spectre_runs": 0}
    valid = []
    for nr in (nr_candidates if nr_candidates is not None else NR_CANDIDATES):
        lay = {"nr": nr, "multi": 1, "w_um": cfg["wr_um"] * nr}
        st = run_spectre(runner, validation_netlist(cfg, lay), f"{rroot}/val_nr{nr}", local / f"val_nr{nr}", timeout_s=120)
        report["spectre_runs"] += 1
        report["validation"][nr] = st
        if st["ok"]:
            valid.append(nr)
    if nr_candidates == []:  # validation skipped: reuse the range found earlier (2..64 even on crn40lp)
        valid = [2, 64]
    report["valid_nr"] = valid
    report["vds_v"] = float(vds if vds is not None else cfg["vdd"])
    report["freqs_hz"] = sorted(set((freqs or []) + [F_LO, F_HI]))
    usable = list(range(min(valid), max(valid) + 1, 2)) if valid else []
    report["usable_nr"] = usable
    rows: list[dict] = []
    if valid:
        for w in widths:
            lay = layout_for(w, float(cfg["wr_um"]), usable)
            tag = f"w{w:g}"
            st = run_spectre(runner, char_netlist(cfg, lay, vbs, vds, freqs), f"{rroot}/{tag}", local / tag)
            report["spectre_runs"] += 1
            entry = {"layout": lay, "steps": st}
            if st["ok"]:
                try:
                    r = extract_rows(local / tag, lay, vbs, float(vds if vds is not None else cfg["vdd"]))
                    for x in r:
                        x["w_target_um"] = w
                    rows += r
                except Exception as exc:  # keep going; the report shows which width failed
                    entry["parse_error"] = repr(exc)[:400]
            report["widths"][tag] = entry
    report["rows"] = rows
    local.mkdir(parents=True, exist_ok=True)
    (local / "device_table.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# V2-3: PDK device table as the engine's device provider
# ---------------------------------------------------------------------------
from .device import DeviceOP  # noqa: E402

_PER_W = ("id_ma", "gm_s", "gds_s", "cgs_f", "cgd_f", "cdb_f")


class PdkTable:
    """Interpolates the characterised rows: linear in Vgs (log for current), per-micron scaling in W.

    ``rg_ohm`` scales as 1/W; ``a1db_v`` and ``vdsat_v`` are width-independent.  Widths outside the table
    are extrapolated by the per-micron values of the nearest characterised width (gate fingers in parallel).
    """

    def __init__(self, rows: list[dict], vdd: float, name: str = "pdk_table", vb_grid=None) -> None:
        rows = [self._apply_fit(r) for r in rows]
        by_w: dict[float, list[dict]] = defaultdict(list)
        for r in rows:
            by_w[float(r["w_um"])].append(r)
        self.widths = np.array(sorted(by_w))
        self.vgs = np.array(sorted({float(r["vgs_v"]) for r in rows}))
        self.fitted = all("fit" in r for r in rows)
        self.large_signal = all(r.get("a1db_ls_v") is not None for r in rows)
        self.data: dict[str, np.ndarray] = {}
        keys = _PER_W + ("rg_ohm", "ri_ohm", "tau_s", "gamma", "dg", "a1db_v", "vdsat_v", "nfmin_db_30g", "ft_ghz")
        for k in keys:
            m = np.empty((len(self.widths), len(self.vgs)))
            for i, w in enumerate(self.widths):
                rr = sorted(by_w[w], key=lambda r: r["vgs_v"])
                v = np.array([float(r.get(k, 0.0) if r.get(k) is not None else 0.0) for r in rr])
                if k in _PER_W:
                    v = v / w
                elif k in ("rg_ohm", "ri_ohm"):
                    v = v * w
                m[i] = v
            self.data[k] = m
        self.vdd, self.name = float(vdd), name
        self.vb_grid = list(vb_grid) if vb_grid is not None else [float(v) for v in self.vgs]

    @staticmethod
    def _apply_fit(r: dict) -> dict:
        """Rows refitted by pdk_fit carry the two-frequency model; prefer it over the 5-GHz lumped values."""
        f = r.get("fit")
        if not f:
            return r
        r = dict(r)
        r.update(gm_s=f["gm"], gds_s=f["gds"], cgs_f=f["cgs"], cgd_f=f["cgd"], cdb_f=f["cdb"], rg_ohm=f["rg"],
                 ri_ohm=f["ri"], tau_s=f["tau"], gamma=f["gamma"], dg=f["dg"])
        if r.get("a1db_ls_v") is not None and np.isfinite(r["a1db_ls_v"]):
            r["a1db_v"] = float(r["a1db_ls_v"])
        return r

    @classmethod
    def from_json(cls, path: Path, vdd: float | None = None, name: str | None = None) -> "PdkTable":
        rep = json.loads(Path(path).read_text(encoding="utf-8"))
        # rows from tables whose DC sweep stopped at 0.75 V carry clamped currents above it (first pass, 2026-10-01)
        rows = [r for r in rep["rows"] if r.get("dc_valid", float(r["vgs_v"]) <= 0.70 + 1e-9)]
        return cls(rows, vdd if vdd is not None else float(rows[0]["vds_v"]), name or "pdk_table")

    def _q(self, key: str, w: float, vgs: float) -> float:
        i = int(np.clip(np.searchsorted(self.widths, w), 1, len(self.widths) - 1))
        w0, w1 = self.widths[i - 1], self.widths[i]
        t = float(np.clip((w - w0) / (w1 - w0), 0.0, 1.0))
        row = (1 - t) * self.data[key][i - 1] + t * self.data[key][i]
        if key == "id_ma":
            return float(np.exp(np.interp(vgs, self.vgs, np.log(np.maximum(row, 1e-12)))))
        return float(np.interp(vgs, self.vgs, row))

    def get(self, key: str, w: float, vgs: float) -> float:
        v = self._q(key, w, vgs)
        if key in _PER_W:
            return v * w
        if key in ("rg_ohm", "ri_ohm"):
            return v / w
        return v

    def id_ma(self, w_um, vgs):
        w, v = np.broadcast_arrays(np.asarray(w_um, float), np.asarray(vgs, float))
        out = np.array([self.get("id_ma", float(a), float(b)) for a, b in zip(w.ravel(), v.ravel())])
        return out.reshape(w.shape) if w.shape else float(out[0])

    def op(self, kind: str, w_um: float, vgs_v: float) -> DeviceOP:
        g = {k: self.get(k, w_um, vgs_v) for k in _PER_W + ("rg_ohm", "a1db_v", "vdsat_v")}
        extra = {}
        if self.fitted:
            extra = dict(tau_s=self.get("tau_s", w_um, vgs_v), ri_ohm=self.get("ri_ohm", w_um, vgs_v),
                         gamma=self.get("gamma", w_um, vgs_v), dg=self.get("dg", w_um, vgs_v))
        return DeviceOP(kind=kind, w_um=float(w_um), vgs_v=float(vgs_v), id_ma=g["id_ma"], gm_s=g["gm_s"],
                        gds_s=g["gds_s"], cgs_f=g["cgs_f"], cgd_f=g["cgd_f"], cdb_f=g["cdb_f"],
                        rg_ohm=g["rg_ohm"], a1db_v=g["a1db_v"], vdsat_v=g["vdsat_v"], **extra)


# ---------------------------------------------------------------------------
# V2-1 / V2-4 / V2-5: full LNA with PDK RF transistors (bias tees, neutralisation, HB compression)
# ---------------------------------------------------------------------------
from . import circuit as ck  # noqa: E402
from .backend_cadence import (SAVE_NODES, T_NOISE_C, CadenceBackend, _expand, _g,  # noqa: E402
                              parse_results)


def render_pdk_netlist(design: ck.LNADesign, f_hz: np.ndarray, cfg: dict, usable_nr: list[int], *,
                       upto: str | None = None, include_match: bool = True,
                       nominal_load: tuple[float, float] | None = None,
                       hb_pin_dbm: list[float] | None = None) -> tuple[str, float, dict]:
    """Fig. 3 chain with ``cfg['nmos']`` devices.  Inductor/resistor returns go to the supply or the next gate's
    bias source (AC grounds), ports are DC-blocked, stage-2/3 Cgd is neutralised by an ideal inverter + capacitor
    (the half-circuit view of the paper's cross-coupled pair).  Gate resistance is inside the RF cell."""
    op1, op2, op3 = design.ops
    f_ref, vdd = design.fc_hz, float(cfg["vdd"])
    L: list[str] = _header(cfg)[:-1] + [f'include "{cfg["toplevel"]}" section={cfg["section"]}',
                                        f"opts options temp={T_NOISE_C} tnom=27"]
    pin = hb_pin_dbm[0] if hb_pin_dbm else -60.0
    L.append(f"parameters pin={pin:g}")
    L += [f"VDD (vdd 0) vsource dc={vdd:g}", f"VB1 (vb1 0) vsource dc={op1.vgs_v:.6g}",
          f"VB2 (vb2 0) vsource dc={op2.vgs_v:.6g}", f"VB3 (vb3 0) vsource dc={op3.vgs_v:.6g}"]
    L.append(f"PORT1 (p1 0) port r=50 num=1 mag=1 type=sine freq={f_ref:.10g} dbm=pin")
    L.append("CDC1 (p1 in) capacitor c=1")
    k = [0]

    def uid(p):
        k[0] += 1
        return f"{p}{k[0]}"

    def lossy(a, b, l_h, q):
        m = uid("xl")
        L.append(f"L{m} ({a} {m}) inductor l={_g(l_h)}")
        L.append(f"R{m} ({m} {b}) resistor r={_g(2 * math.pi * f_ref * l_h / q)}")

    def mcr(m, a, b, ret_a, ret_b):
        u = uid("k")
        wl = 2 * math.pi * m.f_loss_hz
        L.append(f"L{u}p ({a} {u}p) inductor l={_g(m.l1_h)}")
        L.append(f"R{u}p ({u}p {ret_a}) resistor r={_g(wl * m.l1_h / m.q_ind)}")
        L.append(f"L{u}s ({b} {u}s) inductor l={_g(m.l2_h)}")
        L.append(f"R{u}s ({u}s {ret_b}) resistor r={_g(wl * m.l2_h / m.q_ind)}")
        L.append(f"K{u} mutual_inductor coupling={_g(m.k)} ind1=L{u}p ind2=L{u}s")
        for node, r, c, ret in ((a, m.r1_ohm, m.c1_f, ret_a), (b, m.r2_ohm, m.c2_f, ret_b)):
            if math.isfinite(r):
                L.append(f"R{u}{node} ({node} {ret}) resistor r={_g(r)}")
            if c > 0:
                L.append(f"C{u}{node} ({node} {ret}) capacitor c={_g(c)}")

    lays = {}

    def fet(name, d, g, s, op):
        lay = layout_for(op.w_um, float(cfg["wr_um"]), usable_nr)
        lays[name] = lay
        L.append(_inst(cfg, name, d, g, s, "0", lay))

    def neutralise(tag, d, g, op):
        # half circuit of a cross-coupled pair: CN from the gate to the opposite drain AND from the drain to the
        # opposite gate (both opposite nodes are the inverted own nodes)
        cn = _g(op.cgd_f * (1 - ck.TECH.neutralization_residual))
        L.append(f"EN{tag} (dn{tag} 0 {d} 0) vcvs gain=-1")
        L.append(f"CN{tag} (dn{tag} {g}) capacitor c={cn}")
        L.append(f"EG{tag} (gn{tag} 0 {g} 0) vcvs gain=-1")
        L.append(f"CM{tag} (gn{tag} {d}) capacitor c={cn}")

    if include_match:
        lossy("in", "vb1", design.lpar_h, ck.Q_MATCH)
        lossy("in", "g1", design.lg_h, ck.Q_MATCH)
    else:
        L.append("RSHORT (in g1) resistor r=1e-6 isnoisy=no")
        L.append("LB1 (vb1 g1) inductor l=1")
    L.append("RG1 (g1 g1i) resistor r=1m isnoisy=no")
    fet("M1", "cas", "g1i", "s1", op1)
    if design.ls_h > 0:
        lossy("s1", "0", design.ls_h, ck.Q_MATCH)
    else:
        L.append("RLS0 (s1 0) resistor r=1e-6 isnoisy=no")
    fet("MCG", "d1", "vdd", "cas", ck.cascode_device(op1))
    mcr(design.mcr1, "d1", "g2", "vdd", "vb2")
    L.append("RG2 (g2 g2i) resistor r=1m isnoisy=no")
    fet("M2", "d2", "g2i", "0", op2)
    neutralise("2", "d2", "g2i", op2)
    if upto == "stage2":
        rl, cl = nominal_load or (250.0, 0.0)
        out = "d2"
        L += ["LDC2 (vdd d2) inductor l=1", "CDC2 (d2 p2) capacitor c=1", f"PORT2 (p2 0) port r={_g(rl)} num=2"]
    else:
        mcr(design.mcr2, "d2", "g3", "vdd", "vb3")
        L.append("RG3 (g3 g3i) resistor r=1m isnoisy=no")
        fet("M3", "d3", "g3i", "0", op3)
        neutralise("3", "d3", "g3i", op3)
        mcr(design.mcr3, "d3", "out", "vdd", "0")
        rl, cl = design.load
        out = "out"
        L.append(f"PORT2 (out 0) port r={_g(rl)} num=2")
    if cl > 0:
        L.append(f"CLOAD ({out} 0) capacitor c={_g(cl)}")
    freqs = " ".join(_g(f) for f in np.asarray(f_hz, float))
    L.append("dcop dc")
    L.append(f"sp1 sp values=[{freqs}] ports=[PORT1 PORT2] donoise=yes oprobe=PORT2 iprobe=PORT1")
    L.append(f"ac1 ac values=[{freqs}]")
    if hb_pin_dbm:
        L.append(f"hbsw sweep param=pin values=[{' '.join(f'{p:g}' for p in hb_pin_dbm)}] {{")
        L.append(f"  hb hb fundfreqs=[{f_ref:.10g}] maxharms=[5] annotate=status")
        L.append("}")
    present = [x for x in SAVE_NODES if (x != "out" or out == "out") and not (upto == "stage2" and x in ("g3", "g3i", "d3"))]
    L.append("save " + " ".join(present) + " cas VDD:p VB1:p " + " ".join(f"{m}:d" for m in lays))
    return "\n".join(L) + "\n", rl, lays


def parse_hb_sweep(psf: Path, out_node: str, rl: float, fc: float, pins: list[float]) -> dict:
    files = sorted((p for p in psf.iterdir() if "hb.fd" in p.name and "pss_hb" in p.name),
                   key=lambda p: [int(x) for x in re.findall(r"-(\d+)_", p.name)] or [0])
    if len(files) != len(pins):
        raise ValueError(f"expected {len(pins)} HB results, found {len(files)}")
    rows = []
    for pin, f in zip(pins, files):
        fr, v = parse_complex_trace(f, out_node)
        k = int(np.argmin(np.abs(np.asarray(fr) - fc)))
        pout = 10 * math.log10(max(abs(v[k]) ** 2 / (2 * rl), 1e-30) / 1e-3)
        rows.append({"pin_dbm": pin, "pout_dbm": pout, "gain_db": pout - pin})
    g0 = rows[0]["gain_db"]
    ip1 = None
    for a, b in zip(rows, rows[1:]):
        if a["gain_db"] > g0 - 1 >= b["gain_db"]:
            t = (a["gain_db"] - (g0 - 1)) / (a["gain_db"] - b["gain_db"])
            ip1 = a["pin_dbm"] + t * (b["pin_dbm"] - a["pin_dbm"])
            break
    return {"rows": rows, "small_signal_gain_db": g0, "ip1db_dbm": ip1,
            "compressed_within_sweep": ip1 is not None}


class PdkCadenceBackend(CadenceBackend):
    """Stage-4 backend with PDK RF transistors; IP1dB from a Spectre HB power sweep when ``hb_pins`` is set."""

    def __init__(self, cfg: dict | None = None, usable_nr: list[int] | None = None,
                 hb_pins: list[float] | None = None, **kw) -> None:
        self.cfg = cfg or load_pdk_config()
        self.usable_nr = usable_nr or list(range(2, 65, 2))
        self.hb_pins = hb_pins
        self.max_calls = int(os.environ.get("ORFADC_SPECTRE_MAX_PER_DESIGN", "0")) or None
        super().__init__(**kw)
        self.name = f"cadence_spectre_{self.cfg.get('name', 'pdk')}"
        self.local_root = ROOT / "results" / "runs" / "repro_cadence_pdk"

    def simulate(self, design, f_hz, *, upto=None, include_match=True, nominal_load=None) -> dict:
        t0 = time.perf_counter()
        self.n_calls += 1
        tag = f"sim{self.n_calls:05d}"
        local = self.local_root / self.run_id / tag
        f_req = np.asarray(f_hz, float)
        f_u, inv = np.unique(np.array([float(_g(x)) for x in f_req]), return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
        pins = self.hb_pins if upto is None else None
        text, r_out, lays = render_pdk_netlist(design, f_u, self.cfg, self.usable_nr, upto=upto,
                                               include_match=include_match, nominal_load=nominal_load, hb_pin_dbm=pins)
        steps = run_spectre(self, text, str(PurePosixPath(self.remote_root) / tag), local, timeout_s=self.timeout_s)
        (local / "design.json").write_text(json.dumps({"summary": design.summary(), "fc_hz": design.fc_hz,
                                                      "load": list(design.load), "upto": upto}, default=float, indent=1),
                                           encoding="utf-8")
        if not steps["ok"]:
            (local / "metrics.json").write_text(json.dumps({"status": "spectre_failed", "steps": steps}, indent=1))
            raise RuntimeError(f"PDK Spectre run failed: {steps}")
        out = _expand(parse_results(local / "psf", design, f_u, r_out, upto), inv, len(f_u))
        out["f_hz"] = f_req
        out["source"] = "cadence_spectre_pdk"
        out["compression"]["estimate_ip1db_dbm"] = out["compression"]["ip1db_dbm"]
        try:  # engine prediction of the same design, kept next to Spectre for calibration (docs/121)
            eng = ck.simulate(design, f_req, upto=upto, include_match=include_match, nominal_load=nominal_load)
            out["engine"] = {k: np.asarray(eng[k]).tolist() for k in ("gain_db", "s11_db", "nf_db")}
            out["engine"]["ip1db_dbm"] = eng["compression"]["ip1db_dbm"]
        except Exception as exc:  # never let bookkeeping break a Spectre evaluation
            out["engine"] = {"error": repr(exc)[:200]}
        if pins:
            hb = parse_hb_sweep(local / "psf", "out" if upto is None else "d2", r_out, design.fc_hz, pins)
            out["hb"] = hb
            if hb["ip1db_dbm"] is not None:
                out["compression"]["ip1db_dbm"] = hb["ip1db_dbm"]
                out["compression"]["source"] = "spectre_hb_power_sweep"
            else:  # no 1-dB point inside the sweep: report the largest input power (lower bound)
                out["compression"]["ip1db_dbm"] = max(pins)
                out["compression"]["source"] = "spectre_hb_lower_bound"
        dc = read_dc_point(local / "psf" / "dcop.dc")
        out["supply_ma"] = -dc["VDD:p"] * 1e3 if "VDD:p" in dc else None
        out["drain_ma"] = {m: dc[f"{m}:d"] * 1e3 for m in lays if f"{m}:d" in dc}
        d = out["drain_ma"]
        if upto is None and {"M1", "M2", "M3"} <= set(d):
            # half circuit simulated; stages 2/3 are differential pairs -> count both halves (stage 1 is single-ended)
            out["power_ma_measured"] = d["M1"] + 2 * (d["M2"] + d["M3"])
        dt = time.perf_counter() - t0
        self.wall_s += dt
        (local / "metrics.json").write_text(json.dumps({
            "status": "ok", "backend": self.name, "wall_s": dt, "upto": upto, "steps": steps, "layouts": lays,
            "gain_db": out["gain_db"].tolist(), "s11_db": out["s11_db"].tolist(), "nf_db": out["nf_db"].tolist(),
            "ip1db_dbm": out["compression"]["ip1db_dbm"], "hb": out.get("hb"), "supply_ma": out["supply_ma"],
            "drain_ma": out.get("drain_ma"), "power_ma_measured": out.get("power_ma_measured"),
            "engine": out.get("engine"), "estimate_ip1db_dbm": out["compression"].get("estimate_ip1db_dbm"),
            "not_lna_result": False,
            "note": "PDK transistors (RF MOS cells), ideal passives/bias; no layout parasitics"}, indent=1, default=float),
            encoding="utf-8")
        return out

    # RemoteRunner-like facade so run_spectre() can be reused with self as the runner
    @property
    def config(self):
        return self.runner.config

    def ensure_remote_dir(self, d):
        return self.runner.ensure_remote_dir(d)

    def upload(self, a, b):
        return self.runner.upload(a, b)

    def run_shell(self, *a, **k):
        return self.runner.run_shell(*a, **k)

    def download(self, a, b):
        return self.runner.download(a, b)


def _tables(root: Path | None = None) -> dict[float, Path]:
    """Best characterisation per drain bias: {vds: device_table.json} (fitted first, then most rows, newest on ties)."""
    best: dict[float, tuple] = {}
    for p in sorted((root or ROOT / "results" / "runs" / "pdk_char").glob("*/device_table.json")):
        rep = json.loads(p.read_text(encoding="utf-8"))
        rows = [r for r in rep.get("rows", []) if r.get("dc_valid", float(r["vgs_v"]) <= 0.70 + 1e-9)]
        if not rows:
            continue
        vds = round(float(rows[0]["vds_v"]), 3)
        fitted = any("fit" in r for r in rows)          # a refit (docs/122) beats a raw table of the same bias
        key = (fitted, len(rows), p.parent.name)
        if vds not in best or key > best[vds][0]:
            best[vds] = (key, p)
    return {v: k[1] for v, k in best.items()}


def read_dc_point(path: Path) -> dict[str, float]:
    """``"name" "V|I" value PROP(`` lines of a single-point PSFASCII DC file."""
    vals: dict[str, float] = {}
    if not Path(path).exists():
        return vals
    for line in Path(path).read_text(errors="replace").splitlines():
        m = re.match(r'^"([^"]+)"\s+"[A-Z]"\s+([-+0-9.eE]+)', line)
        if m:
            vals[m.group(1)] = float(m.group(2))
    return vals


def latest_table(root: Path | None = None) -> Path:
    t = _tables(root)
    if not t:
        raise FileNotFoundError("no PDK device table; run `bench pdk-characterize` first")
    return t[max(t)]


class PdkProvider:
    """Kind-aware provider: the stage-1 cascode devices (CS + CG, each with ~VDD/2 across it) use the low-Vds
    table, the neutralised CS stages the full-VDD table.  ``cascode_ratio`` widens the CG device so that its
    Vgs leaves the CS device in saturation at a 1.1 V supply."""

    def __init__(self, full: PdkTable, low: PdkTable | None, vdd: float, name: str, cascode_ratio: float = 1.0,
                 ip1db_offset_db: float = 0.0):
        self.full, self.low = full, low or full
        self.vdd, self.name, self.cascode_ratio = float(vdd), name, cascode_ratio
        self.physical_cdb = self.full.fitted     # fitted tables describe the real (drain-bulk) Cdb placement
        self.neutralization = "cross_coupled"   # matches render_pdk_netlist's half circuit
        self.large_signal_table = self.full.large_signal
        self.ip1db_offset_db = float(ip1db_offset_db)
        self.vb_grid = [v for v in full.vb_grid if v in set(self.low.vb_grid)] or full.vb_grid

    def op(self, kind, w_um, vgs_v):
        return (self.low if kind == "cascode" else self.full).op(kind, w_um, vgs_v)

    def id_ma(self, w_um, vgs):  # only used to bias the CG device of the cascode
        return self.low.id_ma(w_um, vgs)


def install_table(path: Path | None = None, cascode_ratio: float | None = None):
    from . import device as D
    cfg = load_pdk_config()
    vdd = float(cfg["vdd"])
    name = f"pdk_table_{cfg.get('name', 'pdk')}"
    if path is not None:
        prov = PdkTable.from_json(path, vdd=vdd, name=name)
    else:
        t = _tables()
        if not t:
            raise FileNotFoundError("no PDK device table; run `bench pdk-characterize` first")
        full = PdkTable.from_json(t[max(t)], vdd=vdd, name=name)
        low = PdkTable.from_json(t[min(t)], vdd=vdd, name=name) if len(t) > 1 else None
        ratio = cascode_ratio if cascode_ratio is not None else float(cfg.get("cascode_ratio", 1.0 if low else 0.45))
        prov = PdkProvider(full, low, vdd, name + ("_vds2" if low else "") + ("_fit" if full.fitted else ""), ratio,
                           ip1db_offset_db=float(cfg.get("ip1db_offset_db", 0.0)))
    D.set_device_provider(prov)
    if cfg.get("use_y3", True) and os.environ.get("ORFADC_PDK_Y3", "1") != "0":   # docs/123 measured stage-1 3-port
        from . import pdk3
        pdk3.install_y3()
    return prov
