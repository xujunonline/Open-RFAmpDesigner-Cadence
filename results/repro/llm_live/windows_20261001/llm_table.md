# LLM backbone runs (surrogate simulator unless backend = spectre(stage4); trend-level)

fallbacks = LLM answer rejected by validation or call failed; rule-after-cap = rule decisions after the ORFADC_LLM_MAX_CALLS cap / circuit breaker.

| spec | policy | backend | pass | viol | IP1dB | NF | gain_min | LLM calls | errors | fallbacks | rule-after-cap | prompt tok | compl tok | latency s | bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S10 | llm-claude-cli | surrogate | N | 2.83 | -21.5 | 4.14 | 23.2 | 19 | 0 | 0 | 0 | 36120 | 16019 | 287 | ip1db:stage3 |
| S10 | llm-codex-mcp | surrogate | N | 3.72 | -21.2 | 5.17 | 22.9 | 40 | 0 | 0 | 51 | 632744 | 10121 | 894 | ip1db:stage2 |
| S10 | rule | surrogate | N | 3.24 | -22.7 | 4.18 | 24.0 | - | - | - | - | - | - | - | ip1db:stage3 |
| S10s | llm-claude-cli | surrogate | N | 1.37 | -21.1 | 5.32 | 23.4 | 40 | 0 | 0 | 79 | 88283 | 47798 | 734 | ip1db:stage2 |
| S10s | llm-codex-mcp | surrogate | N | 0.68 | -21.3 | 4.58 | 25.2 | 40 | 0 | 0 | 71 | 632534 | 9759 | 815 | ip1db:stage2 |
| S10s | rule | surrogate | N | 0.81 | -21.3 | 4.71 | 23.7 | - | - | - | - | - | - | - | ip1db:stage2 |
| S2 | rule | spectre(stage4) | Y | 0.00 | -22.4 | 4.14 | 25.3 | - | - | - | - | - | - | - | - |
| S9 | llm-claude-cli | surrogate | N | 2.36 | -18.3 | 6.25 | 23.5 | 12 | 0 | 0 | 0 | 26738 | 14948 | 209 | power |
| S9 | llm-codex-mcp | surrogate | N | 1.99 | -15.9 | 6.70 | 22.7 | 40 | 0 | 0 | 89 | 633333 | 10177 | 872 | ip1db:stage2 |
| S9 | rule | surrogate | N | 2.63 | -16.3 | 6.98 | 22.1 | - | - | - | - | - | - | - | ip1db:stage3 |
| S9s | llm-claude-cli | surrogate | N | 1.48 | -23.0 | 5.48 | 25.6 | 40 | 0 | 0 | 0 | 91044 | 46209 | 747 | power |
| S9s | llm-codex-mcp | surrogate | N | 0.96 | -22.9 | 4.88 | 25.5 | 40 | 0 | 0 | 0 | 632452 | 9765 | 801 | ip1db:stage2 |
| S9s | rule | surrogate | N | 0.27 | -20.3 | 5.16 | 24.3 | - | - | - | - | - | - | - | ip1db:stage3 |
