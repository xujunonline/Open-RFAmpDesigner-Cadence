---
name: rfamp-paper-audit
description: Audit the RFAmpDesigner paper against this repository — equations (1)(2)(3), Tables I–VI, Fig. 2–11 claims, agent protocol — and report gaps, errata and implementation defects with evidence. Use when asked to check correctness, find inconsistencies between paper/docs/code, or update the audit register.
---

# Paper ↔ project audit

Sources: `references/paper/RFAmpDesigner.pdf` (English original is authoritative),
`references/paper/RFAmpDesigner_中文翻译.md`, `docs/116_project_audit_2026-09-29.md` (issue register B01–B21) and `docs/125` §4.

## Procedure
1. Build/refresh a claim matrix: claim → page/section → code location → test → status
   (`implemented`, `surrogate-only`, `cadence-only`, `missing`, `erratum`).
2. Check equations numerically, not by eye:
   - Eq.(1) `tools/cost_functions.stage2_cost`; Eq.(2) `stage3_cost` (`tests/test_paper_tables.py`).
   - Eq.(3): compare `repro/mcr_eq3.eq3_voltage(variant=...)` to the nodal model
     `tools/mcr_lumped.lumped_mcr_response` (`tests/test_repro_core.py`). Known erratum: the Y11 denominator's
     last term must be `R_S ω0³ Q s`. The "/2" in V(s) is a differential-half convention (≈ −6 dB offset in
     a single-ended equivalent) — report which convention is used.
3. Tables: II ranges → `config/variable_ranges_table_ii.yaml` & `repro/tools.STAGE2_BOUNDS`;
   III specs → `config/specs_table_iii.yaml`; IP1dB(−15) vs OP1dB(9 dBm) is consistent at ~24 dB gain.
4. Protocol: Manager/Searcher/Refiner roles, two modes, KB/EB templates (Fig. 6), back-tracking policy
   (Sec. II-B-4) → `repro/agents.py`, `repro/memory.py`, `repro/prompts/*.md`.
5. Output a prioritized list (P0 wrong-success risk, P1 reliability, P2 docs) with file:line evidence and
   a proposed fix; add a regression test for every code fix; append to the issue register.
