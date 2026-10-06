"""Reproduction harness: Table IV/V-like tables and Fig. 5/7/8/10-like plots.

    python -m orfadc.repro.bench all   --seeds 5 --out results/repro/latest
    python -m orfadc.repro.bench table4 --seeds 5
    python -m orfadc.repro.bench table5 --seeds 5
    python -m orfadc.repro.bench fig5 | fig7 | fig10 | smoke

Table/figure commands run on the surrogate backend (no Cadence, no network) and are
deterministic under the seed; their numbers are *trend-level* evidence, not silicon or
PDK results (every artefact carries that label).  Other subcommands (see ``--help``):
design (``--backend surrogate|cadence|pdk``), replot, llm-check, llm-table, llm-seeds,
cadence-check and pdk-inventory|pdk-config|pdk-refit|pdk-characterize|pdk-characterize3|pdk-characterize-casc|pdk-check
(the last two groups reach the Cadence VM and need an explicit user request).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import math
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orfadc.config_loader import load_specs  # noqa: E402
from orfadc.repro import agents as A  # noqa: E402
from orfadc.repro import baselines as B  # noqa: E402
from orfadc.repro import circuit as ck  # noqa: E402
from orfadc.repro import tools as T  # noqa: E402
from orfadc.schemas import Spec  # noqa: E402

ROOT = SRC.parent
LABEL = "surrogate backend (open EKV-class model); trend-level, not PDK/silicon"
METHODS_T4 = ["ga_vanilla", "bo_vanilla", "ga_subtool", "bo_subtool", "ours"]


def specs() -> dict[str, Spec]:
    return {s.id: s for s in load_specs(ROOT / "config" / "specs_table_iii.yaml")}


def _rel(p: Path) -> str:
    """Repo-relative path for evidence pointers written into result JSON (no machine-specific prefixes)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def budget_for(spec_id: str) -> float:
    base = 18000.0 if spec_id.startswith(("S9", "S10")) else 3600.0
    return base * float(os.environ.get("ORFADC_BUDGET_SCALE", "1"))   # >1 only for explicit budget studies (docs/126)


# ---------------------------------------------------------------------------
# result labels and design-file naming (docs/130 A1: runs with different settings never share a file name)
# ---------------------------------------------------------------------------

AGENT_IMPLS = ("v1", "v2")
LLM_MAX_CALLS_DEFAULT = 200


def agent_impl(value: str | None = None) -> str:
    """Agent implementation: explicit value, else ORFADC_AGENT_IMPL, else v1."""
    v = (value or os.environ.get("ORFADC_AGENT_IMPL") or "v1").strip().lower()
    if v not in AGENT_IMPLS:
        raise ValueError(f"agent implementation must be one of {AGENT_IMPLS}, got {v!r}")
    return v


def spectre_calls_of(backend) -> int | None:
    """Spectre runs made by a hybrid backend's final (Stage-4) simulator; None for the surrogate."""
    n = getattr(getattr(backend, "final", None), "n_calls", None)
    return int(n) if isinstance(n, int) else None


def pdk_label(cfg: dict | None) -> str:
    """Short PDK label from the local PDK config's ``name``.  A config without a name is the v1 crn40lp setup."""
    name = str((cfg or {}).get("name") or "").strip().lower()
    if not name or "40" in name:
        return "crn40lp"
    if "65" in name:
        return "crn65lp"
    return re.sub(r"[^a-z0-9]+", "", name) or "pdk"


_PDK_FILE_TAG = {"crn40lp": "", "crn65lp": "n65"}   # crn40lp keeps the v1 file names


def design_suffix(*, backend: str, impl: str = "v1", pdk: str | None = None, llm: bool = False,
                  env: dict | None = None) -> str:
    """Stable file-name suffix after ``design_<spec>_seed<n>_mode<m>_<policy>``; empty for the default settings.

    Order: backend[_pdk-tag], v2, passive Q, budget scale, LLM call cap (LLM policies only),
    Spectre cap (Spectre backends only), stage-2 back-off, report-best (vs the backend's default)."""
    env = os.environ if env is None else env
    s = ""
    if backend != "surrogate":
        s += f"_{backend}"
        if backend == "pdk":
            tag = _PDK_FILE_TAG.get(pdk or "crn40lp", pdk)
            s += f"_{tag}" if tag else ""
    if impl != "v1":
        s += f"_{impl}"
    if ck.Q_MATCH != 25.0 or ck.Q_IND != 15.0:                       # passive-Q study runs (docs/126)
        s += f"_qm{ck.Q_MATCH:g}_qi{ck.Q_IND:g}"
    if float(env.get("ORFADC_BUDGET_SCALE", "1")) != 1.0:
        s += f"_b{float(env['ORFADC_BUDGET_SCALE']):g}x"
    calls = int(env.get("ORFADC_LLM_MAX_CALLS") or LLM_MAX_CALLS_DEFAULT)
    if llm and calls != LLM_MAX_CALLS_DEFAULT:
        s += f"_calls{calls}"
    smax = int(env.get("ORFADC_SPECTRE_MAX_PER_DESIGN") or 0)
    if backend != "surrogate" and smax > 0:
        s += f"_smax{smax}"
    if env.get("ORFADC_STAGE2_BACKOFF", "0") == "1":
        s += "_backoff"
    rb_default = "1" if backend == "pdk" else "0"
    rb = env.get("ORFADC_REPORT_BEST", rb_default)
    if rb != rb_default:
        s += f"_rb{rb}"
    return s


def default_memory_dir(impl: str = "v1", pdk: str | None = None) -> Path:
    """KB/EB directory per agent implementation and process; v1 without N65 keeps the v1 location."""
    tag = _PDK_FILE_TAG.get(pdk or "crn40lp", pdk)
    return ROOT / "results" / "memory" / ("repro" + ("" if impl == "v1" else f"_{impl}") + (f"_{tag}" if tag else ""))


DESIGN_FILE_RE =re.compile(r"design_(S\w+?)_seed(\d+)_mode(\d+)_([a-z-]+)((?:_[A-Za-z0-9.]+)*)\.json$")


def parse_design_name(name: str) -> dict | None:
    """Inverse of the design file naming: spec, seed, mode, policy and the settings suffix ('' = default)."""
    m = DESIGN_FILE_RE.match(name)
    if not m:
        return None
    return {"spec": m.group(1), "seed": int(m.group(2)), "mode": int(m.group(3)), "policy": m.group(4),
            "suffix": m.group(5).lstrip("_")}


def scaled_hard_specs() -> dict[str, Spec]:
    """S9/S10 shifted to the surrogate's linearity frontier.

    A 20 000-evaluation GA on the surrogate reaches IP1dB ~ -19.7 dBm at NF 5 dB and ~ -21.9 dBm at
    NF 3.6 dB (25 dB gain, 30 mA), so the paper's -15 dBm targets are infeasible for this device model.
    S9s/S10s keep the tasks' role (hardest linearity) at the same distance from the frontier."""
    return {"S9s": Spec(id="S9s", fc_ghz=30, fbw_ratio=0.2, power_ma=30, gain_db=25, nf_max_db=5.0, ip1db_min_dbm=-20.0),
            "S10s": Spec(id="S10s", fc_ghz=30, fbw_ratio=0.2, power_ma=30, gain_db=25, nf_max_db=4.0, ip1db_min_dbm=-21.0)}


# ---------------------------------------------------------------------------
# single run dispatch (picklable)
# ---------------------------------------------------------------------------

def run_one(job: tuple) -> dict:
    method, spec, seed, budget, extra = job
    t = time.perf_counter()
    if method.startswith("ours"):
        from orfadc.repro.llm import make_policy
        mode = 2 if "eb" in method else 1
        policy = make_policy(extra.get("policy", "rule"))
        out = A.run_design(spec, seed, mode=mode, budget_equiv_s=budget,
                           use_refiner="no_refiner" not in method, policy=policy,
                           memory_dir=Path(extra["memory_dir"]) if extra.get("memory_dir") else None)
        out.pop("_session", None)
        out["method"] = method
        if hasattr(policy, "usage"):
            out["llm_usage"] = policy.usage.__dict__
        rep = out.get("report") or {}
        out["metrics"] = rep.get("metrics")
        out["violations"] = rep.get("violations")
        out.pop("trace", None) if not extra.get("keep_trace") else None
    else:
        out = B.run_baseline(method, spec, seed, budget)
    out["wall_s"] = round(time.perf_counter() - t, 2)
    out["label"] = LABEL
    return out


def run_jobs(jobs: list[tuple], workers: int) -> list[dict]:
    if workers <= 1:
        return [run_one(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(run_one, jobs))


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

def summarize(rows: list[dict], methods: list[str], spec_ids: list[str]) -> list[dict]:
    table = []
    for sid in spec_ids:
        rec = {"spec": sid}
        for m in methods:
            rs = [r for r in rows if r["spec"] == sid and r["method"] == m]
            ok = [r for r in rs if r["success"]]
            rec[f"{m}.pass"] = f"{len(ok)}/{len(rs)}"
            rec[f"{m}.time_s"] = round(float(np.mean([r["sims"]["equiv_time_s"] for r in ok])), 0) if ok else None
            rec[f"{m}.sims"] = round(float(np.mean([r["sims"]["hf_total"] for r in ok])), 0) if ok else None
            viol = [sum(v / B.NORM[k] for k, v in r["violations"].items()) for r in rs if r.get("violations")]
            rec[f"{m}.viol"] = round(float(np.mean(viol)), 3) if viol else None
        table.append(rec)
    return table


def write_table(path: Path, table: list[dict], methods: list[str], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    lines = [f"# {title}", "", f"> {LABEL}. pass@1 over seeds; time = mean equivalent EDA seconds of successful runs "
             f"(cost model {T.EQUIV_COST_S}); '-' = no success within budget.", "",
             "`viol` = mean normalised residual violation of the best design per run (0 = pass; "
             "gain/ripple/IP1dB/S11/power per 3 dB, NF per 1 dB).", "",
             "| Spec | " + " | ".join(f"{m} pass@1 | {m} time(s) | {m} viol" for m in methods) + " |",
             "|---|" + "---|---|---|" * len(methods)]
    for rec in table:
        cells = []
        for m in methods:
            cells += [rec[f"{m}.pass"], "-" if rec[f"{m}.time_s"] is None else f"{rec[f'{m}.time_s']:.0f}",
                      "-" if rec.get(f"{m}.viol") is None else f"{rec[f'{m}.viol']:.2f}"]
        lines.append(f"| {rec['spec']} | " + " | ".join(cells) + " |")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def dump(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            r = {k: v for k, v in r.items() if k not in ("history",)}
            fh.write(json.dumps(r, default=float) + "\n")


def cmd_table4(out: Path, seeds: int, workers: int, spec_ids: list[str] | None = None,
               methods: list[str] | None = None) -> list[dict]:
    sp = specs()
    spec_ids = spec_ids or [f"S{i}" for i in range(1, 9)]
    methods = methods or METHODS_T4
    jobs = [(m, sp[s], seed, budget_for(s), {}) for s in spec_ids for m in methods for seed in range(seeds)]
    rows = run_jobs(jobs, workers)
    dump(out / "raw" / "table4_runs.jsonl", rows)
    write_table(out / "tables" / "table4_like", summarize(rows, methods, spec_ids), methods,
                "Table IV-like: first 8 tasks (1 h equivalent budget)")
    return rows


def cmd_table5(out: Path, seeds: int, workers: int, pretrain_rows: list[dict] | None = None) -> list[dict]:
    sp = specs()
    mem = out / "memory_table5"
    if mem.exists():
        shutil.rmtree(mem)
    # EB/KB pre-training: Mode-1 runs on S1..S8 populate the memory (self-evolution)
    for sid in [f"S{i}" for i in range(1, 9)]:
        A.run_design(sp[sid], 100, mode=1, memory_dir=mem, budget_equiv_s=3600.0)
    methods = ["ga_subtool", "bo_subtool", "ours", "ours_no_refiner", "ours_with_eb"]
    sp.update(scaled_hard_specs())
    jobs = []
    for s in ("S9", "S10", "S9s", "S10s"):
        for m in methods:
            for seed in range(seeds):
                extra = {}
                if m == "ours_with_eb":
                    dst = out / f"memory_eb_{s}_{seed}"
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(mem, dst)
                    extra = {"memory_dir": str(dst)}
                jobs.append((m, sp[s], seed, budget_for(s), extra))
    rows = run_jobs(jobs, workers)
    dump(out / "raw" / "table5_runs.jsonl", rows)
    table = summarize(rows, methods, ["S9", "S10", "S9s", "S10s"])
    for rec in table:
        for m in methods:
            rs = [r for r in rows if r["spec"] == rec["spec"] and r["method"] == m and m.startswith("ours")]
            if rs:
                rec[f"{m}.search"] = round(float(np.mean([r["n_search"] for r in rs])), 2)
                rec[f"{m}.refine"] = round(float(np.mean([r["n_refine"] for r in rs])), 2)
    write_table(out / "tables" / "table5_like", table, methods,
                "Table V-like: S9/S10 (+ surrogate-scaled S9s/S10s) with 5 h budget, ablations (rule policy)")
    return rows


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def cmd_fig5(out: Path) -> dict:
    """Eq.-3 low-fidelity vs high-fidelity, calibration, and runtime (Fig. 5a/5b)."""
    sp = specs()["S2"]
    ctx = T.ToolContext(sp)
    cfg = T.active_sizing([0.4, 0.3, 0.3], sp.power_ma)["active_params_dict_list"][0]
    s2 = T.impedance_matching(ctx, cfg)
    res = {}
    t = time.perf_counter()
    c0 = ctx.counter.to_dict()
    mf = T.band_planning(ctx, cfg, s2, calibrate=True)
    res["multi_fidelity"] = {"cpu_s": time.perf_counter() - t, "rounds": mf["rounds"],
                             "hf_full": ctx.counter.hf_full - c0["hf_full"], "lf": ctx.counter.lf - c0["lf"]}
    ctx2 = T.ToolContext(sp)
    t = time.perf_counter()
    T.band_planning(ctx2, cfg, s2, simulation_based=True, sa_iters=500)   # cost is read from ctx2.counter
    res["simulation_based"] = {"cpu_s": time.perf_counter() - t, "hf_full": ctx2.counter.hf_full}
    eq_mf = res["multi_fidelity"]["hf_full"] * T.EQUIV_COST_S["hf_full"] + res["multi_fidelity"]["lf"] * T.EQUIV_COST_S["lf"]
    eq_sb = res["simulation_based"]["hf_full"] * T.EQUIV_COST_S["hf_full"]
    res["equiv_time_s"] = {"multi_fidelity": eq_mf, "simulation_based": eq_sb,
                           "reduction_pct": 100 * (1 - eq_mf / eq_sb)}
    # LF vs HF at the first (uncalibrated) round and after calibration
    ctx3 = T.ToolContext(sp)
    un = T.band_planning(ctx3, cfg, s2, calibrate=False)
    # variant accuracy study on random MCR points
    rng = np.random.default_rng(0)
    ops, cur = T.ops_from_active(cfg)
    par2 = ck.node_parasitics(ops[1], ops[2], None)
    par3 = ck.node_parasitics(ops[2], None, ck.DEFAULT_LOAD)
    lb, ub = T._stage3_bounds(sp, par2, par3)
    from orfadc.repro.mcr_eq3 import eq3_voltage
    acc = {}
    for var, half in (("printed", True), ("corrected", True), ("corrected", False)):
        errs = []
        for _ in range(60):
            x = lb + rng.random(8) * (ub - lb)
            d = T._full_design(ops, cur, s2["passive_params_cpstages"], x, ctx.fc_hz)
            hf = ck.simulate(d, np.array([ctx.fc_hz]))["stage_gain_db_at_fc"]
            for i, (op, xs) in enumerate(((ops[1], x[0:4]), (ops[2], x[4:8]))):
                ro = 1 / op.gds_s
                lf = eq3_voltage(np.array([ctx.fc_hz]), k=xs[0], w0=2 * math.pi * xs[1] * 1e9, q0=xs[2],
                                 c_f=xs[3] * 1e-15, gm50_s=op.gm_s * ro / (ro + 50), rs_drv_ohm=ro,
                                 cs_drv_f=op.cdb_f + 0.12 * op.cgd_f, variant=var, half=half)["gain_db"][0]
                errs.append(lf - hf[i + 1])
        e = np.array(errs)
        acc[f"{var}{'_half' if half else ''}"] = {"mean_err_db": float(e.mean()), "std_err_db": float(e.std()),
                                                 "rms_err_db": float(np.sqrt((e**2).mean()))}
    res["eq3_stage_gain_error_vs_hf"] = acc
    plt = _plt()
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    f = np.array(un["cal_gain_dict"]["f_ghz"])
    ax[0].plot(f, un["cal_gain_dict"]["gain_lf_db"], "k-", label="Eq.3 calculation")
    ax[0].plot(f, un["cal_gain_dict"]["gain_hf_db"], "r-", label="Sim w/o calibration")
    ax[0].plot(mf["cal_gain_dict"]["f_ghz"], mf["cal_gain_dict"]["gain_hf_db"], "b-", label="Sim with calibration")
    lo, hi = sp.band_edges_ghz
    ax[0].axvspan(lo, hi, color="g", alpha=0.15)
    ax[0].axhline(sp.gain_db, ls=":", c="gray")
    ax[0].set(xlabel="Frequency (GHz)", ylabel="Gain (dB)", title="Fig.5a-like (S2, surrogate)")
    ax[0].legend()
    ax[1].barh(["multi-fidelity", "simulation-based"], [eq_mf, eq_sb], color=["#4472c4", "#a5a5a5"])
    ax[1].set(xlabel="Equivalent EDA time (s)", title=f"Fig.5b-like: {res['equiv_time_s']['reduction_pct']:.0f}% reduction")
    fig.tight_layout()
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "figures" / "fig5_like.png", dpi=130)
    plt.close(fig)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "raw" / "fig5.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    return res


def cmd_fig7(out: Path, rows: list[dict]) -> None:
    plt = _plt()
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    for i, group in enumerate((["S1", "S2", "S3"], ["S4", "S5", "S6"])):
        for sid in group:
            r = next((r for r in rows if r["spec"] == sid and r["method"] == "ours" and r.get("sweep")), None)
            if not r:
                continue
            sw = r["sweep"]
            ax[i].plot(sw["f_ghz"], sw["gain_db"], label=f"{sid} S21{'' if r['success'] else ' (fail)'}")
            ax[i].plot(sw["f_ghz"], sw["s11_db"], "--", label=f"{sid} S11")
        ax[i].set(xlabel="Frequency (GHz)", ylabel="dB", ylim=(-35, 35), title=f"Fig.7{'ac'[i]}-like")
        ax[i].legend(fontsize=7)
    for sid in ("S1", "S2", "S3", "S7"):
        r = next((r for r in rows if r["spec"] == sid and r["method"] == "ours" and r.get("sweep")), None)
        if r:
            ax[2].plot(r["sweep"]["f_ghz"], r["sweep"]["nf_db"], label=f"{sid} NF")
            ax[2].plot(r["sweep"]["f_ghz"], r["sweep"]["nfmin_db"], ":", label=f"{sid} NFmin")
    ax[2].set(xlabel="Frequency (GHz)", ylabel="dB", ylim=(0, 10), title="Fig.7b-like")
    ax[2].legend(fontsize=7)
    fig.suptitle(LABEL, fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "figures" / "fig7_like.png", dpi=130)
    plt.close(fig)


def cmd_fig8(out: Path, rows: list[dict]) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7, 4))
    ms = METHODS_T4
    for j, m in enumerate(ms):
        ax.bar([], [], color=f"C{j}", label=m)
        for i, sid in enumerate(("S1", "S2", "S4")):
            ts = [r["sims"]["equiv_time_s"] for r in rows if r["spec"] == sid and r["method"] == m and r["success"]]
            if ts:
                mu = np.mean(ts)
                ax.bar(i + 0.16 * j, mu, 0.15, yerr=[[mu - min(ts)], [max(ts) - mu]], color=f"C{j}")
                ax.text(i + 0.16 * j, 20, f"{len(ts)}/5", ha="center", fontsize=6, color="white")
    ax.set_xticks(np.arange(3) + 0.32, ["S1", "S2", "S4"])
    ax.set(ylabel="Equivalent time (s)", title="Fig.8-like: mean completion time with min-max range")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "figures" / "fig8_like.png", dpi=130)
    plt.close(fig)


def cmd_fig10(out: Path, seeds: int = 3) -> dict:
    """Self-evolution: S4-style narrow-band tasks with gain 20 -> 45 dB."""
    base = specs()["S4"]
    gains = [20, 25, 30, 35, 40, 45]
    tasks = [Spec(id=f"G{g}", fc_ghz=base.fc_ghz, fbw_ratio=base.fbw_ratio, power_ma=base.power_ma,
                  gain_db=g, nf_max_db=base.nf_max_db, ip1db_min_dbm=-(g + 5.0)) for g in gains]  # OP1dB ~ -6 dBm
    res: dict = {"gains": gains, "tasks": [t.__dict__ for t in tasks]}
    for method in ("ours_eb", "ga_vanilla", "bo_vanilla"):
        per_seed = []
        for seed in range(seeds):
            mem = out / f"memory_fig10_{seed}"
            if mem.exists():
                shutil.rmtree(mem)
            costs = []
            for t in tasks:
                if method == "ours_eb":
                    r = A.run_design(t, seed, mode=2, memory_dir=mem, budget_equiv_s=3600.0)
                else:
                    r = B.run_baseline(method, t, seed, 3600.0)
                costs.append({"sims": r["sims"]["hf_total"], "equiv_s": r["sims"]["equiv_time_s"],
                              "success": r["success"]})
            per_seed.append(costs)
        res[method] = per_seed
    plt = _plt()
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for m, c in (("ours_eb", "C3"), ("ga_vanilla", "C7"), ("bo_vanilla", "C0")):
        arr = np.array([[x["equiv_s"] for x in s] for s in res[m]])
        cum = np.cumsum(arr, axis=1)
        ax[0].errorbar(np.arange(1, len(gains) + 1), cum.mean(0), yerr=cum.std(0), label=m, color=c, marker="o")
        ax[1].plot(np.arange(1, len(gains) + 1), arr.mean(0), label=m, color=c, marker="o")
    ax[0].set(yscale="log", xlabel="Task ID (gain 20..45 dB)", ylabel="Cumulative equivalent time (s)",
              title="Fig.10-like (left)")
    ax[1].set(yscale="log", xlabel="Task ID", ylabel="Per-task equivalent time (s)", title="Fig.10-like (right)")
    for a in ax:
        a.legend()
    fig.tight_layout()
    fig.savefig(out / "figures" / "fig10_like.png", dpi=130)
    plt.close(fig)
    (out / "raw" / "fig10.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    return res


def cmd_smoke(out: Path) -> dict:
    sp = specs()["S2"]
    r = A.run_design(sp, 0, budget_equiv_s=3600.0)
    r.pop("_session", None)
    out.mkdir(parents=True, exist_ok=True)
    (out / "smoke_S2.json").write_text(json.dumps({k: v for k, v in r.items() if k != "trace"}, indent=2,
                                                  default=float), encoding="utf-8")
    (out / "smoke_S2_trace.json").write_text(json.dumps(r["trace"], indent=1, default=float), encoding="utf-8")
    print(json.dumps({"spec": r["spec"], "success": r["success"], "sims": r["sims"],
                      "metrics": (r["report"] or {}).get("metrics")}, indent=2, default=float))
    return r


def _usage(r: dict) -> dict:
    u = dict(r.get("llm_usage") or {})
    if u and "rule_after_disable" not in u:  # runs before 2026-10-01 counted post-cap rule decisions as fallbacks
        from .llm import _valid_refine, _valid_split
        bad = sum(1 for e in r.get("llm_log") or [] if "error" not in e and not (
            _valid_refine(e.get("parsed")) if e.get("role") == "refiner" else
            isinstance(e.get("parsed"), dict) and (e["parsed"].get("stop") or _valid_split(e["parsed"].get("power_ratio_list")))))
        real = min(u.get("fallbacks", 0), bad + u.get("errors", 0))
        u["rule_after_disable"], u["fallbacks"] = u.get("fallbacks", 0) - real, real
    return u


def cmd_llm_table(out: Path) -> int:
    """Summarise every design_*.json in ``out`` (LLM / rule runs) into llm_table.{md,csv}."""
    rows = []
    for p in sorted(out.glob("design_*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        rep = r.get("report") or {}
        m, v = rep.get("metrics") or {}, rep.get("violations") or {}
        u = _usage(r)
        backend = r.get("backend") or "surrogate"
        n = parse_design_name(p.name)
        rows.append({
            "spec": r.get("spec"), "seed": r.get("seed"), "policy": r.get("policy"),
            "variant": n["suffix"] if n else p.stem, "backend": backend, "success": r.get("success"),
            "viol": round(sum(x / B.NORM[k] for k, x in v.items()), 3) if v else None,
            "bottleneck": rep.get("bottleneck"), "gain_min_db": m.get("gain_min_db"), "nf_db": m.get("nf_fc_db"),
            "ip1db_dbm": m.get("ip1db_dbm"), "hf_sims": (r.get("sims") or {}).get("hf_total"),
            "equiv_s": (r.get("sims") or {}).get("equiv_time_s"), "llm_calls": u.get("calls"),
            "llm_errors": u.get("errors"), "fallbacks": u.get("fallbacks"), "rule_after_cap": u.get("rule_after_disable"), "prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"), "llm_latency_s": round(u.get("latency_s", 0), 1) if u else None,
            "disabled": u.get("disabled_reason"), "file": p.name})
    if not rows:
        print(f"no design_*.json in {out}")
        return 1
    with (out / "llm_table.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    def f(x, nd=2):
        return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))
    lines = ["# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)", "",
             "fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the "
             "ORFADC_LLM_MAX_CALLS cap / circuit breaker.", "",
             "| spec | policy | variant | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        be = "spectre(stage4)" if "cadence" in r["backend"] else "surrogate"
        lines.append(f"| {r['spec']} | {r['policy']} | {r['variant'] or '-'} | {be} | {'Y' if r['success'] else 'N'} | {f(r['viol'])} | {f(r['ip1db_dbm'],1)} | "
                     f"{f(r['nf_db'])} | {f(r['gain_min_db'],1)} | {f(r['llm_calls'])} | {f(r['llm_errors'])} | {f(r['fallbacks'])} | "
                     f"{f(r['rule_after_cap'])} | {f(r['prompt_tokens'])} | {f(r['completion_tokens'])} | {f(r['llm_latency_s'],0)} | {f(r['bottleneck'])} |")
    (out / "llm_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def cmd_llm_seeds(out: Path, inputs: list[Path]) -> int:
    """Multi-seed summary (per spec x policy) of design_*_seed*_mode1_<policy>.json found in ``out`` and ``inputs``:
    pass@1 count, residual violation mean/median, LLM calls/tokens, fallbacks and rule-after-cap.  -> llm_seeds.{md,json}"""
    import statistics as st
    runs: dict = {}
    for d in [out, *inputs]:
        for p in sorted(Path(d).glob("design_*_seed*_mode1_*.json")):
            n = parse_design_name(p.name)
            if not n or n["mode"] != 1:
                print(f"skipped (unrecognised name): {p}")
                continue
            # the settings suffix (backend, v2, caps, ...) is part of the group key, never silently dropped
            pol = n["policy"] + (f"[{n['suffix']}]" if n["suffix"] else "")
            runs[(n["spec"], pol, n["seed"])] = json.loads(p.read_text(encoding="utf-8"))   # later folders win on duplicates
    if not runs:
        print("no runs")
        return 1
    groups: dict = {}
    for (spec, pol, seed), r in runs.items():
        rep = r.get("report") or {}
        v = rep.get("violations") or {}
        u = _usage(r)
        groups.setdefault((spec, pol), []).append({
            "seed": seed, "pass": bool(r.get("success")),
            "viol": sum(x / B.NORM[k] for k, x in v.items()) if v else float("nan"),
            "best_eval_viol": min((sum(x / B.NORM[k] for k, x in e["violations"].items()) for e in r.get("trace") or []
                                   if e.get("event") == "evaluate" and e.get("violations")), default=float("nan")),
            "calls": u.get("calls"), "tok": (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0) if u else None,
            "fallbacks": u.get("fallbacks"), "rule_after_cap": u.get("rule_after_disable"), "errors": u.get("errors"),
            "equiv_s": (r.get("sims") or {}).get("equiv_time_s")})
    order = {"rule": 0, "codex-mcp": 1, "claude-cli": 2}
    lines = ["# Multi-seed LLM backbone summary (trend-level, not silicon results)", "",
             "policy[suffix] = run settings from the file name (pdk = Spectre stage 4 with PDK transistors, n65 = TSMC N65, "
             "v2 = ReAct agents, calls1000 = LLM call cap, ...); no suffix = surrogate simulator, v1 agents, default settings.", "",
             "viol =normalised residual violation of the reported design (0 = all specs met; runs that reported no "
             "design are left out, see 'reported'); best-eval = least violation among all full-chain evaluations of the run; "
             "calls/tokens per run.", "",
             "| spec | policy | seeds | pass | reported | viol mean | viol median | best-eval mean | best-eval median | calls mean | tokens mean | fallbacks | rule-after-cap | errors | equiv s mean |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    summary = []
    for (spec, pol), rr in sorted(groups.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1].split("[")[0], 9), kv[0][1])):
        vs = [x["viol"] for x in rr if x["viol"] == x["viol"]]
        bs = [x["best_eval_viol"] for x in rr if x["best_eval_viol"] == x["best_eval_viol"]]
        def mean(k):
            xs = [x[k] for x in rr if x[k] is not None]
            return (sum(xs) / len(xs)) if xs else None
        def tot(k):
            xs = [x[k] for x in rr if x[k] is not None]
            return sum(xs) if xs else None
        row = {"spec": spec, "policy": pol, "seeds": sorted(x["seed"] for x in rr), "pass": sum(x["pass"] for x in rr),
               "reported": len(vs), "viol_mean": (sum(vs) / len(vs)) if vs else None,
               "viol_median": st.median(vs) if vs else None,
               "best_eval_mean": (sum(bs) / len(bs)) if bs else None, "best_eval_median": st.median(bs) if bs else None,
               "calls_mean": mean("calls"), "tokens_mean": mean("tok"), "fallbacks": tot("fallbacks"),
               "rule_after_cap": tot("rule_after_cap"), "errors": tot("errors"), "equiv_s_mean": mean("equiv_s")}
        summary.append(row)
        fm = lambda x, nd=3: "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))
        lines.append(f"| {spec} | {pol} | {len(rr)} | {row['pass']}/{len(rr)} | {row['reported']}/{len(rr)} | {fm(row['viol_mean'])} | "
                     f"{fm(row['viol_median'])} | {fm(row['best_eval_mean'])} | {fm(row['best_eval_median'])} | "
                     f"{fm(row['calls_mean'], 1)} | {fm(row['tokens_mean'], 0)} | {fm(row['fallbacks'])} | {fm(row['rule_after_cap'])} | "
                     f"{fm(row['errors'])} | {fm(row['equiv_s_mean'], 0)} |")
    (out / "llm_seeds.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "llm_seeds.json").write_text(json.dumps({"summary": summary, "runs": {f"{k[0]}|{k[1]}": g for k, g in groups.items()}}, indent=1, default=float), encoding="utf-8")
    print("\n".join(lines))
    return 0


def cmd_cadence_check(out: Path, spec_id: str = "S2", seed: int = 0) -> int:
    """Cross-check the Python two-port engine against Spectre on one agent-designed LNA:
    SSH/Spectre probe -> critical-stage run -> full-chain sweep -> metric deltas."""
    from orfadc.repro.backend_cadence import CadenceBackend
    rep: dict = {"spec": spec_id, "seed": seed}
    t0 = time.perf_counter()
    cad = CadenceBackend()
    rep["probe"] = cad.probe()
    rep["remote_dir"] = cad.remote_root
    r = A.run_design(specs()[spec_id], seed, budget_equiv_s=budget_for(spec_id))
    sess = r.pop("_session")
    did = (r.get("report") or {}).get("did")
    design = sess.designs[did]["design"]
    rep["surrogate_design_pass"] = r["success"]
    fc = design.fc_hz
    sp = specs()[spec_id]
    rows = {}
    f_band = ck.sweep_grid(fc, sp.fbw_ratio)
    cases = {"critical_fc": dict(f=np.array([fc]), kw=dict(upto="stage2", include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD)),
             "fullchain": dict(f=f_band, kw={})}
    for name, c in cases.items():
        eng = ck.simulate(design, c["f"], **c["kw"])
        spc = cad.simulate(design, c["f"], **c["kw"])
        d = {k: float(np.max(np.abs(np.asarray(spc[k]) - np.asarray(eng[k])))) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")}
        d["ip1db_dbm"] = abs(spc["compression"]["ip1db_dbm"] - eng["compression"]["ip1db_dbm"])
        rows[name] = {"max_abs_delta": d,
                      "spectre_at_fc": {k: float(np.asarray(spc[k])[int(np.argmin(np.abs(c['f'] - fc)))]) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
                      "engine_at_fc": {k: float(np.asarray(eng[k])[int(np.argmin(np.abs(c['f'] - fc)))]) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
                      "ip1db": {"spectre": spc["compression"]["ip1db_dbm"], "engine": eng["compression"]["ip1db_dbm"]}}
        if name == "fullchain":
            rows[name]["spectre_band_metrics"] = ck.band_metrics(spc, fc, sp.fbw_ratio)
    rep["cases"] = rows
    # Model sensitivity (informational, not part of `agree`): stage-1 Cdb tied to ground as a real
    # drain-bulk junction, instead of drain->source as the engine's Ls-in-common-terminal form implies.
    cad.physical_cdb = True
    phys = cad.simulate(design, f_band)
    eng = ck.simulate(design, f_band)
    i_fc = int(np.argmin(np.abs(f_band - fc)))
    rep["sensitivity_physical_cdb"] = {
        "max_abs_delta": {k: float(np.max(np.abs(np.asarray(phys[k]) - np.asarray(eng[k])))) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
        "spectre_at_fc": {k: float(np.asarray(phys[k])[i_fc]) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
        "ip1db_dbm": phys["compression"]["ip1db_dbm"],
        "spectre_band_metrics": ck.band_metrics(phys, fc, sp.fbw_ratio)}
    cad.physical_cdb = False
    tol = {"gain_db": 0.2, "s11_db": 1.0, "nf_db": 0.2, "nfmin_db": 0.3, "ip1db_dbm": 0.5}
    rep["tolerance"] = tol
    rep["agree"] = all(rows[c]["max_abs_delta"][k] <= tol[k] for c in rows for k in tol)
    rep["spectre_calls"], rep["spectre_wall_s"] = cad.n_calls, round(cad.wall_s, 1)
    rep["local_evidence"] = _rel(cad.local_root / cad.run_id)
    rep["wall_s"] = round(time.perf_counter() - t0, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"cadence_check_{spec_id}.json").write_text(json.dumps(rep, indent=2, default=float), encoding="utf-8")
    print(json.dumps(rep, indent=2, default=float))
    return 0 if rep["agree"] else 5


PDK_HB_PINS = [round(-50 + 2.5 * i, 2) for i in range(19)]   # -50 .. -5 dBm


def cmd_pdk_check(out: Path, spec_id: str = "S2", seed: int = 0) -> int:
    """V2-4/V2-5: design S2 with the engine running on the PDK device table, then simulate the same design in
    Spectre with PDK RF transistors (critical stage + full chain with an HB power sweep) and report deltas."""
    from orfadc.repro import device as D, pdk_v2
    t0 = time.perf_counter()
    tab = pdk_v2.install_table()
    rep: dict = {"spec": spec_id, "seed": seed, "device_source": D.device_source(), "table_widths": getattr(getattr(tab, "full", tab), "widths", np.array([])).tolist(),
                 "cascode_ratio": getattr(tab, "cascode_ratio", None)}
    try:
        r = A.run_design(specs()[spec_id], seed, budget_equiv_s=budget_for(spec_id))
        sess = r.pop("_session")
        rep["engine_design_pass"] = r["success"]
        rep["engine_report"] = r.get("report")
        did = (r.get("report") or {}).get("did")
        if did is None:
            rep["error"] = "no design produced"
            print(json.dumps(rep, indent=2, default=float))
            return 8
        design = sess.designs[did]["design"]
        rep["design"] = design.summary()
        cad = pdk_v2.PdkCadenceBackend(hb_pins=PDK_HB_PINS)
        sp = specs()[spec_id]
        fc = design.fc_hz
        f_band = ck.sweep_grid(fc, sp.fbw_ratio)
        cases = {"critical_fc": dict(f=np.array([fc]), kw=dict(upto="stage2", include_match=True, nominal_load=T.NOMINAL_STAGE2_LOAD)),
                 "fullchain": dict(f=f_band, kw={})}
        rows = {}
        for name, c in cases.items():
            eng = ck.simulate(design, c["f"], **c["kw"])
            spc = cad.simulate(design, c["f"], **c["kw"])
            i = int(np.argmin(np.abs(c["f"] - fc)))
            rows[name] = {
                "max_abs_delta": {k: float(np.max(np.abs(np.asarray(spc[k]) - np.asarray(eng[k])))) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
                "spectre_at_fc": {k: float(np.asarray(spc[k])[i]) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
                "engine_at_fc": {k: float(np.asarray(eng[k])[i]) for k in ("gain_db", "s11_db", "nf_db", "nfmin_db")},
                "ip1db": {"spectre": spc["compression"]["ip1db_dbm"], "spectre_source": spc["compression"].get("source", "estimate"),
                          "spectre_estimate": spc["compression"].get("estimate_ip1db_dbm"), "engine": eng["compression"]["ip1db_dbm"]},
                "supply_ma_half_circuit": spc.get("supply_ma"), "hb": spc.get("hb")}
            if name == "fullchain":
                rows[name]["spectre_band_metrics"] = ck.band_metrics(spc, fc, sp.fbw_ratio)
                rows[name]["engine_band_metrics"] = ck.band_metrics(eng, fc, sp.fbw_ratio)
                m = dict(rows[name]["spectre_band_metrics"], power_ma=design.power_ma)
                rows[name]["spectre_spec_check"] = T.spec_check(m, sp)
        rep["cases"] = rows
        rep["spectre_calls"], rep["spectre_wall_s"] = cad.n_calls, round(cad.wall_s, 1)
        rep["local_evidence"] = _rel(cad.local_root / cad.run_id)
    finally:
        D.set_device_provider(None)
    rep["wall_s"] = round(time.perf_counter() - t0, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"pdk_check_{spec_id}.json").write_text(json.dumps(rep, indent=2, default=float), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k not in ("design", "table_widths")}, indent=2, default=float)[:6000])
    return 0


def cmd_llm_check(policy_name: str, out: Path) -> int:
    """Two calls through the chosen LLM transport: a ping and one real Refiner decision
    on a canned S9 observation.  Proves login/quota/parsing before a long benchmark."""
    from orfadc.repro.llm import _valid_refine, make_policy
    from orfadc.repro.agents import Candidate
    t0 = time.perf_counter()
    pol = make_policy(policy_name)
    report: dict = {"policy": policy_name}
    tr = pol.transport
    try:
        text, u = tr.complete("You are a terse assistant.", "Reply with exactly: OK")
        report["ping"] = {"text": text.strip()[:80], "usage": u}
    except Exception as exc:
        report["ping"] = {"error": repr(exc)[:500]}
    sp = specs()["S9"]
    cand = Candidate("C000", [0.35, 0.15, 0.5], {"config_id": "crit_large__noncrit_large", "stages": []},
                     {"sim_result_cpstages": {"nf_db": 4.6, "s11_db": -24.0, "gain_cp_db": 17.0, "ip1db_cp_dbm": -14.0},
                      "feasible": True, "passive_params_cpstages": {}}, 0.2, 17.0)
    fc = {"sim_results_dict": {"gain_min_db": 25.4, "ripple_db": 1.8, "nf_fc_db": 4.8, "ip1db_dbm": -19.6,
                               "s11_max_inband_db": -18.0, "power_ma": 29.1},
          "violations": {"gain": 0.0, "ripple": 0.0, "nf": 0.0, "ip1db": 4.6, "s11": 0.0, "power": 0.0},
          "compression_stages": {"stage1": {"ip1db_dbm_if_alone": -2.0, "mechanism": "voltage_swing"},
                                 "stage2": {"ip1db_dbm_if_alone": -12.0, "mechanism": "current_clip"},
                                 "stage3": {"ip1db_dbm_if_alone": -20.5, "mechanism": "current_clip"}}}
    s3 = {"stage_gain_hf_db_at_fc": [4.0, 9.5, 12.0], "rounds": []}
    act = pol.refine_action(sp, cand, fc, s3, 0)
    last = pol.log[-1] if getattr(pol, "log", None) else {}
    report["refine_decision"] = {"action": act, "from_llm": bool(last.get("parsed")) and _valid_refine(last.get("parsed")),
                                 "raw_tail": (last.get("response") or last.get("error") or "")[-600:]}
    report["usage"] = getattr(pol, "usage", None).__dict__ if hasattr(pol, "usage") else None
    report["wall_s"] = round(time.perf_counter() - t0, 1)
    ok = "error" not in report["ping"] and report["refine_decision"]["from_llm"]
    report["ok"] = ok
    if hasattr(tr, "close"):
        tr.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"llm_check_{policy_name}.json").write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False),
                                                       encoding="utf-8")
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    return 0 if ok else 4


def write_summary(out: Path, parts: dict) -> None:
    lines = ["# RFAmpDesigner reproduction run", "", f"*{LABEL}*", "",
             f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"- cost model (equivalent seconds): {T.EQUIV_COST_S}", ""]
    for name in ("table4_like", "table5_like"):
        p = out / "tables" / f"{name}.md"
        if p.exists():
            lines += [p.read_text(encoding="utf-8"), ""]
    if "fig5" in parts:
        f5 = parts["fig5"]
        lines += ["## Fig. 5-like (multi-fidelity band planning)", "",
                  f"- equivalent time: multi-fidelity {f5['equiv_time_s']['multi_fidelity']:.0f} s vs "
                  f"simulation-based {f5['equiv_time_s']['simulation_based']:.0f} s "
                  f"(**{f5['equiv_time_s']['reduction_pct']:.0f}% reduction**; paper: 88%)",
                  "- Eq. 3 per-stage gain error vs high-fidelity simulation (60 random MCR points):", ""]
        for k, v in f5["eq3_stage_gain_error_vs_hf"].items():
            lines.append(f"  - `{k}`: mean {v['mean_err_db']:+.2f} dB, std {v['std_err_db']:.2f} dB, rms {v['rms_err_db']:.2f} dB")
        lines.append("")
    f10 = out / "raw" / "fig10.json"
    if f10.exists():
        d = json.loads(f10.read_text(encoding="utf-8"))
        lines += ["## Fig. 10-like (self-evolution, gain 20..45 dB, IP1dB = -(gain+5) dBm)", "",
                  "| method | tasks solved | cumulative equivalent time (s) | per-task mean (s) |", "|---|---|---|---|"]
        for m in ("ours_eb", "ga_vanilla", "bo_vanilla"):
            arr = np.array([[x["equiv_s"] for x in s_] for s_ in d[m]])
            suc = sum(x["success"] for s_ in d[m] for x in s_)
            lines.append(f"| {m} | {suc}/{arr.size} | {arr.sum(1).mean():.0f} | "
                         + ", ".join(f"{v:.0f}" for v in arr.mean(0)) + " |")
        lines.append("")
    lines += ["Figures: " + ", ".join(sorted(p.name for p in (out / "figures").glob("*.png"))) if (out / "figures").exists() else ""]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["all", "table4", "table5", "fig5", "fig7", "fig10", "smoke", "design", "replot", "llm-check", "cadence-check", "llm-table", "llm-seeds", "pdk-inventory", "pdk-config", "pdk-refit", "pdk-characterize", "pdk-characterize3", "pdk-characterize-casc", "pdk-check"])
    ap.add_argument("--spec", default="S2", help="spec id for the 'design' command")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", type=int, default=1, choices=[1, 2])
    ap.add_argument("--policy", default="rule",
                    choices=["rule", "scripted", "anthropic", "openai", "claude-cli", "codex-mcp"])
    ap.add_argument("--vds", type=float, default=None, help="pdk-characterize: drain bias (default: PDK vdd)")
    ap.add_argument("--freqs", default="", help="pdk-characterize: extra S/noise frequencies in GHz, e.g. 15,25,35,45,60")
    ap.add_argument("--inputs", default="", help="llm-seeds: extra comma-separated run folders merged with --out; pdk-refit: raw pdk_char folders")
    ap.add_argument("--widths", default="", help="pdk-characterize3/-casc: stage-1 widths in um (default 45,72,99,126,153,180); pdk-characterize: probe widths")
    ap.add_argument("--backend", default="surrogate", choices=["surrogate", "cadence", "pdk"],
                    help="simulator for design/llm-check (cadence = remote Spectre, see backend_cadence.py)")
    ap.add_argument("--agent-impl", default=None, choices=list(AGENT_IMPLS),
                    help="design: agent implementation (default: ORFADC_AGENT_IMPL, else v1)")
    ap.add_argument("--memory", type=Path, default=None, help="KB/EB directory (mode 2 / self-evolution)")
    ap.add_argument("--lr", default=None, help="pdk-config: RF nmos gate length, e.g. 60n (required)")
    ap.add_argument("--wr-um", type=float, default=None, help="pdk-config: finger width in um (required)")
    ap.add_argument("--vdd", type=float, default=None, help="pdk-config: supply in V (required)")
    ap.add_argument("--mult-param", default=None, help="pdk-config: multiplicity instance parameter (default multi; N65: m)")
    ap.add_argument("--prefer", default=None, help="pdk-config: substring of the preferred model file path")
    ap.add_argument("--corner", default=None, help="pdk-config: corner section of toplevel.scs (default tt_lib/top_tt/tt)")
    ap.add_argument("--nmos", default="nmos_rf", help="pdk-config: RF nmos cell name")
    ap.add_argument("--force", action="store_true", help="pdk-config: replace an existing local model config")
    ap.add_argument("--vds-cs", type=float, default=None, help="pdk-config: drain bias of the cs3 three-port (default 0.5 V)")
    ap.add_argument("--vb-grid", default="", help="pdk-config: gate-bias grid in V, e.g. 0.4,0.45,0.5 (default: device grid)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "repro" / "latest")
    ap.add_argument("--specs", default=None, help="comma list for table4, e.g. S1,S2")
    ap.add_argument("--methods", default=None, help="comma list for table4")
    a = ap.parse_args(argv)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    parts: dict = {}
    if a.cmd == "smoke":
        cmd_smoke(out)
        return 0
    if a.cmd == "replot":  # rebuild tables/figures from existing raw runs (no simulation)
        rows = [json.loads(x) for x in (out / "raw" / "table4_runs.jsonl").read_text(encoding="utf-8").splitlines() if x]
        ids = sorted({r["spec"] for r in rows}, key=lambda x: int(x[1:]))
        ms = [m for m in METHODS_T4 if any(r["method"] == m for r in rows)]
        write_table(out / "tables" / "table4_like", summarize(rows, ms, ids), ms,
                    "Table IV-like: first 8 tasks (1 h equivalent budget)")
        cmd_fig7(out, rows)
        cmd_fig8(out, rows)
        f5 = out / "raw" / "fig5.json"
        write_summary(out, {"fig5": json.loads(f5.read_text(encoding="utf-8"))} if f5.exists() else {})
        print(f"replotted {out}")
        return 0
    if a.cmd == "llm-table":
        return cmd_llm_table(out)
    if a.cmd == "llm-seeds":
        return cmd_llm_seeds(out, [Path(x) for x in a.inputs.split(",") if x])
    if a.cmd == "pdk-check":  # docs/120 V2-4/V2-5: engine on the PDK table vs Spectre with PDK transistors
        return cmd_pdk_check(out, a.spec, a.seed)
    if a.cmd == "pdk-characterize":  # docs/120 V2-2: PDK device table (results stay in git-ignored results/runs/)
        from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
        from orfadc.repro import device as D, pdk_v2
        runner = RemoteRunner(load_remote_config(ROOT / "config" / "remote_cadence.local.yaml"))
        cfg = pdk_v2.load_pdk_config()
        widths = sorted(set(D.cascode_widths()) | set(D.diff_widths()))
        if a.widths:  # docs/132: a one-width probe before the full table
            widths = [float(x) for x in a.widths.split(",")]
        vbs = [float(v) for v in cfg.get("vb_grid") or D.bias_grid()]
        vds = a.vds
        freqs = [float(x) * 1e9 for x in a.freqs.split(",")] if a.freqs else None
        rep = pdk_v2.characterize(runner, cfg, widths, vbs, vds=vds, nr_candidates=[] if vds is not None else None,
                                  freqs=freqs)
        print(json.dumps({"valid_nr": rep["valid_nr"], "spectre_runs": rep["spectre_runs"], "rows": len(rep["rows"]),
                          "failed_widths": [k for k, v in rep["widths"].items() if not v["steps"]["ok"] or "parse_error" in v],
                          "local_dir": rep["local_dir"]}, indent=1))
        return 0 if rep["rows"] else 7
    if a.cmd == "pdk-characterize3":  # docs/123: 3-port Y of the stage-1 cell (CS at low Vds, CG with lifted source)
        from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
        from orfadc.repro import device as D, pdk3, pdk_v2
        runner = RemoteRunner(load_remote_config(ROOT / "config" / "remote_cadence.local.yaml"))
        cfg = pdk_v2.load_pdk_config()
        widths = [float(x) for x in a.widths.split(",")] if a.widths else [45.0, 72.0, 99.0, 126.0, 153.0, 180.0]
        vbs = [float(v) for v in cfg.get("vb_grid") or D.bias_grid()]
        freqs = [float(x) * 1e9 for x in (a.freqs or "5,15,25,30,35,45,60").split(",")]
        rep = pdk3.characterize3(runner, cfg, widths, vbs, freqs)
        print(json.dumps({"spectre_runs": rep["spectre_runs"], "rows": len(rep["rows"]),
                          "failed": [k for k, v in rep["runs"].items() if not v["steps"]["ok"] or "parse_error" in v],
                          "local_dir": rep["local_dir"]}, indent=1))
        return 0 if rep["rows"] else 7
    if a.cmd == "pdk-characterize-casc":  # docs/123 §11: two-port noise of the stage-1 cascode cell
        from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
        from orfadc.repro import device as D, pdk3, pdk_v2
        runner = RemoteRunner(load_remote_config(ROOT / "config" / "remote_cadence.local.yaml"))
        cfg = pdk_v2.load_pdk_config()
        widths = [float(x) for x in a.widths.split(",")] if a.widths else [45.0, 72.0, 99.0, 126.0, 153.0, 180.0]
        vbs = [float(v) for v in cfg.get("vb_grid") or D.bias_grid()]
        freqs = [float(x) * 1e9 for x in (a.freqs or "5,15,25,30,35,45,60").split(",")]
        rep = pdk3.characterize_casc(runner, cfg, widths, vbs, freqs)
        print(json.dumps({"spectre_runs": rep["spectre_runs"], "rows": len(rep["rows"]),
                          "failed": [k for k, v in rep["runs"].items() if not v["steps"]["ok"] or "parse_error" in v],
                          "local_dir": rep["local_dir"]}, indent=1))
        return 0 if rep["rows"] else 7
    if a.cmd == "pdk-config":  # docs/132 N1: local model config from the newest inventory (offline, 0 Spectre)
        from orfadc.repro import pdk_v2
        if a.lr is None or a.wr_um is None or a.vdd is None:
            raise SystemExit("pdk-config needs --lr, --wr-um and --vdd")
        invs = sorted((ROOT / "results" / "runs" / "pdk_inventory").glob("*/inventory.json"))
        if not invs:
            raise SystemExit("no inventory; run `bench pdk-inventory` first")
        pdk = pdk_v2.propose_config(json.loads(invs[-1].read_text(encoding="utf-8")), nmos=a.nmos, prefer=a.prefer,
                                    corner=a.corner)
        pdk.update({"lr": a.lr, "wr_um": a.wr_um, "vdd": a.vdd})
        if a.mult_param:
            pdk["mult_param"] = a.mult_param
        if a.vds_cs is not None:
            pdk["vds_cs"] = a.vds_cs
        if a.vb_grid:
            pdk["vb_grid"] = [float(x) for x in a.vb_grid.split(",")]
        path = pdk_v2.write_pdk_config(pdk, force=a.force)
        # PDK paths stay in the git-ignored file; the console only shows the non-path choices.
        print(json.dumps({"written": path.name, "inventory": invs[-1].parent.name, "toplevel": "<set>",
                          **{k: v for k, v in pdk.items() if k != "toplevel"}}, indent=1))
        return 0
    if a.cmd == "pdk-refit":  # docs/122 fit + large-signal 1 dB point for raw device tables (offline, 0 Spectre)
        from orfadc.repro import pdk_fit
        root = ROOT / "results" / "runs" / "pdk_char"
        dirs = [Path(x) for x in a.inputs.split(",") if x] or \
            [d for d in sorted(root.glob("*")) if d.is_dir() and not d.name.endswith("_fit")
             and (d / "device_table.json").exists() and not (root / f"{d.name}_fit").exists()]
        done = []
        for d in dirs:
            rep = pdk_fit.add_large_signal(d, pdk_fit.refit_table(d))
            dst = d.parent / f"{d.name}_fit"
            dst.mkdir(exist_ok=True)
            (dst / "device_table.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
            done.append({"from": d.name, "to": dst.name, "rows": len(rep["rows"]), "vds_v": rep.get("vds_v")})
        print(json.dumps(done, indent=1))
        return 0 if done else 8
    if a.cmd == "pdk-inventory":  # docs/120 V2-0: read-only listing of the PDKs on the Cadence host
        from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
        from orfadc.repro import pdk_v2
        cfg_path = ROOT / "config" / "remote_cadence.local.yaml"
        runner = RemoteRunner(load_remote_config(cfg_path))
        inv = pdk_v2.run_inventory(runner, env=pdk_v2.load_inventory_env(cfg_path))  # optional `inventory:` block
        # PDK paths stay in the git-ignored results/runs/ folder; the console only gets counts.
        (Path(inv["local_dir"]) / "summary.txt").write_text(pdk_v2.summarize(inv) + "\n", encoding="utf-8")
        print(json.dumps({"complete": inv["complete"], "steps": inv["steps"], "pdk_dirs": len(inv["pdk_dirs"]),
                          "model_files": len(inv["model_files"]), "nmos_candidates": len(inv["nmos_candidates"]),
                          "local_dir": inv["local_dir"]}, indent=1))
        return 0 if inv["complete"] else 6
    if a.cmd == "cadence-check":
        return cmd_cadence_check(out, a.spec, a.seed)
    if a.cmd == "llm-check":
        return cmd_llm_check(a.policy, out)
    if a.cmd == "design":
        from orfadc.repro.llm import make_policy
        sp = {**specs(), **scaled_hard_specs()}[a.spec]
        backend, pdk = None, None
        impl = agent_impl(a.agent_impl)
        if impl == "v2" and a.policy == "rule":
            raise SystemExit("agent implementation v2 is LLM-driven: use --policy scripted|claude-cli|codex-mcp|anthropic|openai")
        pol = make_policy(a.policy) if impl == "v1" else None
        if a.backend == "cadence":
            from orfadc.repro.backend_cadence import CadenceBackend, HybridBackend
            backend = HybridBackend(T.SurrogateBackend(), CadenceBackend())
        elif a.backend == "pdk":  # inner loop: engine on the PDK device table; Stage 4: Spectre + PDK RF MOS + HB
            os.environ.setdefault("ORFADC_REPORT_BEST", "1")
            from orfadc.repro import pdk_v2
            from orfadc.repro.backend_cadence import HybridBackend
            pdk_v2.install_table()
            final = pdk_v2.PdkCadenceBackend(hb_pins=PDK_HB_PINS)
            pdk = pdk_label(final.cfg)
            backend = HybridBackend(T.SurrogateBackend(), final)
        mem = a.memory or default_memory_dir(impl, pdk)
        mem_dir = mem if (a.mode == 2 or a.memory) else None
        if impl == "v2":
            from orfadc.repro import agents_v2
            r = agents_v2.run_design_v2(sp, a.seed, mode=a.mode, memory_dir=mem_dir, budget_equiv_s=budget_for(a.spec),
                                        policy_name=a.policy, backend=backend, pdk=pdk)
        else:
            r = A.run_design(sp, a.seed, mode=a.mode, policy=pol, budget_equiv_s=budget_for(a.spec),
                             memory_dir=mem_dir, backend=backend)
        r.pop("_session", None)
        r["run_settings"] = {"q_match": ck.Q_MATCH, "budget_equiv_s": budget_for(a.spec),
                             "spectre_max_per_design": os.environ.get("ORFADC_SPECTRE_MAX_PER_DESIGN")}
        n_spectre = spectre_calls_of(backend)
        if n_spectre is not None:  # docs/132: per-design Spectre count for the ledger (parallel queues)
            r["spectre_calls"] = n_spectre
        if impl == "v2":
            r["run_settings"]["llm_max_calls"] = int(os.environ.get("ORFADC_LLM_MAX_CALLS") or LLM_MAX_CALLS_DEFAULT)
            r["run_settings"]["memory_dir"] = _rel(mem_dir) if mem_dir else None
        if hasattr(pol, "usage"):
            r["llm_usage"] = pol.usage.__dict__
            r["llm_log"] = pol.log
        r["labels"] = {"agent_impl": impl, "pdk": pdk, "not_silicon_result": True,
                       "note": ("schematic-level PDK transistors, ideal passives, no layout parasitics" if pdk else
                                "Spectre-solved macromodel (surrogate devices)" if a.backend == "cadence" else LABEL)}
        name = (f"design_{a.spec}_seed{a.seed}_mode{a.mode}_{a.policy}"
                + design_suffix(backend=a.backend, impl=impl, pdk=pdk, llm=impl == "v2" or hasattr(pol, "usage")) + ".json")
        (out / name).write_text(json.dumps(r, indent=1, default=float), encoding="utf-8")
        rep = r.get("report") or {}
        print(json.dumps({"spec": a.spec, "success": r["success"], "sims": r["sims"], "bottleneck": rep.get("bottleneck"),
                          "metrics": rep.get("metrics"), "llm_usage": r.get("llm_usage"), "file": str(out / name)},
                         indent=2, default=float))
        return 0 if r["success"] else 3
    if a.cmd in ("all", "fig5"):
        parts["fig5"] = cmd_fig5(out)
        print("fig5:", json.dumps(parts["fig5"]["equiv_time_s"]))
    if a.cmd in ("all", "table4", "fig7"):
        rows = cmd_table4(out, a.seeds, a.workers, a.specs.split(",") if a.specs else None,
                          a.methods.split(",") if a.methods else None)
        (out / "figures").mkdir(parents=True, exist_ok=True)
        cmd_fig7(out, rows)
        cmd_fig8(out, rows)
        print((out / "tables" / "table4_like.md").read_text(encoding="utf-8"))
    if a.cmd in ("all", "table5"):
        cmd_table5(out, a.seeds, a.workers)
        print((out / "tables" / "table5_like.md").read_text(encoding="utf-8"))
    if a.cmd in ("all", "fig10"):
        (out / "raw").mkdir(parents=True, exist_ok=True)
        (out / "figures").mkdir(parents=True, exist_ok=True)
        cmd_fig10(out, seeds=min(a.seeds, 3))
    write_summary(out, parts)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
