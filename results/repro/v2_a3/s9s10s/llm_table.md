# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)

fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the ORFADC_LLM_MAX_CALLS cap / circuit breaker.

| spec | policy | variant | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10s | claude-cli | v2_calls1000 | surrogate | Y | 0.00 | -20.7 | 3.87 | 24.1 | 57 | 0 | 0 | 0 | 247295 | 28786 | 588 | - |
| S10s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -20.9 | 3.83 | 24.0 | 450 | 0 | 0 | 0 | 8115194 | 125374 | 7760 | - |
| S10s | codex-mcp | v2_calls1000 | surrogate | N | 0.23 | -21.3 | 4.14 | 22.4 | 519 | 0 | 0 | 0 | 9344948 | 149477 | 8413 | ip1db:stage3 |
| S10s | codex-mcp | v2_calls1000 | surrogate | N | 0.47 | -20.7 | 4.47 | 23.7 | 236 | 0 | 0 | 0 | 4221074 | 63805 | 3959 | nf |
| S10s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -20.8 | 3.83 | 25.0 | 183 | 0 | 0 | 0 | 3271706 | 50595 | 3236 | - |
| S10s | codex-mcp | v2_calls1000 | surrogate | N | 0.37 | -20.0 | 4.37 | 22.3 | 523 | 0 | 0 | 0 | 9408040 | 155654 | 8593 | nf |
| S9s | claude-cli | v2_calls1000 | surrogate | Y | 0.00 | -19.6 | 4.50 | 24.3 | 66 | 0 | 0 | 0 | 305642 | 29321 | 631 | - |
| S9s | codex-mcp | v2_calls1000 | surrogate | N | 0.16 | -19.4 | 5.16 | 23.0 | 529 | 0 | 0 | 0 | 9549087 | 147261 | 9128 | nf |
| S9s | claude-cli | v2_calls1000 | surrogate | Y | 0.00 | -19.6 | 4.76 | 23.6 | 73 | 0 | 0 | 0 | 336631 | 35956 | 759 | - |
| S9s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -19.5 | 4.94 | 26.0 | 588 | 0 | 0 | 0 | 10652705 | 163146 | 10145 | - |
| S9s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -19.2 | 4.90 | 22.3 | 198 | 0 | 0 | 0 | 3570325 | 49961 | 3186 | - |
| S9s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -19.4 | 4.56 | 25.9 | 90 | 0 | 0 | 0 | 1602415 | 21691 | 1462 | - |
| S9s | codex-mcp | v2_calls1000 | surrogate | Y | 0.00 | -19.4 | 4.96 | 24.7 | 175 | 0 | 0 | 0 | 3136404 | 43532 | 2921 | - |
