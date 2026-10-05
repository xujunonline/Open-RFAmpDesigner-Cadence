---
name: cadence-backend-bridge
description: Run, extend or debug the Cadence/Spectre backends of the orfadc.repro pipeline (Spectre macromodel check, PDK device backend, PDK characterisation) with the evidence, budget and safety gates. Use when the user wants PDK/Spectre-level results instead of the surrogate, asks how the Cadence backends work, or wants to move to another PDK/VM.
---

# Cadence / PDK backends of orfadc.repro

**Status (v1.1):**
- Spectre macromodel backend: `src/orfadc/repro/backend_cadence.py` (`CadenceBackend`, `HybridBackend`);
  `bench cadence-check --spec S2` cross-checks the two-port engine; `bench design --backend cadence` (docs/119 §4.1).
- PDK backend: `repro/pdk_v2.py` (inventory, characterisation, `PdkCadenceBackend`, `--backend pdk`),
  `repro/pdk3.py` (stage-1 three-port Y, diff-stage Y, cascode noise), `repro/pdk_fit.py` (device fit, large-signal 1 dB).
  Results: docs/120–127 (illustrative-PDK pass@1 34/40 on TSMC 40 nm LP RF). New VM IC618_rf: docs/128.
- Runs only from the Windows host that can SSH to the Cadence VM; host/port/user come from the git-ignored
  `config/remote_cadence.local.yaml`, PDK paths from `config/model_paths.local.yaml` (templates: `*.example.yaml`).

## Contract (must hold exactly)
`Backend.simulate(design: LNADesign, f_hz: np.ndarray, *, upto=None|"stage2", include_match=True,
nominal_load=None) -> dict` with keys `f_hz, gain_db, s11_db, zin, nf_db, nfmin_db, compression{ip1db_dbm,
stages{stage1..3:{ip1db_dbm_if_alone, mechanism}}}, gain_to_g2_db` and, for the full chain,
`gain_to_g3_db, stage_gain_db_at_fc`. `name` identifies the backend (`cadence_spectre_macromodel_v1`,
`cadence_spectre_<pdk name>`, `hybrid(<inner>-><final>)`).

## Safety & evidence gates (do not relax)
- No ssh/scp, `cadence-check`, `pdk-*` or `--backend cadence|pdk` without an explicit user request
  (CLAUDE.md rule 2; `.claude/hooks/guard_bash.py` asks for confirmation). Announce the expected Spectre count first,
  stay under the user-approved cumulative cap, set `ORFADC_SPECTRE_MAX_PER_DESIGN`, never re-dispatch an uncertain run.
- A design passes only when Spectre evaluated it and `repro/tools.spec_check` reports no violation.
  Surrogate, macromodel and PDK results are never mixed in one table.
- PDK-derived device data stays in git-ignored `results/runs/` and `results/windows_checks/`; never print PDK paths.

## Moving to another PDK / VM (e.g. IC618_rf, CRN65LP)
1. User updates `config/remote_cadence.local.yaml` (host/user) for the new VM.
2. `bench pdk-inventory` (read-only, 0 Spectre) → fills `config/model_paths.local.yaml` (toplevel, section, nmos, lr, wr_um, vdd).
3. `bench pdk-characterize`, `pdk-characterize3`, `pdk-characterize-casc` (announce Spectre counts), then `pdk-check --spec S2`.
4. Re-run the paper-budget pass@1 (docs/127) and label results with the new PDK name.
