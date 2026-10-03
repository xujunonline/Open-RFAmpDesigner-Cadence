# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)

fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the ORFADC_LLM_MAX_CALLS cap / circuit breaker.

| spec | policy | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10s | llm-codex-mcp | surrogate | N | - | - | - | - | 54 | 0 | 0 | 0 | 854306 | 13060 | 1128 | - |
| S10s | llm-codex-mcp | surrogate | N | 5.60 | -28.8 | 5.91 | 20.7 | 52 | 0 | 0 | 0 | 822004 | 12871 | 1133 | nf |
| S9s | llm-codex-mcp | surrogate | N | 1.13 | -20.7 | 5.91 | 22.2 | 62 | 0 | 0 | 0 | 983081 | 15467 | 1261 | ip1db:stage2 |
| S9s | llm-codex-mcp | surrogate | N | 1.52 | -21.6 | 5.37 | 22.0 | 60 | 0 | 0 | 0 | 950242 | 14564 | 1253 | ip1db:stage2 |
