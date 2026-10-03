# Stage 10：第二轮反馈 pending 的成功归档恢复与对账

## 目的与适用范围

`docs/101_stage10_two_round_diagnostic_feedback.md` 的确定性 Manager/Searcher/Refiner 已实测两次新 Cadence Spectre 共源级诊断。若**第二轮**计划派发后控制端返回不确定，journal 留在 `reconcile_pending_evaluation`。本轮为这个严格限定的状态增加两步只读接管：先从远端静止目录取回已完成的第二轮原始结果，再把已归档的第二轮结果写入原有 journal 的终态。两个入口均不运行或重发 Spectre。

| 入口 | 前置条件 | 输出 |
| --- | --- | --- |
| `recover_pending_remote.py --feedback-second` | 两次 Search/两次 Evaluate；首轮 Refine 已绑定真实原始归档且提出 10% RD 步长；第二轮 planned ID 未结束；远端进程静止、两次原始文件哈希一致、0-error Spectre 完成标志、下载后再次核哈希 | 同一 planned run ID 下的私有第二轮 `netlist.scs`、ADE 伴随文件、日志、DC/SP/noise PSFASCII、`recovery_provenance.json`、指标和证据清单；journal **仍 pending** |
| `reconcile_pending_feedback.py` | 两轮候选快照、规格快照、远端身份、首轮清单/原始 PSF、第二轮清单/原始 PSF、RD/VBIAS 映射及远端恢复来源均一致；规格文件未漂移 | 原 journal 追加第二轮 Refine 和 Stop，写 `agent_trace.json`、`diagnostic_feedback_summary.json`、`feedback_reconciliation.json`；独立审计器重建两轮摘要 |

第二轮只允许 `S1_seed0_oa_feedback1` 形式的同 spec/seed ID（具体 ID 由 trace 绑定）、空 `notes`、RD 白名单与首轮 `RD × 1.1`、相同 VBIAS。首轮 S21 必须确实低于目标增益。恢复归档还要把远端目录哈希及身份摘要绑定到原 trace，不能从其他作业借原始数据。现有单候选恢复分支保持不变；新分支必须显式传 `--feedback-second`。

## 验证证据

本轮使用 `20260927T165301Z_0be1bd66`（RD=250 Ω）与 `20260927T165307Z_f9d006ba`（RD=275 Ω）的**已有真实 Cadence 原始归档**，在私有临时目录构造第二轮 planned pending。受控传输夹具只复制第二轮真实源档的六项原始文件，并提供两次稳定哈希观察；恢复器实际执行原始 PSFASCII 提取与归档审计，对账器再复审两轮来源。测试确认原 journal 从 pending 转为 complete、成功摘要可独立重建、没有 Spectre 调用或控制端 stdout/stderr 伪造。篡改首轮来源、缺少第二轮归档、规格文件漂移均在改写 journal 前拒绝。相关三模块定向 `26 passed`，属于**真实 Cadence 数据 + 合成 pending/传输协议测试**，不是新发生的 SSH 故障，也不是新 Cadence 运行。

补充拒绝已完成真实 trace 再次接管、远端无 clean completion 不下载的负例后，三模块定向为 `28 passed`。默认环境全量 Python 回归 `939 passed, 7 skipped`（864.52 秒）；真实两轮源档再审仍通过，既有运行中 SSH 中断的不完整 trace 仍 pending，远端 Spectre 进程数为 0。`git diff --check` 无空白错误，仅既有换行格式提示；私有源档与连接配置均被 Git 忽略。

```powershell
$env:PYTHONPATH='src'
$template='results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs'
$hash=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower()
# 仅对检查后确认为第二轮 planned pending 的新 trace 执行，不要对旧已完成 trace 重跑。
python -m orfadc.agents.recover_pending_remote --trace-dir <pending-trace> --template $template --template-sha256 $hash --feedback-second
python -m orfadc.agents.reconcile_pending_feedback --trace-dir <pending-trace> --template $template --template-sha256 $hash
python -m orfadc.experiments.audit_diagnostic_feedback_agent --trace-dir <pending-trace> --template $template --template-sha256 $hash
python -m pytest tests/test_diagnostic_feedback.py tests/test_recover_pending_remote.py tests/test_reconcile_pending.py -q
```

`<pending-trace>` 必须替换为**另一条新 trace** 的私有绝对/相对路径；文中的两份成功源档和已完成 trace 不可再次派发或接管。上述过程尚未在真实第二轮 SSH 断线下演练。若远端仍在运行、文件缺失/变化、日志不具备 clean completion、下载不一致、原始审计失败，就保持 pending，不发布结果、不重发。第二轮**终态 Spectre 失败**的单独恢复/对账尚未扩展；前一轮 `docs/100_stage10_live_ssh_disconnect_incomplete.md` 的无终结行旧档也保持 pending。所有结果 `not_lna_result=true`、`spec_pass=null`，不构成 LNA 或论文 Table/Fig. 验收。
