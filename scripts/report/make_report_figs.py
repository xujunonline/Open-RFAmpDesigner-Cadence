"""Figures for the v2 experiment report (docs/139), drawn from results/report/*.csv and the Spectre ledger.

Run scripts/report/make_report_tables.py first.

    python scripts/report/make_report_figs.py [--out results/report/figures]
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "results" / "report"
# Okabe-Ito categorical order (colour-blind safe), fixed per series
COLORS = {"paper": "#999999", "crn40lp_v1": "#0072B2", "n65_v1": "#E69F00", "n65_v2": "#009E73"}
PAPER_OURS = {"S1": 5, "S2": 5, "S3": 3, "S4": 5, "S5": 4, "S6": 2, "S7": 3, "S8": 5}   # paper Table IV, out of 5


def read(name: str) -> list[dict]:
    return list(csv.DictReader(open(REP / name, encoding="utf-8")))


def fig_pass_by_spec(out: Path) -> None:
    specs = [f"S{i}" for i in range(1, 9)]
    by = {}
    for r in read("pass_by_spec.csv"):
        if r["experiment"] in ("N3", "A3-N65"):
            by[("n65_v1" if r["experiment"] == "N3" else "n65_v2", r["spec"])] = r
    for r in read("v1_reference.csv"):
        if "pdk_pass_at1" in r["source"] and r["spec"] in specs:
            by[("crn40lp_v1", r["spec"])] = r
    series = [("paper", "Paper (Ours, N65 post-layout)"), ("crn40lp_v1", "crn40lp, v1 rule [PDK]"),
              ("n65_v1", "N65, v1 rule [PDK]"), ("n65_v2", "N65, v2 + Codex [PDK]")]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    width = 0.2
    for j, (key, label) in enumerate(series):
        xs = [i + (j - 1.5) * width for i in range(len(specs))]
        if key == "paper":
            ys = [PAPER_OURS[s] / 5 for s in specs]
            ax.bar(xs, ys, width * 0.9, color=COLORS[key], label=label)
            continue
        ys, lo, hi = [], [], []
        for s in specs:
            r = by[(key, s)]
            p = int(r["passed"]) / int(r["n"])
            ys.append(p)
            lo.append(p - float(r["wilson95_lo"]))
            hi.append(float(r["wilson95_hi"]) - p)
        ax.bar(xs, ys, width * 0.9, color=COLORS[key], label=label)
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor="#333333", elinewidth=0.8, capsize=2)
    ax.set_xticks(range(len(specs)), specs)
    ax.set_ylabel("pass@1 (5 seeds)")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(ncol=2, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.22))
    ax.text(1.0, -0.16, "Error bars: 95% Wilson interval. Paper bars: reported values, no interval.",
            transform=ax.transAxes, ha="right", fontsize=7, color="#555555")
    fig.tight_layout()
    fig.savefig(out / "fig_pass_by_spec.png", dpi=200)
    plt.close(fig)


def fig_spectre_ledger(out: Path) -> None:
    rows = list(csv.DictReader(open(ROOT / "results" / "repro" / "n65" / "spectre_ledger.csv", encoding="utf-8")))
    # some rows were appended after later ones (back-filled entries), so sort by timestamp and re-accumulate;
    # the final total equals the ledger's last cumulative value
    rows.sort(key=lambda r: datetime.fromisoformat(r["time"]))
    t = [datetime.fromisoformat(r["time"]) for r in rows]
    cum, acc = [], 0
    for r in rows:
        acc += int(r["spectre_runs"])
        cum.append(acc)
    caps = [(datetime(2026, 10, 6, 9, 0), 1500), (datetime(2026, 10, 7, 16, 24), 2000),
            (datetime(2026, 10, 9, 3, 46), 2400), (datetime(2026, 10, 9, 21, 24), 3000),
            (datetime(2026, 10, 10, 0, 57), 3300)]   # docs/130 §1-3; approximate approval times (git log, ledger)
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.step(t, cum, where="post", color="#0072B2", linewidth=1.6, label="Cumulative Spectre runs (ledger)")
    end = max(t[-1], caps[-1][0])
    cx, cy = [], []
    for i, (ct, cv) in enumerate(caps):
        nxt = caps[i + 1][0] if i + 1 < len(caps) else end
        cx += [ct, nxt]
        cy += [cv, cv]
    ax.plot(cx, cy, color="#999999", linestyle="--", linewidth=1.0, label="Approved cap")
    marks = {}
    for r, ti, c in zip(rows, t, cum):
        marks.setdefault(r["stage"], (ti, c))
    for st, (ti, c) in marks.items():
        if st in ("N3", "A3-2", "B", "E2", "b2", "b2-v2"):
            ax.annotate(st, (ti, c), xytext=(4, 6), textcoords="offset points", fontsize=7, color="#333333")
    ax.set_ylabel("Spectre runs")
    ax.set_ylim(0, 3500)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "fig_spectre_ledger.png", dpi=200)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REP / "figures"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    fig_pass_by_spec(out)
    fig_spectre_ledger(out)
    print("written:", sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main()
