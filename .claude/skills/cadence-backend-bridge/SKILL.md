---
name: cadence-backend-bridge
description: Connect the runnable orfadc.repro pipeline to a real Cadence Spectre/OCEAN environment by implementing the Backend protocol (critical-stage and full-chain simulations returning the surrogate's metric schema), with evidence, budget and safety gates. Use when the user wants PDK/Spectre-level results instead of the surrogate, or asks how to migrate the tool middleware to Cadence.
---

# Bridge the repro pipeline to Cadence

**Status:** v1 is implemented in `src/orfadc/repro/backend_cadence.py` (Spectre macromodel of the same circuit,
`CadenceBackend`, `HybridBackend`), with `bench cadence-check` and `bench design --backend cadence`; details in
`docs/119`. Runs only from the Windows host that can SSH to the Cadence VM (`scripts\windows_llm_cadence_check.ps1`).
The steps below describe v2: replace the macromodels with PDK device instances.

## Contract (must hold exactly)
`Backend.simulate(design: LNADesign, f_hz: np.ndarray, *, upto=None|"stage2", include_match=True,
nominal_load=None) -> dict` with keys `f_hz, gain_db, s11_db, zin, nf_db, nfmin_db, compression{ip1db_dbm,
stages{stage1..3:{ip1db_dbm_if_alone, mechanism}}}, gain_to_g2_db` and, for the full chain,
`gain_to_g3_db, stage_gain_db_at_fc`. `name` must identify the backend (e.g. `cadence_spectre_n65`).

## Mapping
- `LNADesign.summary()` gives every parameter: active (kind, W µm, Vb V, current), Ls/Lg/Lpar (pH), MCR1
  physical (k, L1, L2, R1, R2, C1, C2) and MCR2/MCR3 physical (after `circuit.map_mcr`).
- Netlist: template the Fig. 3 topology (`circuit/spectre/teaching_three_stage_probe.scs` is the closest
  existing template); PDK devices via `config/model_paths.local.yaml` (never committed).
- Analyses: `sp` (+`noise` at fc) for Stage 2 critical runs; `sp`+`noise`+`hb`/`pss` compression sweep for
  Stage 4. Parse with `cadence/psfascii_reader.py`, `hb_metrics.py`, `noise_metrics.py`, `touchstone.py`.
- Stage-1 knowledge DB: replace `device.knowledge_database()` with OCEAN sweeps (cascode W 45–180 µm,
  diff W 45–117 µm step 9, Vb 300–500 mV step 25 mV; paper Sec. II-A).

## Safety & evidence gates (do not relax)
- Remote runs go through `cadence/remote_runner.py` with unique run IDs; respect `docs/113`/`docs/114`
  quarantine rules; no live SSH without an explicit user request.
- A result is `pass` only with `source=cadence_spectre`, finished simulation logs and parsed metrics
  (`tools/cost_functions.fullchain_violations`). Surrogate and Cadence results are never mixed in a table.
- Calibrate `EQUIV_COST_S` from measured wall-clock per simulation class before reporting times.

## Steps
1. Implement `CadenceBackend` in `src/orfadc/repro/backend_cadence.py` (new file) behind the protocol.
2. Unit-test the netlist writer and parsers offline with archived PSF files.
3. One critical-stage smoke → one full-chain smoke → compare against surrogate trends.
4. Run `bench design --spec S2` with the Cadence backend (add a `--backend` flag), then scale out.
