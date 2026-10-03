# Stage 10：三级教学 agent 的终态快照收尾

## 故障窗口

`docs/106_stage10_three_stage_planned_agent.md` 已让公开 MOS1 三级教学候选按 planned journal 完成两轮 Spectre、候选快照和 Refiner 反馈；`reconcile_pending_teaching_three_stage` 处理的是 `EvaluateCandidate` 已写但评估尚未记账的 pending。如果**第二轮 `RefineCandidate` 已写入 journal**，进程却在 `Stop`、`agent_trace.json` 或 `feedback_summary.json` 落盘之前退出，不应把已有候选重跑，也不应把完整原始档留成无法审计的半成品。

`src/orfadc/agents/finalize_teaching_three_stage_agent.py` 在本机 run 锁下先审计两份原始 Spectre 档、远端身份、规格/候选快照、首轮失败事实导出的第二候选、两个清单与 Refine 事件。只接受两轮评估、两轮 Refine 均已 journaled、无 pending 且调度顺序精确匹配的 trace；缺档、来源变化、状态/预算/身份不符、已有完整摘要却无恢复意图均拒绝。**不调用 SSH 或 Spectre。**

通过前置审计后先写 `feedback_terminal_intent.json`，再按需补 `Stop`、终态 trace、来源重建的摘要，最后写 `feedback_terminal_recovery.json`。若 finalizer 自己在这些写入边界中断，下次从相同两份原始档重新审计并核对意图，继续补缺；已完成的恢复报告可重复只读验证，绝不再次派发候选。该机制只证明本机单写者锁与已有成功档案的终态收尾，不是跨控制主机互斥、原始文件不存在时的恢复或不完整远端作业的隔离。

测试将正常真实双源 trace `results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba/` 复制到 Git 忽略的隔离目录，分别截在 Refine 后/Stop 后/trace 后；另模拟 finalizer 写意图后、写 Stop 后及写摘要后的三次中断。两个受控丢回复的真实恢复源 trace `20260927T191949Z_8f1e9695`（第二轮 v4）和 `20260927T200439Z_6577ff6a`（首轮 v4）也各自在隔离副本中经过同样来源核验。全部原始 source 未修改、没有新 Cadence 仿真样本。相关 `tests/test_finalize_teaching_three_stage_agent.py` **10 passed**，包括重复调用、伪造意图及普通已完成 trace 误用的拒绝。结果仍 `not_lna_result=true`、`spec_pass=null`。

```powershell
$env:PYTHONPATH='src'
python -m pytest -q --basetemp="results/runs/pytest_teach3_terminal_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_finalize_teaching_three_stage_agent.py
```

只对**新出现的、第二轮 Refine 已 journaled 且终态缺失**的私有 trace 执行 `python -m orfadc.agents.finalize_teaching_three_stage_agent <trace_dir>`；不要对上面三个原始完整 trace 执行 finalizer，也不要将这一步称为新的 Spectre 样本。首轮 Refine 后、第二轮派发前的继续已另见 `docs/109_stage10_teaching_agent_pre_second_resume.md`；远端非终结/不完整作业的不可重派隔离及授权 PDK 的物理有损无源、CDF/PCell、DRC/模型和合格 LNA fullchain 仍未通过。
