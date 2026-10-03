# Stage 10：三级教学 agent 首轮 Refine 后安全续跑

## 状态边界

`docs/106` 的两轮 planned agent 已能在 `EvaluateCandidate` pending 后按原 run ID 恢复/对账，`docs/108` 能在**第二轮** Refine 已记账后只读补齐终态。两者之间还有一个断点：首轮 `RefineCandidate` 已写入 journal，而第二轮尚未派发。`resume_teaching_three_stage_agent.py` 仅接受两种精确前缀：首轮 Refine 后尚未 Search，或第二轮 `SearchCandidates` 已写且唯一候选在队列中、但没有 `EvaluateCandidate`。若第二轮已派发 pending，必须走原 pending 对账器，**不得调用 resume 重派**。

恢复前先核对规格文件/快照、远端身份、候选快照、预算和 journal；从首轮原始 Spectre DC/SP/noise 档独立重算观察量，并用原 LC 启发式重新计算第二轮 4.085532 nH 候选。只有预期候选与队列快照一致且宿主物理内存过门禁，才写 `feedback_search_resume_intent.json` 并继续。若该入口自身在第二轮 Search 后、Evaluate 前退出，同一意图可再次审计后继续；一旦第二轮 Evaluate 已写，立即转入 pending 对账，不重复派发。正常成功后还需独立双源审计；失败仍为 `teaching_agent_incomplete`，无总体 LNA pass。

## 实际实验

受控实验仅将已审计完整 trace `results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba/` 的前四个事件、第一份候选快照及规格/远端身份字节复制到新私有 trace，模拟首轮 Refine 后进程退出。源首轮 `S1/seed0/S1_seed0_teach3_l3s2/20260927T191321Z_263aa75c/` **直接复用，未再派发**；新 trace `results/runs/teaching_three_stage_agent_resume/20260927T202048Z_e6bdafbe/` 只新派发一次第二轮 Spectre，源档为 `S1/seed0/S1_seed0_teach3_resonance/20260927T202048Z_c3e11b27/`。双源 journal/候选/原始档再审计为 `verified_two_run_teaching_agent_feedback`。隔离夹具不改动原 trace 和旧第二轮源档，新的第二轮只是一次自动化续跑样本，不能作为额外独立 seed 或性能提升证据。

`probe_teaching_three_stage_agent_resume.py` 的受控 runner 在运行时计数 `new_second_spectre_calls=1`。只读审计器核对源/新 trace 的首轮四个 journal 事件和首份候选快照逐字节一致、规格/远端身份一致、首轮源路径相同、第二轮 run ID 不同，并重新审计两轮 raw。**静态归档能证明来源和不同 run ID，单次调用计数来自受控 runner 的运行时记录，不是原始波形单独可证明的事实。**摘要字段篡改会被拒绝。

定向测试用实际首轮原始档的隔离 journal 验证两个可续跑前缀、第二轮不确定时停在新 pending、重复 resume 被拒，以及意图/报告篡改拒绝；和 `docs/108` 的终态测试合计 `14 passed`。没有在线 LLM、授权 PDK、合格 LNA 或论文数值复现。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.probe_teaching_three_stage_agent_resume results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba --audit-dir results/runs/teaching_three_stage_agent_resume/20260927T202048Z_e6bdafbe
python -m pytest -q --basetemp="results/runs/pytest_teach3_resume_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_resume_teaching_three_stage_agent.py tests/test_finalize_teaching_three_stage_agent.py
```

上面的 `--audit-dir` 只读，不派发新 Spectre。不要在既有完整 trace 上再次运行 resume 或 probe。下一门禁是非终结/不完整远端作业的不可重派隔离、跨控制主机事务，以及授权 PDK 有损无源、CDF/PCell、DRC/模型和合格 fullchain；Stage 09/10 与全项目仍 `partial`。
