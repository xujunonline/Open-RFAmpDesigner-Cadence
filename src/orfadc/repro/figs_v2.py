"""Paper-style figures for the v2 results (docs/133).

``fig9``: mean SEARCH and REFINE count per seed, per method and spec (paper Fig. 9 reports the same two counts per
model / configuration on S9/S10).  Reads the design JSONs written by ``bench design``; nothing is simulated.

    python -m orfadc.repro.figs_v2 fig9 --out results/repro/v2_a3/figures
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SEARCH_C, REFINE_C = "#2a78d6", "#eb6834"      # categorical slots 1-2 of the dataviz reference palette
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

# (panel title, [(label, glob, spec filter)]); labels say which agent implementation / prompt / backend
PANELS = [
    ("(a) Surrogate, S9s/S10s, 5 h, 5 seeds (trend-level)", [
        ("v2 + Codex\nprompt rev 1", "results/repro/v2_a3/s9s10s/design_*_codex-mcp_v2_calls1000.json"),
        ("v2 + Codex\nprompt rev 2", "results/repro/v2_a3/s9s10s_r2/design_*_codex-mcp_v2_r2_calls1000.json"),
    ]),
    ("(b) N65 PDK, S9/S10, 5 h, 5 seeds (schematic-level)", [
        ("v2 + Codex", "results/repro/v2_a3/n65_s9s10/design_*_codex-mcp_pdk_n65_v2_calls1000_smax*.json"),
        ("v1 rule", "results/repro/v2_a3/n65_s9s10/design_*_rule_pdk_n65_smax60.json"),
    ]),
]


def collect(pattern: str, root: Path = ROOT) -> dict[str, dict]:
    """{spec: {"search": [...], "refine": [...], "pass": [...], "seeds": [...]}} from design JSONs."""
    out: dict[str, dict] = {}
    for f in sorted(glob.glob(str(root / pattern))):
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        d = out.setdefault(r["spec"], {"search": [], "refine": [], "pass": [], "seeds": []})
        d["search"].append(int(r.get("n_search") or 0))
        d["refine"].append(int(r.get("n_refine") or 0))
        d["pass"].append(bool(r.get("success")))
        d["seeds"].append(int(r.get("seed", -1)))
    return out


def fig9(out: Path, panels=PANELS, root: Path = ROOT) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    summary: dict = {}
    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 3.8), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (title, groups) in zip(axes, panels):
        labels, s_mean, s_std, r_mean, r_std, notes = [], [], [], [], [], []
        for name, pattern in groups:
            data = collect(pattern, root)
            for spec in sorted(data, key=lambda s: (len(s), s)):
                d = data[spec]
                labels.append(f"{name}\n{spec}")
                s_mean.append(np.mean(d["search"])); s_std.append(np.std(d["search"]))
                r_mean.append(np.mean(d["refine"])); r_std.append(np.std(d["refine"]))
                notes.append(f"{sum(d['pass'])}/{len(d['pass'])}")
                summary[f"{title} | {name.replace(chr(10), ' ')} | {spec}"] = {
                    "n": len(d["seeds"]), "search_mean": float(np.mean(d["search"])),
                    "refine_mean": float(np.mean(d["refine"])), "pass": f"{sum(d['pass'])}/{len(d['pass'])}"}
        x = np.arange(len(labels))
        w = 0.36
        ax.bar(x - w / 2 - 0.01, s_mean, w, yerr=s_std, color=SEARCH_C, label="SEARCH", capsize=2,
               error_kw={"elinewidth": 1, "ecolor": MUTED})
        ax.bar(x + w / 2 + 0.01, r_mean, w, yerr=r_std, color=REFINE_C, label="REFINE", capsize=2,
               error_kw={"elinewidth": 1, "ecolor": MUTED})
        for xi, top, note in zip(x, np.maximum(np.add(s_mean, s_std), np.add(r_mean, r_std)), notes):
            ax.text(xi, top + 0.4, f"pass {note}", ha="center", va="bottom", fontsize=7, color=MUTED)
        ax.set_xticks(x, labels, fontsize=7, color=INK)
        ax.set_title(title, fontsize=9, color=INK)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=7)
    axes[0].set_ylabel("count per seed (mean ± std)", fontsize=8, color=INK)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Fig. 9-like: SEARCH / REFINE per seed (not silicon; see docs/133)", fontsize=10, color=INK)
    fig.tight_layout()
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "fig9_like.png", dpi=150)
    plt.close(fig)
    (out / "fig9_like.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def fom(metrics: dict | None, spec, vdd: float) -> float | None:
    """LNA figure of merit (user choice, docs/133 §11; the paper's FoM is defined in its ref. [48], not in the text):
    FoM = G_lin * BW[GHz] / ((F_lin - 1) * P_DC[mW]),  G and F at fc, BW = fbw * fc, P_DC = I_total * VDD."""
    if not metrics:
        return None
    g = 10 ** (float(metrics["gain_fc_db"]) / 10)
    f = 10 ** (float(metrics["nf_fc_db"]) / 10)
    p_mw = float(metrics["power_ma"]) * vdd
    bw = spec.fbw_ratio * spec.fc_ghz
    return g * bw / ((f - 1) * p_mw) if f > 1 and p_mw > 0 else None


def run_fig11(seeds: int = 3, work: Path | None = None) -> dict:
    """Re-run the Fig. 10 protocol (bench.cmd_fig10: S4-style tasks, gain 20 -> 45 dB, ours_eb in mode 2 with memory,
    GA/BO vanilla) and keep each task's final metrics, so FoM can be traced against cumulative simulation cost.
    Same seeds, tasks and budgets as cmd_fig10; the surrogate pipeline is deterministic, so the costs must equal
    results/repro/2026-10-03/raw/fig10.json (checked by the caller)."""
    import shutil

    from . import agents as A
    from . import baselines as B
    from .bench import specs
    from .device import vdd
    from ..schemas import Spec
    base = specs()["S4"]
    gains = [20, 25, 30, 35, 40, 45]
    tasks = [Spec(id=f"G{g}", fc_ghz=base.fc_ghz, fbw_ratio=base.fbw_ratio, power_ma=base.power_ma,
                  gain_db=g, nf_max_db=base.nf_max_db, ip1db_min_dbm=-(g + 5.0)) for g in gains]
    work = work or ROOT / "results" / "runs" / "fig11_memory"
    res: dict = {"gains": gains, "fom_definition": "G_lin*BW_GHz/((F_lin-1)*P_DC_mW) at fc", "vdd_v": vdd()}
    for method in ("ours_eb", "ga_vanilla", "bo_vanilla"):
        per_seed = []
        for seed in range(seeds):
            mem = work / f"memory_fig11_{seed}"
            if mem.exists():
                shutil.rmtree(mem)
            rows = []
            for t in tasks:
                if method == "ours_eb":
                    r = A.run_design(t, seed, mode=2, memory_dir=mem, budget_equiv_s=3600.0)
                    m = (r.get("report") or {}).get("metrics")
                else:
                    r = B.run_baseline(method, t, seed, 3600.0)
                    m = r.get("metrics")
                rows.append({"task": t.id, "sims": r["sims"]["hf_total"], "equiv_s": r["sims"]["equiv_time_s"],
                             "success": r["success"], "fom": fom(m, t, vdd()),
                             "metrics": {k: m.get(k) for k in ("gain_fc_db", "nf_fc_db", "power_ma", "ip1db_dbm")} if m else None})
            per_seed.append(rows)
        res[method] = per_seed
    return res


def plot_fig11(res: dict, out: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"ours_eb": SEARCH_C, "ga_vanilla": REFINE_C, "bo_vanilla": "#1baf7a"}   # categorical slots 1-3
    names = {"ours_eb": "Ours (v1 rule, with memory)", "ga_vanilla": "GA (vanilla)", "bo_vanilla": "BO (vanilla)"}
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    summary = {}
    for m in ("ours_eb", "ga_vanilla", "bo_vanilla"):
        cum_end = []
        for s, rows in enumerate(res[m]):
            cum = np.cumsum([r["equiv_s"] for r in rows])
            ok = [(c, r["fom"]) for c, r in zip(cum, rows) if r["success"] and r["fom"] is not None]
            if ok:
                xs, ys = zip(*ok)
                ax.plot(xs, ys, color=colors[m], marker="o", markersize=4, linewidth=1.2, alpha=0.85,
                        label=names[m] if s == 0 else None)
            cum_end.append(float(cum[-1]))
        foms = [r["fom"] for rows in res[m] for r in rows if r["success"] and r["fom"] is not None]
        summary[m] = {"cum_equiv_s_mean": float(np.mean(cum_end)), "solved": sum(r["success"] for rows in res[m] for r in rows),
                      "tasks": sum(len(rows) for rows in res[m]), "fom_mean": float(np.mean(foms)) if foms else None,
                      "fom_std": float(np.std(foms)) if foms else None}
    ours = summary["ours_eb"]["cum_equiv_s_mean"]
    for m in ("ga_vanilla", "bo_vanilla"):
        summary[m]["cost_ratio_vs_ours"] = summary[m]["cum_equiv_s_mean"] / ours if ours else None
    ax.set_xscale("log")
    ax.set_yscale("log")                     # FoM spans ~3 decades (gain 20 -> 45 dB)
    ax.set_xlabel("Cumulative equivalent simulation time (s, log)", fontsize=8, color=INK)
    ax.set_ylabel("FoM of each solved task, log  [G·BW / ((F−1)·P_DC), GHz/mW]", fontsize=8, color=INK)
    ax.set_title("Fig. 11-like: FoM vs simulation cost over the 6-task sequence (surrogate, 3 seeds)", fontsize=9, color=INK)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=7)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "fig11_like.png", dpi=150)
    plt.close(fig)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fig9", "fig11"])
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "repro" / "v2_a3" / "figures")
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args(argv)
    if a.cmd == "fig11":
        res = run_fig11(a.seeds)
        ref = ROOT / "results" / "repro" / "2026-10-03" / "raw" / "fig10.json"
        if ref.exists():          # determinism check against the published Fig. 10 run
            old = json.loads(ref.read_text(encoding="utf-8"))
            res["matches_fig10_costs"] = all(
                round(x["equiv_s"], 2) == round(y["equiv_s"], 2) and x["success"] == y["success"]
                for m in ("ours_eb", "ga_vanilla", "bo_vanilla") for s1, s2 in zip(res[m], old[m]) for x, y in zip(s1, s2))
        a.out.mkdir(parents=True, exist_ok=True)
        res["summary"] = plot_fig11(res, a.out)
        (a.out / "fig11_like.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
        print(json.dumps({"matches_fig10_costs": res.get("matches_fig10_costs"), "summary": res["summary"]}, indent=1))
        return 0
    summary = fig9(a.out)
    for k, v in summary.items():
        print(f"{k}: n={v['n']} search={v['search_mean']:.1f} refine={v['refine_mean']:.1f} pass={v['pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
