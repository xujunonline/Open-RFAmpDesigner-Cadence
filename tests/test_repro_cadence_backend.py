"""CadenceBackend offline: netlist rendering + a fake remote runner that 'runs Spectre'
by writing PSFASCII files computed with the two-port engine (exercises upload/run/
download/parse/normalisation exactly as with the real SSH runner)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

import numpy as np
import pytest

from orfadc.repro import backend_cadence as BC
from orfadc.repro import circuit as ck
from orfadc.repro import tools as T
from orfadc.config_loader import load_specs

ROOT = Path(__file__).resolve().parents[1]
SPECS = {s.id: s for s in load_specs(ROOT / "config" / "specs_table_iii.yaml")}


def _design():
    sp = SPECS["S2"]
    ctx = T.ToolContext(sp)
    cfg = T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0]
    s2 = T.impedance_matching(ctx, cfg, iters=3, n_particles=4)
    return T.band_planning(ctx, cfg, s2, sa_iters=80, max_rounds=1)["_design"]


@dataclass
class _R:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self):
        return self.returncode == 0


class FakeRunner:
    """Stands in for RemoteRunner; the 'remote' is a local temp directory."""

    def __init__(self, root: Path, design):
        self.root, self.design = root, design
        self.config = type("C", (), {"remote_root": "/fake/root", "spectre_bin": "spectre"})()
        self.calls = []

    def _p(self, remote: str) -> Path:
        return self.root / remote.lstrip("/")

    def ensure_remote_dir(self, d):
        self._p(d).mkdir(parents=True, exist_ok=True)
        return _R()

    def upload(self, local, remote):
        self._p(remote).write_bytes(Path(local).read_bytes())
        return _R()

    def download(self, remote, local):
        src = self._p(remote)
        if not src.exists():
            return _R(1, stderr="missing")
        Path(local).write_bytes(src.read_bytes())
        return _R()

    def probe(self, tools):
        return {"tool.spectre": "/fake/spectre"}

    def run_remote(self, argv, cwd=None, timeout_seconds=None):
        self.calls.append(argv)
        net = (self._p(cwd) / "netlist.scs").read_text()
        f = np.array([float(x) for x in re.search(r"sp1 sp values=\[([^\]]*)\]", net).group(1).split()])
        upto = None if "PORT2 (out 0)" in net else "stage2"
        rl = float(re.search(r"PORT2 \(\w+ 0\) port r=([0-9.eE+-]+)", net).group(1))
        kw = dict(upto=upto, include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD if upto else None)
        res = ck.simulate(self.design, f, **kw)
        s = 2j * math.pi * f
        blocks = ck._chain(self.design, s, upto=upto, include_match=True)
        load = kw["nominal_load"] if upto else self.design.load
        zl = ck._load_z(s, load)
        psf = self._p(cwd) / "psf"
        psf.mkdir(exist_ok=True)
        g = 10 ** (res["gain_db"] / 20) * math.sqrt(50 / rl)
        s11 = (res["zin"] - 50) / (res["zin"] + 50)
        with open(psf / "sp1.sp", "w") as fh:
            fh.write('HEADER\nVALUE\n')
            for i, fi in enumerate(f):
                fh.write(f'"freq" {fi:.15e}\n"s11" ({s11[i].real:.15e} {s11[i].imag:.15e})\n"s21" ({g[i]:.15e} 0.0)\n')
        with open(psf / "sp1.noise.sp", "w") as fh:
            fh.write('HEADER\nVALUE\n')
            for i, fi in enumerate(f):
                fh.write(f'"freq" {fi:.15e}\n"NF" {res["nf_db"][i]:.15e}\n"NFmin" {res["nfmin_db"][i]:.15e}\n')
        names = [n for n, _ in blocks]
        amap = {"in": names[0], "g1i": "dev1", "d1": "mcr1", "g2": "rg2", "g2i": "dev2"}
        if upto is None:
            amap.update({"d2": "mcr2", "g3": "rg3", "g3i": "dev3", "d3": "mcr3"})
        with open(psf / "ac1.ac", "w") as fh:
            fh.write('HEADER\nVALUE\n')
            for i, fi in enumerate(f):
                nv = ck._node_voltages(blocks, i, complex(zl[i]))
                vals = {k: nv[b][0] for k, b in amap.items()}
                vals["s1"] = vals["g1i"] - nv["dev1"][1] / (s[i] * self.design.ops[0].cgs_f)
                if upto:
                    vals["d2"] = nv["__load__"][0]
                else:
                    vals["out"] = nv["__load__"][0]
                fh.write(f'"freq" {fi:.15e}\n')
                for k, v in vals.items():
                    fh.write(f'"{k}" ({v.real:.15e} {v.imag:.15e})\n')
        (self._p(cwd) / "spectre.log").write_text("fake spectre ok\n")
        return _R()


def test_netlist_is_well_formed():
    d = _design()
    for upto in (None, "stage2"):
        text, rl = BC.render_netlist(d, np.array([27e9, 30e9]), upto=upto,
                                     nominal_load=T.NOMINAL_STAGE2_LOAD if upto else None)
        names = [ln.split()[0] for ln in text.splitlines() if ln and not ln.startswith(("//", "simulator", "global", "save"))]
        assert len(names) == len(set(names)), "instance names must be unique"
        assert "mutual_inductor" in text and "vccs" in text and "cccs" in text and "donoise=yes" in text
        assert ("PORT2 (out 0)" in text) == (upto is None)
        assert rl == (1787.0 if upto is None else 250.0)
        assert text.isascii()


def test_backend_roundtrip_matches_engine(tmp_path):
    d = _design()
    runner = FakeRunner(tmp_path / "remote", d)
    be = BC.CadenceBackend(runner=runner, local_root=tmp_path / "local")
    f = ck.sweep_grid(d.fc_hz, 0.2)
    got = be.simulate(d, f)
    ref = ck.simulate(d, f)
    for k in ("gain_db", "s11_db", "nf_db", "nfmin_db", "gain_to_g2_db", "gain_to_g3_db"):
        assert np.allclose(got[k], ref[k], atol=1e-6), k
    assert got["stage_gain_db_at_fc"] == pytest.approx(ref["stage_gain_db_at_fc"], abs=1e-6)
    assert got["compression"]["ip1db_dbm"] == pytest.approx(ref["compression"]["ip1db_dbm"], abs=0.05)
    crit = be.simulate(d, np.array([d.fc_hz]), upto="stage2", include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD)
    ref2 = ck.simulate(d, np.array([d.fc_hz]), upto="stage2", include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD)
    assert crit["nf_db"][0] == pytest.approx(ref2["nf_db"][0], abs=1e-6)
    assert (tmp_path / "local" / be.run_id / "sim00001" / "metrics.json").exists()
    assert runner.calls and runner.calls[0][0] == "spectre" and "psfascii" in runner.calls[0]


def test_hybrid_backend_routes_stage4_to_final(tmp_path):
    d = _design()
    runner = FakeRunner(tmp_path / "remote", d)
    final = BC.CadenceBackend(runner=runner, local_root=tmp_path / "local")
    ctx = T.ToolContext(SPECS["S2"], backend=BC.HybridBackend(T.SurrogateBackend(), final))
    fc = T.fullchain_evaluation(ctx, d)
    assert fc["evidence_source"] == "cadence_spectre_macromodel" and final.n_calls == 1
    assert fc["backend"] == final.name


# ---------------------------------------------------------------------------
# independent check: a small MNA 'Spectre' (tests/fakes/mna_spectre.py) that shares no
# code with the two-port engine; validated against real Spectre 25.1 PSF output.
# ---------------------------------------------------------------------------
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "tests" / "fakes"))
import mna_spectre  # noqa: E402
from orfadc.cadence.psfascii_reader import parse_complex_trace, parse_scalar_trace  # noqa: E402

REAL = ROOT / "tests" / "data" / "spectre_s2"


@pytest.mark.parametrize("tag", ["sim00001", "sim00002"])
def test_mna_reference_reproduces_real_spectre(tmp_path, tag):
    mna_spectre.run(REAL / tag / "netlist.scs", tmp_path)
    for fn, key in (("sp1.sp", "s11"), ("sp1.sp", "s21"), ("ac1.ac", "g2"), ("ac1.ac", "d1"), ("ac1.ac", "in")):
        fa, a = parse_complex_trace(REAL / tag / fn, key)
        fb, b = parse_complex_trace(tmp_path / fn, key)
        assert np.allclose(fa, fb) and np.allclose(a, b, rtol=1e-9, atol=1e-12), (tag, key)
    if (REAL / tag / "sp1.noise.sp").exists():
        for key in ("NF", "NFmin"):
            a = parse_scalar_trace(REAL / tag / "sp1.noise.sp", key, require_each_sweep=True)[1]
            b = parse_scalar_trace(tmp_path / "sp1.noise.sp", key, require_each_sweep=True)[1]
            assert np.allclose(a, b, atol=1e-6), key


class MNARunner(FakeRunner):
    def run_remote(self, argv, cwd=None, timeout_seconds=None):
        self.calls.append(argv)
        mna_spectre.run(self._p(cwd) / "netlist.scs", self._p(cwd) / "psf")
        (self._p(cwd) / "spectre.log").write_text("mna reference ok\n")
        return _R()


def test_netlist_translation_matches_engine_via_independent_solver(tmp_path):
    """Gain/S11/NF/NFmin/node gains of the rendered netlist == engine (the band grid repeats its edges)."""
    d = _design()
    be = BC.CadenceBackend(runner=MNARunner(tmp_path / "remote", d), local_root=tmp_path / "local")
    f = ck.sweep_grid(d.fc_hz, 0.2)
    assert len({BC._g(x) for x in f}) < len(f)  # band edges appear twice, as on the real S2 run
    got, ref = be.simulate(d, f), ck.simulate(d, f)
    assert np.array_equal(got["f_hz"], f)
    for k in ("gain_db", "nf_db", "nfmin_db", "gain_to_g2_db", "gain_to_g3_db"):
        assert np.allclose(got[k], ref[k], atol=1e-6), k
    assert np.allclose(got["s11_db"], ref["s11_db"], atol=1e-4)
    assert got["compression"]["ip1db_dbm"] == pytest.approx(ref["compression"]["ip1db_dbm"], abs=0.5)
    kw = dict(upto="stage2", include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD)
    c, r = be.simulate(d, np.array([d.fc_hz]), **kw), ck.simulate(d, np.array([d.fc_hz]), **kw)
    for k in ("gain_db", "nf_db", "nfmin_db"):
        assert c[k][0] == pytest.approx(r[k][0], abs=1e-6), k


def test_physical_cdb_option_changes_only_stage1_topology(tmp_path):
    d = _design()
    a, _ = BC.render_netlist(d, np.array([30e9]))
    b, _ = BC.render_netlist(d, np.array([30e9]), physical_cdb=True)
    diff = [(x, y) for x, y in zip(a.splitlines(), b.splitlines()) if x != y]
    assert len(diff) == 1 and "(cas s1)" in diff[0][0] and "(cas 0)" in diff[0][1]
