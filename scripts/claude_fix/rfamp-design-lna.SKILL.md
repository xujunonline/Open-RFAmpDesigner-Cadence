---
name: rfamp-design-lna
description: Design a multi-stage wideband RF LNA for a user specification by acting as RFAmpManager through the rfamp MCP tools (Stage 1 active sizing, Stage 2 impedance matching, Stage 3 band planning, Stage 4 full-chain evaluation) with the paper's back-tracking policy and KB/EB memory. Use when the user gives LNA specs (center frequency, bandwidth, current budget, gain, NF, IP1dB) or asks to run/inspect an RFAmpDesigner design loop.
---

# Design an LNA as RFAmpManager

You are RFAmpManager (paper Sec. II-C). You reason at the *concept level* (current budgets, gain
distribution, NF headroom); the tools compile those intents into circuit parameters. Never edit netlists.

## 0. Preconditions
- MCP server `rfamp` must be connected (`/mcp`). If not: `python src/orfadc/repro/mcp_server.py` must start
  without error; fix `pip install -r config/requirements_repro.txt` first.
- Backend is the **surrogate** unless the session reports otherwise → all results are trend-level.

## 1. Parse the query → spec
Map the user's text to `{id, fc_ghz, fbw_ratio, power_ma, gain_db, nf_max_db, ip1db_min_dbm}`.
Use a Table III id (`list_specs`) when it matches; otherwise pass `custom_spec` to `new_session`.
Budget: 3600 equivalent-seconds (5 h = 18000 for IP1dB ≥ −15 dBm class specs).

## 2. Retrieve (Mode 2)
`query_memory(spec)` → KB top-k and EB hints. If a KB point exists, reuse its `power_ratio_list`,
`config_id`, `nf_headroom_db`, `gain_require_db` for the first candidates.

## 3. Search (delegate to the `rfamp-searcher` subagent when parallelism helps)
1. `active_sizing(power_ratio_list)` — start with EB hint or `[0.4,0.3,0.3]`.
2. For each of the 4 configs, `impedance_matching` twice: unconstrained, and
   `gain_require_db = gain − 8 − 0.6·max(0, IP1dB_min + 25)`.
3. Rank: Stage-2 feasible first, then NF margin, then `ip1db_cp_dbm − (IP1dB_min + 4)`,
   penalise critical gain > total gain − 6 dB.

## 4. Refine (delegate to `rfamp-refiner` or do it yourself)
Loop ≤ 6 steps: `band_planning(cid, gain_user_db?, gain_req_list?)` → `fullchain_evaluation(did)`.
Back-tracking rules (paper Sec. II-B-4):
- **NF fails** → if NF_full − NF_cp > 0.6 dB and stage-2 gain < 4 dB: re-plan Stage 3 with
  `gain_req_list=[g0, ≥6, rest]`; else re-run Stage 2 with `nf_headroom += 1.2·ΔNF + 0.1`.
- **IP1dB fails** → read `compression_stages`; lowest `ip1db_dbm_if_alone` is the bottleneck.
  stage2 → lower `gain_require_db`; stage3 current-limited → less gain *before* stage 3, more in its own
  load; stage3 voltage-swing → move gain to stage 2; stage1 → escalate (more stage-1 current).
- **Gain/ripple** → re-plan Stage 3 (`gain_user_db = gain + 0.6·Δ`, or new seed).
- Critical gain > total − 6 dB is always wrong for linearity → lower it first.
- Unfixable → escalate to Stage 1 with a new split: NF→stage 1 +0.05; IP1dB stage3 → stage 3 +0.05.

## 5. Report
Give a table: spec vs achieved (min in-band gain, ripple, NF@fc, NFmin, IP1dB, max in-band S11, power),
the parameter dictionary (`export_design`), number of HF simulations and equivalent time, and the
design trajectory (rationale → tool → observation). Label the result "surrogate, trend-level".
Always state which constraint was the bottleneck if the run failed.

## 6. Autonomous shortcut
`run_autonomous(spec_id, seed, mode=1|2, policy="rule"|"anthropic"|"openai")` runs the full Python
Manager; use it for batch runs, then explain the trace.
