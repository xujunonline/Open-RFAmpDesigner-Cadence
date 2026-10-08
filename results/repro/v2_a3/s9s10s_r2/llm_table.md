# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)

fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the ORFADC_LLM_MAX_CALLS cap / circuit breaker.

| spec | policy | variant | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.36 | -20.7 | 4.36 | 23.1 | 536 | 1 | 0 | 0 | 9658491 | 155515 | 9628 | nf |
| S10s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.49 | -20.2 | 4.49 | 26.3 | 525 | 0 | 0 | 0 | 9889220 | 154788 | 8096 | nf |
| S10s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.29 | -20.2 | 4.29 | 24.9 | 533 | 0 | 0 | 0 | 9946522 | 159663 | 9434 | nf |
| S10s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.67 | -20.8 | 4.63 | 23.7 | 412 | 0 | 0 | 0 | 7396132 | 128207 | 7362 | nf |
| S10s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.10 | -21.3 | 3.88 | 23.8 | 497 | 0 | 0 | 0 | 9381192 | 149668 | 7592 | ip1db:stage3 |
| S9s | codex-mcp | v2_r2_calls1000 | surrogate | Y | 0.00 | -19.6 | 4.87 | 24.5 | 75 | 0 | 0 | 0 | 1340262 | 19136 | 1198 | - |
| S9s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.00 | -20.0 | 4.62 | 23.0 | 591 | 0 | 0 | 0 | 10707783 | 166554 | 10054 | ip1db:stage2 |
| S9s | codex-mcp | v2_r2_calls1000 | surrogate | Y | 0.00 | -19.4 | 4.93 | 22.7 | 469 | 0 | 0 | 0 | 8773256 | 138414 | 8456 | - |
| S9s | codex-mcp | v2_r2_calls1000 | surrogate | N | 0.08 | -19.7 | 5.08 | 23.8 | 609 | 1 | 0 | 0 | 11030705 | 166131 | 11235 | nf |
| S9s | codex-mcp | v2_r2_calls1000 | surrogate | Y | 0.00 | -19.8 | 4.72 | 25.9 | 15 | 0 | 0 | 0 | 255554 | 3407 | 273 | - |
