# Multi-seed LLM backbone summary (surrogate simulator; trend-level, not silicon/PDK results)

viol = normalised residual violation of the reported design (0 = all specs met; runs that reported no design are left out, see 'reported'); best-eval = least violation among all full-chain evaluations of the run; calls/tokens per run.

| spec | policy | seeds | pass | reported | viol mean | viol median | best-eval mean | best-eval median | calls mean | tokens mean | fallbacks | rule-after-cap | errors | equiv s mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10 | rule | 5 | 0/5 | 5/5 | 3.225 | 3.244 | 3.128 | 3.206 | - | - | - | - | - | 18001 |
| S10 | codex-mcp | 5 | 0/5 | 5/5 | 4.341 | 3.724 | 2.569 | 2.565 | 38.6 | 620209 | 0 | 207 | 0 | 15497 |
| S10 | claude-cli | 1 | 0/1 | 1/1 | 2.827 | 2.827 | 2.827 | 2.827 | 19.0 | 52139 | 0 | 0 | 0 | 5182 |
| S10s | rule | 5 | 0/5 | 5/5 | 0.583 | 0.709 | 0.283 | 0.283 | - | - | - | - | - | 18001 |
| S10s | codex-mcp | 5 | 0/5 | 5/5 | 1.259 | 1.185 | 0.640 | 0.662 | 40.0 | 642549 | 2 | 396 | 2 | 18006 |
| S10s | claude-cli | 1 | 0/1 | 1/1 | 1.369 | 1.369 | 0.417 | 0.417 | 40.0 | 136081 | 0 | 79 | 0 | 18000 |
| S9 | rule | 5 | 0/5 | 5/5 | 2.180 | 2.156 | 1.783 | 1.726 | - | - | - | - | - | 18001 |
| S9 | codex-mcp | 5 | 0/5 | 3/5 | 2.328 | 2.077 | 1.798 | 1.825 | 39.4 | 633270 | 1 | 253 | 1 | 12918 |
| S9 | claude-cli | 1 | 0/1 | 1/1 | 2.364 | 2.364 | 2.331 | 2.331 | 12.0 | 41686 | 0 | 0 | 0 | 1897 |
| S9s | rule | 5 | 0/5 | 5/5 | 0.834 | 0.930 | 0.222 | 0.216 | - | - | - | - | - | 18000 |
| S9s | codex-mcp | 5 | 0/5 | 5/5 | 1.367 | 1.488 | 0.331 | 0.273 | 40.0 | 644088 | 0 | 434 | 0 | 15572 |
| S9s | claude-cli | 1 | 0/1 | 1/1 | 1.478 | 1.478 | 0.221 | 0.221 | 40.0 | 137253 | 0 | 0 | 0 | 4991 |
