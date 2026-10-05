"""Tiny independent 'Spectre' for the macromodel netlists written by repro.backend_cadence.

Modified nodal analysis of the element subset the renderer emits (port, resistor, capacitor,
inductor, mutual_inductor, vsource, vccs, cccs, ccvs) plus a thermal-noise analysis
(every resistor without ``isnoisy=no`` and the input port; the output port is excluded, as in
Spectre's two-port NF).  It shares no code with the two-port engine, so agreement between the
two is a real check of the netlist translation.  Validated against real Spectre PSF output
(tests/data/spectre_s2_stage2/): S-parameters and NF agree to ~1e-12.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

_EL = re.compile(r"(\w+) \(([^)]*)\) (\w+) (.*)")
_MUT = re.compile(r"(\w+) mutual_inductor (.*)")
_KV = re.compile(r"(\w+)=(\S+)")


def parse_netlist(text: str) -> tuple[list, dict]:
    els, analyses = [], {}
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith(("sp1 sp", "ac1 ac")):
            vals = re.search(r"values=\[([^\]]*)\]", ln).group(1).split()
            analyses[ln[:3]] = np.array([float(v) for v in vals])
            continue
        m = _EL.match(ln)
        if m:
            name, nodes, typ, rest = m.groups()
            els.append((name, nodes.split(), typ, dict(_KV.findall(rest))))
            continue
        m = _MUT.match(ln)
        if m:
            els.append((m.group(1), [], "mutual_inductor", dict(_KV.findall(m.group(2)))))
    return els, analyses


def _solve(els, f: float, *, drive: str | None, inject: tuple[str, str] | None = None,
           ys_override: complex | None = None) -> dict[str, complex]:
    """Node voltages.  ``drive`` = port name driven by a 1 V EMF behind its resistance;
    ``inject`` = unit current from node a to node b; ``ys_override`` replaces PORT1's admittance."""
    s = 2j * math.pi * f
    nodes = {"0": -1}
    for _, ns, _, _ in els:
        for x in ns:
            nodes.setdefault(x, len(nodes) - 1)
    n = len(nodes) - 1
    br = {}
    for name, _, t, _ in els:
        if t in ("vsource", "inductor", "ccvs"):
            br[name] = n + len(br)
    a = np.zeros((n + len(br),) * 2, complex)
    b = np.zeros(n + len(br), complex)

    def y(p, q, val):
        i, j = nodes[p], nodes[q]
        if i >= 0:
            a[i, i] += val
        if j >= 0:
            a[j, j] += val
        if i >= 0 and j >= 0:
            a[i, j] -= val
            a[j, i] -= val

    ind = {}
    for name, ns, t, p in els:
        if t == "resistor":
            y(*ns, 1.0 / float(p["r"]))
        elif t == "capacitor":
            y(*ns, s * float(p["c"]))
        elif t == "port":
            yp = ys_override if (ys_override is not None and p.get("num") == "1") else 1.0 / float(p["r"])
            y(*ns, yp)
            if name == drive:
                i = nodes[ns[0]]
                b[i] += yp  # 1 V EMF behind the port admittance (Norton)
        elif t == "vccs":
            gm = float(p["gm"])
            o1, o2, c1, c2 = (nodes[x] for x in ns)
            for o, so in ((o1, 1), (o2, -1)):
                for c, sc in ((c1, 1), (c2, -1)):
                    if o >= 0 and c >= 0:
                        a[o, c] += so * sc * gm
    for name, ns, t, p in els:
        if name in br:
            k = br[name]
            i, j = nodes[ns[0]], nodes[ns[1]]
            if i >= 0:
                a[i, k] += 1
                a[k, i] += 1
            if j >= 0:
                a[j, k] -= 1
                a[k, j] -= 1
            if t == "inductor":
                a[k, k] -= s * float(p["l"])
                ind[name] = float(p["l"])
            elif t == "ccvs":
                a[k, br[p["probe"]]] -= float(p["rm"])
    for name, ns, t, p in els:
        if t == "mutual_inductor":
            l1, l2 = p["ind1"], p["ind2"]
            mm = float(p["coupling"]) * math.sqrt(ind[l1] * ind[l2])
            a[br[l1], br[l2]] -= s * mm
            a[br[l2], br[l1]] -= s * mm
        elif t == "cccs":
            k = br[p["probe"]]
            i, j = nodes[ns[0]], nodes[ns[1]]
            if i >= 0:
                a[i, k] += float(p["gain"])
            if j >= 0:
                a[j, k] -= float(p["gain"])
    if inject:
        i, j = nodes[inject[0]], nodes[inject[1]]
        if i >= 0:
            b[i] -= 1
        if j >= 0:
            b[j] += 1
    x = np.linalg.solve(a, b)
    return {k: (x[i] if i >= 0 else 0j) for k, i in nodes.items()}


def _ports(els):
    return {p["num"]: (name, ns[0], float(p["r"])) for name, ns, t, p in els if t == "port"}


def noise_factor(els, f: float, ys: complex | None = None) -> float:
    ports = _ports(els)
    p1, out = ports["1"], ports["2"][1]
    tot = src = 0.0
    for name, ns, t, p in els:
        if t == "resistor" and p.get("isnoisy", "yes") != "no":
            g = 1.0 / float(p["r"])
        elif name == p1[0]:
            g = (ys if ys is not None else 1.0 / p1[2]).real
        else:
            continue
        h = abs(_solve(els, f, drive=None, inject=(ns[0], ns[1]), ys_override=ys)[out]) ** 2 * g
        tot += h
        if name == p1[0]:
            src = h
    return tot / src


def fmin(els, f: float) -> float:
    """Fit F(Ys) = Fmin + Rn/Gs |Ys - Yopt|^2 from several source admittances."""
    rows, rhs = [], []
    for gs in (0.005, 0.02, 0.06):
        for bs in (-0.03, 0.0, 0.03):
            ys = complex(gs, bs)
            fval = noise_factor(els, f, ys)
            rows.append([gs * gs + bs * bs, gs, bs, 1.0])
            rhs.append(fval * gs)
    p1, p2, p3, p4 = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    bo = -p3 / (2 * p1)
    go = math.sqrt(max(p4 / p1 - bo * bo, 0.0))
    return p2 + 2 * p1 * go


def run(netlist: Path, psf_dir: Path, nodes_to_save: list[str] | None = None) -> None:
    """Write sp1.sp / sp1.noise.sp / ac1.ac in the PSFASCII subset the parser reads."""
    text = Path(netlist).read_text()
    els, an = parse_netlist(text)
    save = re.search(r"^save (.*)$", text, re.M)
    save = nodes_to_save or (save.group(1).split() if save else [])
    ports = _ports(els)
    (n1, in_node, r1), (_, out_node, r2) = ports["1"], ports["2"]
    psf_dir.mkdir(parents=True, exist_ok=True)
    fs = np.unique(an["sp1"])  # Spectre sorts and de-duplicates a values=[...] sweep
    with open(psf_dir / "sp1.sp", "w") as sp, open(psf_dir / "sp1.noise.sp", "w") as nz, \
            open(psf_dir / "ac1.ac", "w") as ac:
        for fh in (sp, nz, ac):
            fh.write("HEADER\nVALUE\n")
        for f in fs:
            v = _solve(els, f, drive=n1)          # Vs = 1 V EMF
            s11 = 2 * v[in_node] - 1
            s21 = 2 * v[out_node] * math.sqrt(r1 / r2)
            sp.write(f'"freq" {f:.15e}\n"s11" ({s11.real:.15e} {s11.imag:.15e})\n"s21" ({s21.real:.15e} {s21.imag:.15e})\n')
            nz.write(f'"freq" {f:.15e}\n"NF" {10 * math.log10(noise_factor(els, f)):.15e}\n'
                     f'"NFmin" {10 * math.log10(fmin(els, f)):.15e}\n')
            ac.write(f'"freq" {f:.15e}\n')
            for k in save:
                vk = 2 * v[k]  # Spectre's `port mag=1` is a 2 V EMF (1 V incident wave into 50 ohm)
                ac.write(f'"{k}" ({vk.real:.15e} {vk.imag:.15e})\n')
