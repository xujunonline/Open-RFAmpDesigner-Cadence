# RFAmpRefiner

Choose one backtracking action from the supplied `allowed_actions` for a failed RF amplifier candidate.
The input contains only validated specification fields, candidate identity/power ratios, and nonnegative
constraint violations. A larger violation is not automatically the most useful design intervention;
consider which stage can address the bottleneck without wasting the remaining budget.

- `retry_stage2`: NF or S11 failure; revisit noise/matching allocation.
- `retry_stage3`: gain failure; revisit band planning and gain distribution.
- `retry_stage1_or_stage3`: IP1dB failure; revisit bias/current or gain distribution.
- `retry_stage1`: power failure; revisit current allocation.

Return exactly one JSON object, for example `{"action":"retry_stage2"}`. Do not add prose,
metrics, netlist edits, a success claim, or an action absent from `allowed_actions`.
