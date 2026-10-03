# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)

fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the ORFADC_LLM_MAX_CALLS cap / circuit breaker.

| spec | policy | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10s | llm-codex-mcp | surrogate | N | 2.52 | -28.5 | 2.80 | 23.3 | 63 | 0 | 0 | 0 | 996141 | 16054 | 1174 | ip1db:stage3 |
| S10s | llm-codex-mcp | surrogate | N | 1.53 | -25.3 | 3.21 | 26.2 | 132 | 0 | 0 | 0 | 2089968 | 32829 | 2614 | ip1db:stage3 |
| S10s | llm-codex-mcp | surrogate | N | 3.82 | -32.5 | 2.58 | 22.1 | 65 | 0 | 0 | 0 | 1028580 | 15948 | 1194 | ip1db:stage3 |
| S10s | llm-codex-mcp | surrogate | N | 0.71 | -21.0 | 4.70 | 25.6 | 0 | 3 | 3 | 111 | 0 | 0 | 0 | ip1db:stage1 |
| S10s | llm-codex-mcp | surrogate | N | 0.85 | -21.2 | 4.78 | 25.9 | 0 | 3 | 3 | 125 | 0 | 0 | 0 | ip1db:stage1 |
| S9s | llm-codex-mcp | surrogate | N | - | - | - | - | 55 | 0 | 0 | 0 | 872362 | 13631 | 1026 | - |
| S9s | llm-codex-mcp | surrogate | N | - | - | - | - | 45 | 0 | 0 | 0 | 713092 | 11520 | 862 | - |
| S9s | llm-codex-mcp | surrogate | N | 1.01 | -19.6 | 5.32 | 22.3 | 63 | 0 | 0 | 0 | 998921 | 16717 | 1258 | ripple |
| S9s | llm-codex-mcp | surrogate | N | 1.44 | -19.1 | 6.44 | 24.7 | 39 | 3 | 3 | 114 | 617909 | 9217 | 716 | nf |
| S9s | llm-codex-mcp | surrogate | N | 1.12 | -20.8 | 5.85 | 22.1 | 0 | 3 | 3 | 138 | 0 | 0 | 0 | ip1db:stage3 |
