"""docs/130 N1 tooling offline: run_job_queue.sh (bash twin of the Windows queue runner) and the
configurable roots / cds.lib files / Cadence prefixes of pdk_inventory.sh."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from orfadc.repro import pdk_v2 as P

ROOT = Path(__file__).resolve().parents[1]
QUEUE_SH = ROOT / "scripts" / "run_job_queue.sh"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="needs a POSIX bash")


def _exe(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ---------------------------------------------------------------------------
# run_job_queue.sh
# ---------------------------------------------------------------------------
FAKE_PY = """#!/bin/bash
# stands in for python: prints its argv and the variables the queue runner controls
echo "ARGV $*"
echo "LLM=${ORFADC_LLM_MAX_CALLS:-unset} SPECTRE=${ORFADC_SPECTRE_MAX_PER_DESIGN:-unset}"
echo "ANTHROPIC=${ANTHROPIC_API_KEY:-unset} PYTHONPATH=$PYTHONPATH"
case "$*" in *"--spec S9s"*) exit 3;; esac
exit 0
"""


@needs_bash
def test_job_queue_sh_runs_bench_lines_with_env_and_logs(tmp_path):
    fake = _exe(tmp_path / "fakepy", FAKE_PY)
    queue = tmp_path / "q.txt"
    queue.write_bytes(b"# comment\r\n\r\nset ORFADC_LLM_MAX_CALLS=1000\r\n"
                      b"design --spec S2 --seed 0 --policy rule\n"
                      b"set ORFADC_SPECTRE_MAX_PER_DESIGN=20\n"
                      b"   design --spec S9s --seed 1 --policy codex-mcp   \n"
                      b"Python -c print(1)\n"
                      b"set PATH=/evil\n"
                      b"llm-table --inputs a* b?")
    env = {**os.environ, "ORFADC_QUEUE_PYTHON": str(fake), "ORFADC_QUEUE_OUT_ROOT": str(tmp_path / "out"),
           "ANTHROPIC_API_KEY": "should-be-dropped"}
    env.pop("ORFADC_LLM_MAX_CALLS", None)
    env.pop("ORFADC_SPECTRE_MAX_PER_DESIGN", None)
    r = subprocess.run([BASH, str(QUEUE_SH), str(queue)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    (job,) = list((tmp_path / "out").iterdir())
    assert job.name.endswith("_job") and (job / "DONE.txt").exists()
    assert (job / "queue.txt").read_bytes() == queue.read_bytes()
    progress = (job / "progress.txt").read_text()
    assert "SET ORFADC_LLM_MAX_CALLS=1000" in progress and "SET ORFADC_SPECTRE_MAX_PER_DESIGN=20" in progress
    assert "END   01_design exit=0" in progress and "END   02_design exit=3" in progress   # failure logged, queue goes on
    assert "SKIP (not a bench subcommand): Python -c print(1)" in progress
    assert "SET PATH" not in progress and "QUEUE DONE" in progress   # only ORFADC_* is exported (as in the .ps1)
    log1, log2 = (job / "01_design.log").read_text(), (job / "02_design.log").read_text()
    assert f"ARGV -m orfadc.repro.bench design --spec S2 --seed 0 --policy rule --out {job}" in log1
    assert "LLM=1000 SPECTRE=unset" in log1 and "LLM=1000 SPECTRE=20" in log2
    assert "ANTHROPIC=unset" in log1 and f"PYTHONPATH={ROOT / 'src'}" in log1
    log5 = (job / "05_llm-table.log").read_text()                  # no glob expansion of queue arguments
    assert f"ARGV -m orfadc.repro.bench llm-table --inputs a* b? --out {job}" in log5
    assert not (job / "03_Python.log").exists()


@needs_bash
def test_job_queue_sh_resolves_queue_relative_to_scripts_and_rejects_missing(tmp_path):
    fake = _exe(tmp_path / "fakepy", FAKE_PY)
    env = {**os.environ, "ORFADC_QUEUE_PYTHON": str(fake), "ORFADC_QUEUE_OUT_ROOT": str(tmp_path / "out")}
    r = subprocess.run([BASH, str(QUEUE_SH), "jobs/no_such_queue.txt"], env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "queue not found" in r.stderr and not (tmp_path / "out").exists()
    r = subprocess.run([BASH, str(QUEUE_SH), "jobs/queue_pdk_s7.txt"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    (job,) = list((tmp_path / "out").iterdir())
    assert "ARGV -m orfadc.repro.bench design --spec S7 --seed 1 --policy rule --backend pdk" in (job / "01_design.log").read_text()


def test_job_queue_sh_matches_ps1_queue_grammar():
    """The two runners must accept the same lines: same `set` pattern and the same subcommand check."""
    sh, ps1 = QUEUE_SH.read_text(), (ROOT / "scripts" / "run_job_queue.ps1").read_text()
    assert "(ORFADC_[A-Z0-9_]+)=" in sh and "(ORFADC_[A-Z0-9_]+)=" in ps1
    assert "^[a-z0-9-]+$" in sh and "^[a-z0-9-]+$" in ps1
    assert "results/windows_checks" in sh and "results\\windows_checks" in ps1


# ---------------------------------------------------------------------------
# pdk_inventory.sh
# ---------------------------------------------------------------------------
def test_inventory_env_maps_and_validates():
    assert P.inventory_env(None) == {} and P.inventory_env({}) == {}
    env = P.inventory_env({"extra_roots": ["/home/IC/Desktop/tsmc"], "pdk_roots": "/home/IC",
                           "cdslib_files": ["/home/IC/cds.lib", "/home/IC/b/cds.lib"], "cds_prefixes": [],
                           "skip_home": False})
    assert env == {"PDK_EXTRA_ROOTS": "/home/IC/Desktop/tsmc", "ORFADC_PDK_ROOTS": "/home/IC",
                   "ORFADC_CDSLIB_FILES": "/home/IC/cds.lib /home/IC/b/cds.lib", "ORFADC_INV_SKIP_HOME": "0"}
    for bad in ({"extra_roots": ["relative/dir"]}, {"extra_roots": ["/a b"]}, {"pdk_roots": ["/x;rm -rf /"]},
                {"pdk_roots": ["/a/../b"]}, {"skip_home": "no"}, {"unknown": ["/a"]}):
        with pytest.raises(ValueError):
            P.inventory_env(bad)


class _FakeRunner:
    class config:  # noqa: N801
        remote_root = "/tmp/orfadc"

    def __init__(self):
        self.shell = []

    def ensure_remote_dir(self, d):
        return subprocess.CompletedProcess([], 0)

    def upload(self, src, dst):
        return subprocess.CompletedProcess([], 0)

    def run_shell(self, cmd, cwd=None, timeout_seconds=None):
        self.shell.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "##ROOTS\t/a /b\n##DONE\tok\n", "stderr": ""})()


def test_run_inventory_passes_env_prefix(tmp_path):
    fr = _FakeRunner()
    inv = P.run_inventory(fr, out_root=tmp_path)
    assert fr.shell == ["bash pdk_inventory.sh"] and inv["complete"] and inv["roots"] == ["/a", "/b"]
    P.run_inventory(fr, out_root=tmp_path, env={"PDK_EXTRA_ROOTS": "/home/IC/Desktop/tsmc", "ORFADC_INV_SKIP_HOME": "0"})
    assert fr.shell[-1] == "ORFADC_INV_SKIP_HOME=0 PDK_EXTRA_ROOTS=/home/IC/Desktop/tsmc bash pdk_inventory.sh"


@needs_bash
def test_inventory_script_finds_n65_like_tree_with_configured_roots(tmp_path):
    """Fake CentOS layout: PDK under another user's home (/home/IC/...), Cadence install with its own cds.lib."""
    pdk = tmp_path / "home" / "IC" / "Desktop" / "tsmc" / "crn65lp"
    (pdk / "models" / "spectre").mkdir(parents=True)
    (pdk / "models" / "spectre" / "toplevel.scs").write_text(
        "library crn65lp\nsection top_tt\ninline subckt nmos_rf ( d g s b )\nendsection top_tt\n")
    (pdk / "tsmcN65").mkdir()
    cad = tmp_path / "cad" / "IC618"
    (cad / "analogLib").mkdir(parents=True)
    home = tmp_path / "home" / "userone"
    (home / "work" / "mylib").mkdir(parents=True)
    (home / "cds.lib").write_text(f"DEFINE mylib {home / 'work' / 'mylib'}\n")
    ic_cdslib = tmp_path / "home" / "IC" / "cds.lib"
    ic_cdslib.write_text(f"DEFINE tsmcN65 {pdk / 'tsmcN65'}\nDEFINE analogLib {cad / 'analogLib'}\n")
    shims = tmp_path / "shims"
    shims.mkdir()
    if shutil.which("timeout") is None:              # macOS has no GNU timeout
        _exe(shims / "timeout", '#!/bin/bash\nshift\nexec "$@"\n')
    env = {**os.environ, "HOME": str(home), "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
           "ORFADC_PDK_ROOTS": str(tmp_path / "home" / "IC"), "PDK_EXTRA_ROOTS": str(tmp_path / "nowhere"),
           "ORFADC_CDSLIB_FILES": str(ic_cdslib), "ORFADC_CDS_PREFIXES": str(cad)}
    for k in ("CDSHOME", "CDS_INST_DIR", "PDK_HOME", "PDK_ROOT", "PDKPATH", "CDS_LIC_FILE"):
        env.pop(k, None)

    def run(**extra):
        r = subprocess.run([BASH, str(P.SCRIPT)], env={**env, **extra}, capture_output=True, text=True, timeout=120)
        return P.parse_inventory(r.stdout)

    inv = run()
    assert inv["complete"] and inv["roots"] == [str(tmp_path / "home" / "IC"), str(tmp_path / "nowhere")]
    assert inv["cds_prefixes"] == [str(cad)]
    scs = str(pdk / "models" / "spectre" / "toplevel.scs")
    hits = [c for c in inv["nmos_candidates"] if c["file"] == scs and c["model"] == "nmos_rf"]
    assert len(hits) == 1 and "top_tt" in hits[0]["sections"]
    assert str(ic_cdslib) in inv["cds_libs"] and str(home / "cds.lib") in inv["cds_libs"]
    assert inv["lib_dirs"] == [str(pdk / "tsmcN65")]          # Cadence's own libs and $HOME libs are skipped
    assert str(home / "work" / "mylib") in run(ORFADC_INV_SKIP_HOME="0")["lib_dirs"]
