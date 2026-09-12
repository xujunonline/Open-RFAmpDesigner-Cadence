# Third-party Notes

Record cloned project URL, commit hash, license, files reviewed, and any reused code here. Do not copy third-party code into this project before checking license compatibility.

## Verified Source List

| Project | Official URL checked | Notes for this project |
|---|---|---|
| AnalogCoder | https://github.com/laiyao1/AnalogCoder | Reuse benchmark/prompt/simulation-in-loop ideas. Replace PySpice/ngspice backend with Cadence OCEAN/Spectre. |
| EEsizer / LLM-transistor-sizing | https://github.com/eelab-dev/LLM-transistor-sizing redirects to https://github.com/eelab-dev/EEsizer | Reuse iterative LLM sizing loop and result-history context idea. Replace ngspice metrics with RF S-parameter/NF/IP1dB metrics. |
| AutoCkt | https://github.com/ksettaluri6/AutoCkt | Reuse spec/action/reward organization for baselines. Do not assume its simulator setup matches this Cadence flow. |
| AnalogGym | https://github.com/CODA-Team/AnalogGym | Reuse benchmark organization ideas only. |
| SPICEBridge | https://github.com/clanker-lover/spicebridge | Reuse tool-API concept for simulator actions. |
| virtuoso-bridge-lite | https://github.com/Arcadia-1/virtuoso-bridge-lite | Optional bridge between LLM-Agent and Cadence Virtuoso if lab policy allows. |
| ALIGN | https://github.com/ALIGN-analoglayout/ALIGN-public | Later-stage layout direction, not MVP. |
| ngspice | https://github.com/ngspice/ngspice | Open-source simulator fallback for method debugging only. |
| Xyce | https://github.com/Xyce/Xyce | Open-source parallel simulator fallback for method debugging only. |

## Commercial PDK Safety

- Do not copy model files, PCells, extracted netlists, foundry rule decks, or proprietary examples.
- Do not commit absolute PDK paths.
- Sanitize Cadence logs before sharing.
- Public results must name only the process family if allowed by the lab, not confidential model details.
