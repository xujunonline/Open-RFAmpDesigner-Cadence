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
