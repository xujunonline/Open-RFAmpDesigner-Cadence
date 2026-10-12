"""Recompute the numbers of the v2 experiment report (docs/139) from raw result files.

Reads only committed results (design JSONs, the N65 Spectre ledger, v1 baseline raw files) and writes
CSV/JSON tables to results/report/.  Offline: no Cadence, no LLM calls.

    python scripts/report/make_report_tables.py [--out results/report]
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import defaultdict
from pathlib import Path

from scipy.stats import fisher_exact

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "results" / "repro"

# (experiment id, description, evidence level, glob relative to results/repro, recursive)
EXPERIMENTS = [
    ("N2", "N65 smoke, v1 rule, seed 0, guard 14", "pdk_schematic", "n65/n2/**/design_*.json", True),
    ("N3", "N65 baseline, v1 rule, S1-S8 x 5 seeds, 1 h", "pdk_schematic", "n65/n3/**/design_*.json", True),
    ("A3-smoke", "surrogate S2 smoke, v2 (codex-mcp, claude-cli)", "surrogate", "v2_a3/smoke/design_*.json", False),
    ("A3-S9sS10s", "surrogate S9s/S10s, v2, 5 h, prompt rev 1", "surrogate", "v2_a3/s9s10s/design_*.json", False),
    ("C-surrogate", "surrogate S9s/S10s, v2 codex, prompt rev 2", "surrogate", "v2_a3/s9s10s_r2/design_*.json", False),
    ("A3-N65", "N65 S1-S8, v2 codex, 5 seeds, 1 h", "pdk_schematic", "v2_a3/n65/**/design_*.json", True),
    ("B", "N65 S5, v2 codex, 2 h budget, 5 seeds", "pdk_schematic", "v2_a3/n65_b_s5_2h/design_*.json", False),
    ("C-N65", "N65 S3/S5/S7 seed 0, v2 codex, prompt rev 2", "pdk_schematic", "v2_a3/n65_c_rev2/design_*.json", False),
    ("D3", "N65 S7, v1 rule, PDK spiral inductors, 5 seeds", "pdk_schematic", "v2_a3/n65_d3_spiral/design_*.json", False),
    ("E", "N65 original S9/S10, v1 rule and v2 codex, 5 h", "pdk_schematic", "v2_a3/n65_s9s10/design_*.json", False),
    ("a", "surrogate self-evolution (Fig. 10 protocol), v2 codex, 3 seeds", "surrogate", "v2_a3/fig10_v2/**/design_*.json", True),
    ("b-v1", "N65 Spectre anchors, v1 rule", "pdk_schematic", "v2_a3/n65_b2_anchors/design_*.json", False),
    ("b-v2", "N65 Spectre anchors, v2 codex (incl. guard-300 rerun)", "pdk_schematic", "v2_a3/n65_b2_anchors_v2/design_*.json", False),
]


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def load(pattern: str, recursive: bool) -> list[tuple[str, dict]]:
    files = sorted(glob.glob(str(R / pattern), recursive=recursive))
    files = [f for f in files if "void" not in f.lower() and "crash" not in f.lower()]
    return [(str(Path(f).relative_to(ROOT)), json.load(open(f, encoding="utf-8"))) for f in files]


def impl_of(r: dict) -> str:
    return (r.get("labels") or {}).get("agent_impl") or r.get("agent_impl") or "v1"


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results" / "report"))
    out = Path(ap.parse_args().out)

    runs, pass_rows, res_rows = [], [], []
    for exp, desc, ev, pat, rec in EXPERIMENTS:
        loaded = load(pat, rec)
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for path, r in loaded:
            u = r.get("llm_usage") or {}
            row = {"experiment": exp, "evidence": ev, "file": path, "spec": r["spec"], "seed": r.get("seed"),
                   "impl": impl_of(r), "policy": r.get("policy"), "success": bool(r["success"]),
                   "spectre_calls": r.get("spectre_calls"), "equiv_time_s": (r.get("sims") or {}).get("equiv_time_s"),
                   "llm_calls": u.get("calls"), "prompt_tokens": u.get("prompt_tokens"),
                   "completion_tokens": u.get("completion_tokens"), "terminated_reason": r.get("terminated_reason")}
            runs.append(row)
            groups[(row["impl"], row["policy"], row["spec"])].append(row)
        for (impl, pol, spec), g in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2])):
            k, n = sum(x["success"] for x in g), len(g)
            lo, hi = wilson(k, n)
            pass_rows.append({"experiment": exp, "evidence": ev, "impl": impl, "policy": pol, "spec": spec,
                              "passed": k, "n": n, "wilson95_lo": round(lo, 3), "wilson95_hi": round(hi, 3)})
        sel = [x for x in runs if x["experiment"] == exp]
        num = lambda key: [x[key] for x in sel if isinstance(x[key], (int, float))]
        eq = sorted(num("equiv_time_s"))
        res_rows.append({"experiment": exp, "description": desc, "evidence": ev, "designs": len(sel),
                         "passed": sum(x["success"] for x in sel),
                         "spectre_calls_in_json": sum(num("spectre_calls")) if num("spectre_calls") else "",
                         "equiv_time_s_total": round(sum(eq), 1) if eq else "",
                         "equiv_time_s_median": round(eq[len(eq) // 2], 1) if eq else "",
                         "llm_calls": sum(num("llm_calls")) if num("llm_calls") else "",
                         "prompt_tokens": sum(num("prompt_tokens")) if num("prompt_tokens") else "",
                         "completion_tokens": sum(num("completion_tokens")) if num("completion_tokens") else ""})

    # ---- totals per experiment / implementation (pass@1 with Wilson CI)
    totals = []
    for exp, desc, ev, _, _ in EXPERIMENTS:
        by_impl: dict[tuple, list] = defaultdict(list)
        for x in runs:
            if x["experiment"] == exp:
                by_impl[(x["impl"], x["policy"])].append(x)
        for (impl, pol), g in sorted(by_impl.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            k, n = sum(x["success"] for x in g), len(g)
            lo, hi = wilson(k, n)
            totals.append({"experiment": exp, "evidence": ev, "impl": impl, "policy": pol, "passed": k, "n": n,
                           "wilson95_lo": round(lo, 3), "wilson95_hi": round(hi, 3)})

    # ---- v1 reference results (raw files of earlier phases)
    refs = []
    for name, fn in (("table4", "table4_runs.jsonl"), ("table5", "table5_runs.jsonl")):
        rows = [json.loads(line) for line in open(R / "2026-10-03" / "raw" / fn, encoding="utf-8")]
        agg: dict[tuple, list] = defaultdict(list)
        for r in rows:
            agg[(r["method"], r["spec"])].append(bool(r["success"]))
        for (m, s), v in sorted(agg.items()):
            refs.append({"source": f"results/repro/2026-10-03/raw/{fn}", "evidence": "surrogate", "impl": "v1",
                         "method": m, "spec": s, "passed": sum(v), "n": len(v)})
    crn = json.load(open(R / "pdk_pass_at1_20261002" / "summary.json", encoding="utf-8"))
    crn_total_field = crn["pass_at1_5seed"].get("total")
    for s, v in crn["pass_at1_5seed"].items():
        if s == "total":   # checked against the per-spec sum below (it was stored as 34/40 before 2026-10-12)
            continue
        k, n = map(int, v.split("/"))
        refs.append({"source": "results/repro/pdk_pass_at1_20261002/summary.json", "evidence": "pdk_schematic_crn40lp",
                     "impl": "v1", "method": "ours_rule", "spec": s, "passed": k, "n": n})
    unc = json.load(open(R / "llm_live" / "codex_uncapped_20261002" / "runs.json", encoding="utf-8"))
    agg = defaultdict(list)
    for r in unc:
        if r.get("valid"):
            agg[r["spec"]].append(r.get("success") is True or r.get("best_eval_viol") == 0)
    for s, v in sorted(agg.items()):
        refs.append({"source": "results/repro/llm_live/codex_uncapped_20261002/runs.json", "evidence": "surrogate",
                     "impl": "v1", "method": "ours_codex_uncapped", "spec": s, "passed": sum(v), "n": len(v)})
    for x in refs:
        lo, hi = wilson(x["passed"], x["n"])
        x["wilson95_lo"], x["wilson95_hi"] = round(lo, 3), round(hi, 3)

    # ---- key comparisons (two-sided Fisher exact test)
    def count(exp, impl, specs=None, policy=None):
        g = [x for x in runs if x["experiment"] == exp and x["impl"] == impl
             and (specs is None or x["spec"] in specs) and (policy is None or x["policy"] == policy)]
        return sum(x["success"] for x in g), len(g)

    def ref_count(method, specs, source_key):
        g = [x for x in refs if x["method"] == method and x["spec"] in specs and source_key in x["source"]]
        return sum(x["passed"] for x in g), sum(x["n"] for x in g)

    comps = []
    for label, a, b in (
        ("N65 S1-S8: v1 rule vs v2 codex", count("N3", "v1"), count("A3-N65", "v2")),
        ("N65 S5: v1 rule vs v2 codex", count("N3", "v1", {"S5"}), count("A3-N65", "v2", {"S5"})),
        ("surrogate S9s/S10s: v2 codex (rev 1) vs v1 codex uncapped",
         count("A3-S9sS10s", "v2", {"S9s", "S10s"}, "codex-mcp"), ref_count("ours_codex_uncapped", {"S9s", "S10s"}, "uncapped")),
        ("surrogate S9s/S10s: v2 codex (rev 1) vs v1 rule",
         count("A3-S9sS10s", "v2", {"S9s", "S10s"}, "codex-mcp"), ref_count("ours", {"S9s", "S10s"}, "table5")),
        ("surrogate S9s/S10s: v2 rev 1 vs rev 2",
         count("A3-S9sS10s", "v2", {"S9s", "S10s"}, "codex-mcp"), count("C-surrogate", "v2")),
        ("N65 S1-S8 v1 rule: crn40lp vs N65",
         ref_count("ours_rule", {f"S{i}" for i in range(1, 9)}, "pdk_pass_at1"), count("N3", "v1")),
        ("N65 S9: v1 rule vs v2 codex", count("E", "v1", {"S9"}), count("E", "v2", {"S9"})),
    ):
        (ka, na), (kb, nb) = a, b
        _, p = fisher_exact([[ka, na - ka], [kb, nb - kb]], alternative="two-sided")
        comps.append({"comparison": label, "a_passed": ka, "a_n": na, "b_passed": kb, "b_n": nb,
                      "fisher_two_sided_p": round(float(p), 4)})

    # ---- Spectre ledger
    led = list(csv.DictReader(open(R / "n65" / "spectre_ledger.csv", encoding="utf-8")))
    by_stage: dict[str, int] = defaultdict(int)
    first: dict[str, str] = {}
    for r in led:
        by_stage[r["stage"]] += int(r["spectre_runs"])
        first.setdefault(r["stage"], r["time"])
    ledger_rows = [{"stage": s, "first_entry": first[s], "spectre_runs": v} for s, v in by_stage.items()]
    total = sum(by_stage.values())
    ledger_check = {"sum_of_rows": total, "last_cumulative": int(led[-1]["cumulative"]), "rows": len(led),
                    "consistent": total == int(led[-1]["cumulative"])}

    write_csv(out / "runs.csv", runs)
    write_csv(out / "pass_by_spec.csv", pass_rows)
    write_csv(out / "pass_totals.csv", totals)
    write_csv(out / "v1_reference.csv", refs)
    write_csv(out / "comparisons_fisher.csv", comps)
    write_csv(out / "resources_by_experiment.csv", res_rows)
    write_csv(out / "spectre_ledger_by_stage.csv", ledger_rows)
    crn_rows = [x for x in refs if "pdk_pass_at1" in x["source"]]
    crn_runs: dict[str, list] = defaultdict(list)
    for r in crn["runs"]:
        crn_runs[r["spec"]].append(bool(r["success"]))
    discrepancies = [{
        "item": "crn40lp v1 rule pass@1 (5 seeds), results/repro/pdk_pass_at1_20261002/summary.json and docs/127 §5.1",
        "stored_total": crn_total_field,
        "correction_note": crn.get("correction_2026_10_12", ""),
        "per_spec_sum": f"{sum(x['passed'] for x in crn_rows)}/{sum(x['n'] for x in crn_rows)}",
        "this_job_runs": f"{sum(sum(v) for v in crn_runs.values())}/{sum(len(v) for v in crn_runs.values())} "
                         "(docs/127 table originally stated 27/32)",
        "resolution": "use the per-spec sum; the earlier total 34/40 was an addition error, corrected on 2026-10-12 "
                      "in summary.json and all citing documents"}]
    a3_json = sum(x["spectre_calls"] or 0 for x in runs if x["experiment"] == "A3-N65")
    discrepancies.append({"item": "Spectre of the v2 N65 S1-S8 runs: design JSONs vs ledger stage A3-2",
                          "json_sum": a3_json, "ledger_stage_sum": by_stage.get("A3-2"),
                          "resolution": "ledger includes an aborted S2 seed-4 attempt (2 runs, ssh connect failure, "
                                        "no result file)"})
    (out / "summary.json").write_text(json.dumps({
        "note": "recomputed from raw files by scripts/report/make_report_tables.py; offline",
        "ledger_check": ledger_check, "comparisons": comps, "totals": totals,
        "discrepancies": discrepancies}, indent=1), encoding="utf-8")
    for d in discrepancies:
        print("DISCREPANCY", d)
    print(json.dumps({"ledger_check": ledger_check, "n_runs": len(runs)}, indent=1))
    for c in comps:
        print(c)


if __name__ == "__main__":
    main()
