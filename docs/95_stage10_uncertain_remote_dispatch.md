# Stage 10：计划式远端派发不确定状态

## 问题与修复范围

单候选 OA 诊断 agent 在派发前写入唯一 `run_id`。此前 SSH/Spectre 返回 124 后，后端仍会生成终态失败清单，Manager 随即记录 `RefineCandidate`/`Stop`。124 可能来自远端 `timeout`，也可能来自控制机等待超时；仅凭返回码不能证明来宾 Spectre 已停止。SSH 返回 255 或派发调用抛异常同样不能证明远端未执行。因此，计划式诊断路径必须先保留 pending，绝不自动重发相同候选。普通单独运行的诊断命令维持原有失败归档行为。

`run_agent_diagnostic` 现在启用 `preserve_uncertain_dispatch`。派发结果为 124/255 或调用异常时：

1. 保留预先写入的 `agent_events.jsonl`、候选/规格/远端身份快照及 planned run ID；不写 `Stop`、`agent_trace.json` 或声称有评估结果。
2. 本地候选目录保留 `netlist.scs`、可用的 `ade_e.scs` 和 `candidate.json`；有返回码时把控制端 stdout/stderr 与无敏感命令的状态 JSON 放在 `control_attempt/`，不占用恢复器要求空缺的顶层控制日志。
3. 不写 `metrics.json`、`evidence_manifest.json`、`spec_pass=true`。`agent_evaluation.json` 只报告 `pending_remote_evaluation`、`candidate_evidence_status=pending`、`spec_pass=null`，保留 trace 目录与候选 run ID 供排查。
4. 仅限已完成派发请求后的不确定结果。上传前的明确失败仍按现有终态处理；非 124/255 的 Spectre 失败也仍归档失败。此处理不把失败说成成功。

## 安全恢复顺序

使用真实受限模板、匹配的 SHA-256 和相同 SSH 配置，均在本机 Git 忽略的私有目录中操作。先通过 `python -m orfadc.agents.inspect_pending_remote --trace-dir <私有trace目录> --config <私有配置> --stable-artifacts` 做只读探查。`spectre_in_flight`/`remote_unknown` 时停止，不再派发；`dispatch_not_observed` 也不是可安全重发的证明。只有来宾目录静止、原始文件齐全且 Spectre 日志有干净完成标记时，才用 `python -m orfadc.agents.recover_pending_remote --trace-dir <私有trace目录> --config <私有配置> --template <私有OA模板> --template-sha256 <模板SHA256>` 下载并逐文件比对。恢复器不会启动 Spectre。随后用 `python -m orfadc.agents.reconcile_pending --trace-dir <私有trace目录> --spec S1 --seed 0 --template <私有OA模板> --template-sha256 <模板SHA256>` 对账，并以 journal 审计及 `agent_reconciliation.json` 为终态依据。最初的 `agent_evaluation.json` 是派发时快照，恢复后不作为最终状态。

远端已静止但日志无干净完成标记、文件缺失或哈希变动时，成功恢复器会拒绝。现在另有 `docs/96_stage10_terminal_failure_recovery.md` 所述的**仅限单一非零错误终结行**的失败恢复与对账；纯许可证等待、文件不稳定或没有终结证据仍保持 pending，**不能**直接重发或手工填造指标。跨主机连接、模板、候选或规格不一致时也拒绝。此机制只覆盖受限 RD/VBIAS OA 共源诊断，不是合格 LNA fullchain 或论文多智能体的验收。

对账器现可接受真实 pending 入口留下的 `agent_evaluation.json`，但只在其全部字段与 planned journal 的规格、候选、run ID、预算和“未有结果”状态一致时接收。它仍拒绝已有终态索引和被改写的 pending 索引。`inspect_pending_remote --stable-artifacts` 会把原始文件缺失/变化与仅静止目录分开报告；即便双次哈希稳定，也必须由恢复器再验证结束标记和原始数据。

## 验证

单元测试覆盖返回码 124/255、派发异常、journal 无终态以及携带嵌套控制日志的原始结果恢复与对账；另有从 `run_diagnostic_agent` 的真实 pending 索引出发，经既有私有干净源档模拟远端下载、拒绝篡改索引、恢复原索引后对账的端到端协议测试。这些仍是模拟远端返回，不是真实的 SSH 断线演练。若未来要宣称真实在途恢复，仍需在授权测试环境做可控断线实验，记录来宾进程和原始文件快照，证明没有重复 Spectre 任务。
