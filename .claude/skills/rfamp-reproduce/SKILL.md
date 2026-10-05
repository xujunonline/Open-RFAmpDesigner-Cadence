---
name: rfamp-reproduce
description: Reproduce (fully or partially) the RFAmpDesigner paper results with the offline surrogate pipeline — Table IV-like (S1–S8 vs GA/BO baselines), Table V-like (S9/S10, ablations), Fig. 5 (multi-fidelity), Fig. 7/8 and Fig. 10 (self-evolution) — then verify and document them. Use when asked to run, re-run, compare or explain reproduction results.
---

# Reproduce the paper's results

## Steps
1. Environment: `python -m pip install -r config/requirements_repro.txt`; set `PYTHONPATH=src`.
2. Sanity: `python -m pytest tests/test_repro_core.py -q` must be green.
3. Smoke (≈10 s): `python -m orfadc.repro.bench smoke --out results/repro/smoke` → S2 must pass.
4. Full: `python -m orfadc.repro.bench all --seeds 5 --out results/repro/<YYYYMMDD>` (2 CPU cores ≈ 1.5 h; ≈ 3 h on the Windows host).
   Partial: `table4 --specs S1,S2,S4`, `table5`, `fig5`, `fig10`.
5. Verify (use the `repro-verifier` subagent): every number in `SUMMARY.md` must be recomputable from
   `raw/*.jsonl`; pass@1 = successes/seeds; time = mean equivalent seconds of successful runs.
6. Compare with the paper (Table IV/V, Fig. 5b 88 %, Fig. 10 5.5×) as **trends**:
   - tool middleware ≥ subtool ≥ vanilla in pass@1 and time;
   - multi-fidelity band planning ≪ simulation-based time;
   - with EB/KB the cumulative simulation cost grows sub-exponentially across the gain-20→45 sequence.
   Explain every mismatch (surrogate device, cost model, rule vs LLM policy) instead of hiding it.
7. Record: write `docs/1xx_repro_<date>.md` (command, commit, raw paths, table, deviations), update
   `docs/00_index.md`. Never copy surrogate numbers into claims about PDK/silicon.

## Knobs
- `repro/tools.py: EQUIV_COST_S` equivalent EDA seconds per simulation class.
- `repro/device.py: TechParams` surrogate device; `repro/circuit.py: Q_IND, Q_MATCH, CASCODE_RATIO`.
- Budget: `bench.budget_for` (1 h S1–S8, 5 h S9/S10, as in the paper).
- LLM backbone runs without API keys: `bench llm-check --policy claude-cli|codex-mcp` first, then `bench design --policy claude-cli|codex-mcp` (Claude Pro / ChatGPT subscriptions; cap with ORFADC_LLM_MAX_CALLS: code default 200, quota-guard runs 40, paper-aligned runs 1000; see docs/119, docs/127). API-key variants: `--policy anthropic|openai`.
