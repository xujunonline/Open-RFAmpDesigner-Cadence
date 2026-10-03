# RFAmpDesigner reproduction run

*surrogate backend (open EKV-class model); trend-level, not PDK/silicon*

- generated: 2026-10-03 05:37:43
- cost model (equivalent seconds): {'hf_critical': 0.5, 'hf_full': 12.0, 'lf': 0.002}

# Table IV-like: first 8 tasks (1 h equivalent budget)

> surrogate backend (open EKV-class model); trend-level, not PDK/silicon. pass@1 over seeds; time = mean equivalent EDA seconds of successful runs (cost model {'hf_critical': 0.5, 'hf_full': 12.0, 'lf': 0.002}); '-' = no success within budget.

`viol` = mean normalised residual violation of the best design per run (0 = pass; gain/ripple/IP1dB/S11/power per 3 dB, NF per 1 dB).

| Spec | ga_vanilla pass@1 | ga_vanilla time(s) | ga_vanilla viol | bo_vanilla pass@1 | bo_vanilla time(s) | bo_vanilla viol | ga_subtool pass@1 | ga_subtool time(s) | ga_subtool viol | bo_subtool pass@1 | bo_subtool time(s) | bo_subtool viol | ours pass@1 | ours time(s) | ours viol |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 0/5 | - | 0.81 | 0/5 | - | 0.44 | 0/5 | - | 1.21 | 1/5 | 3506 | 0.68 | 5/5 | 1833 | 0.00 |
| S2 | 1/5 | 3540 | 0.37 | 4/5 | 774 | 0.04 | 0/5 | - | 0.50 | 2/5 | 2984 | 0.37 | 5/5 | 994 | 0.00 |
| S3 | 0/5 | - | 1.28 | 1/5 | 3384 | 0.27 | 0/5 | - | 1.35 | 0/5 | - | 1.42 | 0/5 | - | 1.83 |
| S4 | 3/5 | 2804 | 0.07 | 5/5 | 1114 | 0.00 | 1/5 | 2854 | 0.17 | 4/5 | 1570 | 0.01 | 5/5 | 1004 | 0.00 |
| S5 | 0/5 | - | 1.09 | 1/5 | 1080 | 0.39 | 0/5 | - | 2.65 | 0/5 | - | 1.30 | 4/5 | 1932 | 0.17 |
| S6 | 0/5 | - | 3.34 | 0/5 | - | 1.83 | 0/5 | - | 3.74 | 0/5 | - | 3.52 | 0/5 | - | 2.19 |
| S7 | 0/5 | - | 2.37 | 0/5 | - | 1.25 | 0/5 | - | 1.46 | 0/5 | - | 0.68 | 0/5 | - | 2.19 |
| S8 | 0/5 | - | 0.89 | 0/5 | - | 0.16 | 0/5 | - | 1.60 | 0/5 | - | 0.88 | 3/5 | 1903 | 0.06 |


# Table V-like: S9/S10 (+ surrogate-scaled S9s/S10s) with 5 h budget, ablations (rule policy)

> surrogate backend (open EKV-class model); trend-level, not PDK/silicon. pass@1 over seeds; time = mean equivalent EDA seconds of successful runs (cost model {'hf_critical': 0.5, 'hf_full': 12.0, 'lf': 0.002}); '-' = no success within budget.

`viol` = mean normalised residual violation of the best design per run (0 = pass; gain/ripple/IP1dB/S11/power per 3 dB, NF per 1 dB).

| Spec | ga_subtool pass@1 | ga_subtool time(s) | ga_subtool viol | bo_subtool pass@1 | bo_subtool time(s) | bo_subtool viol | ours pass@1 | ours time(s) | ours viol | ours_no_refiner pass@1 | ours_no_refiner time(s) | ours_no_refiner viol | ours_with_eb pass@1 | ours_with_eb time(s) | ours_with_eb viol |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S9 | 0/5 | - | 1.94 | 0/5 | - | 1.64 | 0/5 | - | 2.18 | 0/5 | - | 2.48 | 0/5 | - | 2.18 |
| S10 | 0/5 | - | 2.23 | 0/5 | - | 2.46 | 0/5 | - | 3.23 | 0/5 | - | 3.18 | 0/5 | - | 3.23 |
| S9s | 1/5 | 15032 | 0.37 | 1/5 | 2956 | 0.61 | 0/5 | - | 0.83 | 0/5 | - | 0.54 | 0/5 | - | 0.83 |
| S10s | 2/5 | 15340 | 0.23 | 3/5 | 9184 | 0.17 | 0/5 | - | 0.58 | 0/5 | - | 0.63 | 0/5 | - | 0.58 |


## Fig. 5-like (multi-fidelity band planning)

- equivalent time: multi-fidelity 38 s vs simulation-based 4344 s (**99% reduction**; paper: 88%)
- Eq. 3 per-stage gain error vs high-fidelity simulation (60 random MCR points):

  - `printed_half`: mean -2.37 dB, std 9.79 dB, rms 10.07 dB
  - `corrected_half`: mean -7.06 dB, std 2.03 dB, rms 7.35 dB
  - `corrected`: mean -1.19 dB, std 2.15 dB, rms 2.46 dB

## Fig. 10-like (self-evolution, gain 20..45 dB, IP1dB = -(gain+5) dBm)

| method | tasks solved | cumulative equivalent time (s) | per-task mean (s) |
|---|---|---|---|
| ours_eb | 18/18 | 3348 | 1860, 297, 97, 93, 111, 891 |
| ga_vanilla | 14/18 | 11620 | 3600, 2648, 1756, 1112, 1180, 1324 |
| bo_vanilla | 16/18 | 5292 | 2712, 512, 1088, 236, 352, 392 |

Figures: fig10_like.png, fig5_like.png, fig7_like.png, fig8_like.png
