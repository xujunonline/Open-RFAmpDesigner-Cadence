# Stage 10：两轮反馈终态快照缺失的只读收尾

## 故障窗口

第二轮 OA 共源诊断即使原始档已完整，控制进程仍可能在 `RefineCandidate` 事件、`Stop` 事件、`agent_trace.json` 和最终反馈摘要之间中断。`docs/102_stage10_second_feedback_pending_recovery.md` 的 pending 对账仅处理尚未写第二轮 Refine 的状态，不能再次接管已记账的评估。本轮新增 `finalize_feedback_trace.py`，只对已经 journaled 的第二轮 Refine 作终态快照补全；不调用 evaluator、SSH 或 Spectre，也不增加搜索/评估次数。

允许的三个精确前缀：

1. `RunStarted, SearchCandidates, EvaluateCandidate, RefineCandidate, SearchCandidates, EvaluateCandidate, RefineCandidate`；补写 `Stop`、trace 和摘要。
2. 上述事件再加 `Stop`，但尚无 trace；补写 trace 和摘要。
3. `Stop` 及可重放的 trace 已存在，但尚无反馈摘要；只补摘要。

每次在独占本机锁下先核对两份候选/规格/远端身份快照、两份来源清单绑定、OA 模板、Spectre 日志、原始 DC/SP/noise PSFASCII/CSV、首轮低于增益目标的 S21、RD `×1.1` 与 VBIAS 不变、第二轮 `needs_evaluation` 状态。来源缺失、清单变化、快照漂移、已存在完整摘要或不是上述状态均拒绝。终态摘要再次由独立只读审计器重算，所有记录仍 `not_lna_result=true`、`spec_pass=null`。

定向故障注入覆盖三个前缀、第二轮源档被改动与重复执行；又用两份已有真实 Spectre 原始档，加受控远端传输夹具构造 `Refine` 后中断，重审成功。此为**真实 Cadence 原始数据 + 合成控制进程断点**，不是新 Spectre 作业或真实故障事件。新增后的反馈/远端恢复相关定向为 `29 passed`；相关完整回归数字以 `docs/16_implementation_status.md` 最新记录为准。

本轮默认环境完整 Python 回归 `944 passed, 7 skipped`（892.76 秒）。回归后，真实两轮 trace 仍 `complete` 且来源绑定通过；既有在途 SSH 断开、原始文件不完整的 trace 仍 `reconcile_pending_evaluation`。远端无 Spectre 进程，`git diff --check` 退出 0（仅既有换行提示），受限源档与本机 SSH 配置由 Git 忽略。

```powershell
$env:PYTHONPATH='src'
$template='results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs'
$hash=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower()
python -m orfadc.agents.finalize_feedback_trace --trace-dir <incomplete-feedback-trace> --template $template --template-sha256 $hash
python -m orfadc.experiments.audit_diagnostic_feedback_agent --trace-dir <incomplete-feedback-trace> --template $template --template-sha256 $hash
python -m pytest tests/test_diagnostic_feedback.py tests/test_recover_pending_remote.py -q
```

`<incomplete-feedback-trace>` 只代表新发现、已独立检查为三种前缀之一的私有 trace；不能用于已有完整 run，也不能把 `docs/100_stage10_live_ssh_disconnect_incomplete.md` 的无终结行 pending 归档转为成功。第二轮**终态 Spectre 失败**及缺失/截断原始文件的隔离事务仍未实现；跨主机锁、端点认证、授权 PDK CDF/PCell/DRC、物理无源及合格 LNA fullchain 仍是独立门禁。
