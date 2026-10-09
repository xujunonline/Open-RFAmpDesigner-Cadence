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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fig9"])
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "repro" / "v2_a3" / "figures")
    a = ap.parse_args(argv)
    summary = fig9(a.out)
    for k, v in summary.items():
        print(f"{k}: n={v['n']} search={v['search_mean']:.1f} refine={v['refine_mean']:.1f} pass={v['pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
