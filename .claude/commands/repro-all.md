---
description: Run the complete reproduction (tables + figures), verify with the repro-verifier subagent, and document.
argument-hint: [seeds=5] [out=results/repro/<date>]
---
Use the `rfamp-reproduce` skill. Seeds: ${1:-5}. Output dir: ${2:-results/repro/latest}.
Run `python -m orfadc.repro.bench all --seeds <seeds> --out <out>` (long; run in background and poll),
then launch the `repro-verifier` subagent on the output directory, then write docs/1xx_repro_<date>.md.
