
Additional rules (prompt revision 2, docs/133 §6):
- Always keep at least one refined design: if no refinement has been run yet and the queue is not empty, refine the
  best queued candidate before your third `search_candidates`, even when its critical-stage NF misses the target.
  A run that only searches reports no design at all; a refined near-miss is always more useful.
- When every searched allocation misses NF at Stage 2, the limit is the device, not the allocation: stop searching
  new splits, refine the queued candidate with the lowest critical-stage NF, and `finish` with that report.
- Before proposing a power_ratio_list, compare it with TASK.splits_tried; a repeated allocation is rejected and
  wastes a turn. If an error lists untried neighbouring allocations, pick one of them or a clearly different one.
