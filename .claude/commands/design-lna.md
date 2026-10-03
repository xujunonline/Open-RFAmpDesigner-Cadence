---
description: Design an LNA for a spec (Table III id or free-text spec) acting as RFAmpManager via the rfamp MCP tools.
argument-hint: <S1..S10 | "fc=28GHz fbw=20% I=30mA G=25dB NF<4 IP1dB>-20">
---
Use the `rfamp-design-lna` skill for: $ARGUMENTS
Delegate searches to the `rfamp-searcher` subagent and refinement to `rfamp-refiner` when helpful.
Finish with the spec-vs-achieved table, parameter dictionary and the trajectory; label results as surrogate.
