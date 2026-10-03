# Stage 10：三级教学电路的计划式多智能体与不重派对账

## 本轮范围

本轮把 `docs/104` 的公开 MOS1 三级教学候选和 `docs/105` 的 v3/v4 派发/恢复协议接到确定性 `Manager -> Searcher -> Refiner`。Searcher 首轮只给 `L3S=2.0 nH`；Refiner 必须从首轮原始 Spectre 档重算 9–11 GHz 的失败事实，才准给一次 `L3S=4.085532 nH` 的 LC 启发式种子。第二轮只重审并终止。两轮均先在 journal 写计划 run ID，再派发 Spectre；规格、候选、远端身份和证据清单绑定到同一 trace。该流程**没有调用在线 LLM**，也没有将候选判为 LNA 合格。

代码入口：

- `src/orfadc/agents/teaching_three_stage_feedback.py`：受限 Searcher/Refiner；仅一条经原始档支持的反馈路径。
- `src/orfadc/experiments/run_teaching_three_stage_feedback_agent.py`：正常 planned 执行，SSH 回复不确定时只记 pending、不自动重派。
- `src/orfadc/experiments/audit_teaching_three_stage_feedback_agent.py`：从两份原始档重建观察量、候选关系、事件/快照和摘要。
- `src/orfadc/agents/reconcile_pending_teaching_three_stage.py`：已完成档的 pending 接管。若首轮 pending，先接管原首轮，才允许派发**新**第二轮；若第二轮 pending，只接管该轮，不调用 Spectre。缺档、变化、身份不符均拒绝。
- `src/orfadc/experiments/probe_teaching_three_stage_agent_lost_reply.py`：仅用于受控实验，选择第一或第二次真实 Spectre 返回 0 后抑制该次控制端成功回复，再按正式恢复器/对账器处理。

## 新实测与来源

正常 planned trace：`results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba/`。两个新原始档位于同一私有候选根的 `S1/seed0/S1_seed0_teach3_l3s2/20260927T191321Z_263aa75c/` 和 `S1/seed0/S1_seed0_teach3_resonance/20260927T191329Z_ea54c02f/`。journal 与双候选来源审计为 `verified_two_run_teaching_agent_feedback`；9–11 GHz 最差 S21 约 `-1.209947 -> 1.677215 dB`，差约 `+2.887163 dB`；最差 S22 约 `-0.948135 -> -2.071694 dB`。改善是**这个理想教学网络**的一次局部反馈，不是论文的全带合格趋势。

受控第二轮丢回复 trace：`results/runs/teaching_three_stage_agent_feedback/20260927T191949Z_8f1e9695/`。两次真实 Spectre 都已运行，第二次远端真实返回 0；本机包装层只对第二次返回伪造 255。Manager 因此停在第二轮 planned pending，不生成终态 trace。正式恢复器确认原远端作业静止、文件双次哈希稳定并从同一远端目录下载、审计协议 v4 源档；对账器之后接收**同一 run ID**，写 Refine/Stop/trace。独立两源审计通过，重复对账被拒绝。`controlled_lost_reply_report.json` 保存 `spectre_calls_before_recovery=2`、`second_reply_suppressed=true`、`reconciliation_redispatched_second=false`、`physical_ssh_disconnect_tested=false`。这不是运行中物理断线，也不证明跨主机互斥或远端不完整作业可安全重试。

受控**首轮**丢回复 trace：`results/runs/teaching_three_stage_agent_feedback/20260927T200439Z_6577ff6a/`。首轮真实 Spectre 返回 0 后只隐藏本机回复，Manager 留在首轮 planned pending。正式恢复器从**首轮原 run ID**恢复 v4 源档；对账器先将其绑定到原 journal，才按首轮失败观察生成 4.085532 nH 候选并派发**新的第二轮** Spectre。来源分别为 `S1/seed0/S1_seed0_teach3_l3s2/20260927T200439Z_f9eb76c5/` 与 `S1/seed0/S1_seed0_teach3_resonance/20260927T200458Z_569d24e2/`；首轮未重派、第二轮只派一次、最终双源审计通过。`controlled_lost_reply_report.json` 明记 `lost_reply_round=1`、首轮恢复前 `spectre_calls_before_recovery=1`、`new_second_dispatched_after_first_recovery=true`、`physical_ssh_disconnect_tested=false`。这只验证成功原档的接管和继续，不覆盖不完整原档的安全中止。

本地回归还用真实原始档的隔离 journal 副本验证第二轮 v3/v4 接管均不调用远端；首轮 pending 接管后只生成一个**新**第二轮计划，控制其再次不确定时保留新 pending。副本测试不增加真实 Spectre 样本。任何 pending 档没有成功的原始审计均不得用对账入口重发。

若第二轮 Refine 已写入 journal 而 Stop/trace/摘要尚未完成，使用独立的终态收尾器，见 `docs/108_stage10_teaching_agent_terminal_recovery.md`；它只接管已有两份成功源档，不处理 pending 或新仿真。

若首轮 Refine 已写入 journal 而第二轮尚未派发，另有受限续跑入口和一次真实新第二轮 Spectre 验收，见 `docs/109_stage10_teaching_agent_pre_second_resume.md`；第二轮 Evaluate 已计划后仍只能走 pending 对账，不可用续跑入口重复派发。

## 复核与门禁

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage_feedback_agent results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba
python -m orfadc.experiments.audit_teaching_three_stage_feedback_agent results/runs/teaching_three_stage_agent_feedback/20260927T191949Z_8f1e9695
python -m orfadc.experiments.audit_teaching_three_stage_feedback_agent results/runs/teaching_three_stage_agent_feedback/20260927T200439Z_6577ff6a
python -m pytest -q --basetemp="results/runs/pytest_teach3_agent_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_teaching_three_stage_agent.py
```

不要对这两个已完成 trace 再执行 `run_*` 或 `reconcile_*`。若新的 planned trace 处于 pending，先通过 `recover_teaching_three_stage_candidate` 从其**原**远端目录恢复干净完整的原始档，再用 `reconcile_pending_teaching_three_stage <trace_dir>` 对账；缺少原始数据就保持 pending/隔离，不能自动重发。真实运行前仍需检查宿主物理余量、来宾进程与 SSH/Tools 状态。

本轮 agent 两次评估本身仅含 DC/SP/noise；后续已对正常 trace 的第二轮候选另做同电路 HB 扫描及绑定审计，见 `docs/107_stage09_teaching_agent_same_candidate_hb.md`。这仍没有授权有损无源的 Q/k/SRF、合法 CDF/PCell/DRC、模型告警排除和**合格** fullchain；其 50 Ω 输入与 1787 Ω 差分输出为混合端口参考，不能等同论文最终匹配网络。`not_lna_result=true`、`spec_pass=null` 固定；不得填 Table IV/V 或声称 Fig. 7 原曲线复现。下一步处理远端不完整作业的不可重派隔离、授权 PDK 物理器件/匹配与全链门禁，最后才有条件评价在线模型及论文级对照。
