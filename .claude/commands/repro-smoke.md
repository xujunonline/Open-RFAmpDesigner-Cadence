---
description: Run the offline repro unit tests and an S2 smoke design; summarise the result.
---
Run in the repository root with PYTHONPATH=src:
1. `python -m pytest tests/test_repro_core.py -q`
2. `python -m orfadc.repro.bench smoke --out results/repro/smoke`
Report pass/fail, HF simulation count, equivalent time and the achieved S2 metrics vs spec in a small table.
