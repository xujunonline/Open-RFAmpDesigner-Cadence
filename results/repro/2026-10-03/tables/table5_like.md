# Table V-like: S9/S10 (+ surrogate-scaled S9s/S10s) with 5 h budget, ablations (rule policy)

> surrogate backend (open EKV-class model); trend-level, not PDK/silicon. pass@1 over seeds; time = mean equivalent EDA seconds of successful runs (cost model {'hf_critical': 0.5, 'hf_full': 12.0, 'lf': 0.002}); '-' = no success within budget.

`viol` = mean normalised residual violation of the best design per run (0 = pass; gain/ripple/IP1dB/S11/power per 3 dB, NF per 1 dB).

| Spec | ga_subtool pass@1 | ga_subtool time(s) | ga_subtool viol | bo_subtool pass@1 | bo_subtool time(s) | bo_subtool viol | ours pass@1 | ours time(s) | ours viol | ours_no_refiner pass@1 | ours_no_refiner time(s) | ours_no_refiner viol | ours_with_eb pass@1 | ours_with_eb time(s) | ours_with_eb viol |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S9 | 0/5 | - | 1.94 | 0/5 | - | 1.64 | 0/5 | - | 2.18 | 0/5 | - | 2.48 | 0/5 | - | 2.18 |
| S10 | 0/5 | - | 2.23 | 0/5 | - | 2.46 | 0/5 | - | 3.23 | 0/5 | - | 3.18 | 0/5 | - | 3.23 |
| S9s | 1/5 | 15032 | 0.37 | 1/5 | 2956 | 0.61 | 0/5 | - | 0.83 | 0/5 | - | 0.54 | 0/5 | - | 0.83 |
| S10s | 2/5 | 15340 | 0.23 | 3/5 | 9184 | 0.17 | 0/5 | - | 0.58 | 0/5 | - | 0.63 | 0/5 | - | 0.58 |
