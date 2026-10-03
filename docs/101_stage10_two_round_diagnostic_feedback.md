# Stage 10：两轮原始证据门禁的共源诊断反馈

## 范围与实测

本轮把确定性 `Manager → Searcher → Cadence evaluator → Refiner → Searcher` 串成两次**新** Spectre 运行。对象仍是私有 Virtuoso OA 共源级导出网表的 RD/VBIAS 白名单派生诊断，不是三级 LNA、论文资源分配或在线 LLM。Refiner 只在首轮原始 PSFASCII/CSV、OA 模板与证据清单重审通过、且中心频点 S21 低于 S1 增益目标时，提出一次 `RD × 1.1`；VBIAS 不变，RD 上界 1000 Ω。无可信原始来源、超界或预算用尽时不生成第二候选。候选快照保持空 `notes`，父 run ID/清单 SHA-256 记在私有反馈摘要中；不能借此放宽全局快照的敏感文本门禁。

| 项目 | 真实观察 |
| --- | --- |
| 私有 trace | `results/runs/agent_diagnostic_feedback/20260927T165301Z_288868af/` |
| 首轮 | `S1_seed0_oa_feedback0`，RD=250 Ω，VBIAS=0.67 V，run `20260927T165301Z_0be1bd66`，中心频点 S21≈1.0778 dB |
| 反馈后 | `S1_seed0_oa_feedback1`，RD=275 Ω，VBIAS=0.67 V，run `20260927T165307Z_f9d006ba`，中心频点 S21≈1.1660 dB |
| 调度 | 两次 Search、两次 Evaluate、两次 Refine；planned run ID、规格/远端身份/候选快照、两份候选证据清单均经 journal 重放绑定 |
| 独立重审 | `audit_diagnostic_feedback_agent.py` 从两次原始 PSFASCII、CSV、OA 模板、清单与快照重算，结论 `verified_two_run_diagnostic_feedback` |
| 验收边界 | 两份运行均 `not_lna_result=true`、`spec_pass=null`；增益微升仅为本共源诊断的单步观察，不能称 LNA 规格通过或论文 Fig./Table 复现 |

`src/orfadc/agents/diagnostic_feedback.py` 是受限的确定性 Searcher/Refiner；`src/orfadc/experiments/run_diagnostic_feedback_agent.py` 调用已有 planned executor 和 Cadence 后端；`src/orfadc/experiments/audit_diagnostic_feedback_agent.py` 是不派发仿真的独立只读重审。真实运行前本机可用物理内存约 3.63 GiB、来宾 `MemAvailable` 约 2.48 GiB、Spectre 进程数 0。受限网表、PDK include、SSH 配置、原始 PSF 和完整日志均留在 Git 忽略的 `results/runs/`，不移入公开文档。

本轮新增定向 `4 passed`，覆盖两轮闭环、原始审计失败后不二次评价、第二轮控制结果不确定时保持 pending，以及规格快照、摘要和源归档篡改拒绝。默认环境全量回归 `931 passed, 7 skipped`（795.94 秒）；规格快照逐字段检查在其后加入并经定向测试与上述真实档重审通过。远端回归后无 Spectre 进程，`git diff --check` 无空白错误，只有既有换行格式提示。

```powershell
$env:PYTHONPATH='src'
$template='results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs'
$hash=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower()
python -m orfadc.experiments.audit_diagnostic_feedback_agent --trace-dir results/runs/agent_diagnostic_feedback/20260927T165301Z_288868af --template $template --template-sha256 $hash
python -m pytest tests/test_diagnostic_feedback.py -q
```

在已有 SSH 控制结果不确定时，新 runner 仅留下 `feedback_pending.json` 和 planned journal，不写终态 trace、摘要或规格通过，不自动重试。第二轮 pending 若远端已形成完整、干净的原始归档，现可经 `docs/102_stage10_second_feedback_pending_recovery.md` 的受限恢复与对账入口处理；真实第二轮 SSH 断线尚未演练，终态失败与不完整档仍须保持 pending。现有一次真实运行中途 SSH 断开且原始结果不完整的旧 trace `docs/100_stage10_live_ssh_disconnect_incomplete.md` 仍保持 pending，本轮不修改它。

## 下一门槛

阶段 10 还需对两轮 pending 建立可审计的终态接管或隔离事务、跨控制进程竞争与端点认证；阶段 11 还需合格 LNA observation、受限模型策略的真实调用与费用记录。阶段 03/08/09 的 CDF/PCell 合法几何、DRC、授权有损无源、模型警告及同候选合格 fullchain 均未通过，因此不能生成 Table IV/V/VI-like 成功数据或 EB 成功经验。
