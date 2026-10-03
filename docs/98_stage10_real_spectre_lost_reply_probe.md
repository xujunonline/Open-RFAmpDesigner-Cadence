# Stage 10：真实 Spectre 完成后的受控回复丢失与 pending 恢复

## 目的与故障注入边界

`docs/95_stage10_uncertain_remote_dispatch.md` 至 `docs/96_stage10_terminal_failure_recovery.md` 已有 planned run ID、静止文件下载和失败收尾协议，但先前恢复实验依赖历史已完成源档或模拟远端返回。本轮对**新**单候选 OA 共源诊断运行一次授权 Spectre：远端命令真实返回 0 后，实验 runner 才将**控制端看到的这一条返回**替换为 255。`run_agent_diagnostic` 因而保留 pending journal，而不下载/发布终态指标。普通 SSH 命令不受注入影响，Spectre 命令只允许一次。真实返回码和注入状态写在 Git 忽略的私有 trace 中。

这不是网络物理断线、在途 Spectre 进程失联，也不是 Cadence LNA。注入发生于仿真完成后；它只覆盖“完成结果存在但控制端未收到可信成功回复”的一种事务不确定性。未更改授权 PDK、许可证、虚拟机配置或既有 OA cell。宿主可用物理内存约 3.75 GiB、来宾约 2604 MiB，派发前无 Spectre 进程；回合后进程空闲。

## 实际运行与证据

| 环节 | 私有证据与结果 |
| --- | --- |
| 新 planned 派发 | trace `results/runs/agent_lost_reply_probe/20260927T153616Z_49c96fc3/`；S1/seed0，单个 RD/VBIAS 白名单诊断候选；仅一次真实 Spectre 调用，原返回码 0，注入后 agent 索引为 `pending_remote_evaluation` |
| 只读远端探查 | `pending_remote_probe_20260927T153636Z_966961da.json`；同一远端目录存在，未见 Spectre，日志及 SP/noise 原始文件存在；两次哈希观察为 `stable_unverified`，`safe_to_dispatch=false` |
| 原始结果恢复 | 候选 `results/runs/S1/seed0/S1_seed0_oa_diag/20260927T153616Z_4ebfbe90/`；恢复器无 Spectre 派发，远端下载前后哈希一致，OA 网表/伴随文件与 planned 候选相同；47 点 DC/SP/noise 重提取、清单与独立只读审计通过；后端 `ok_with_warnings` |
| 对账 | `agent_reconciliation.json` 为 `reconciled_existing_diagnostic_archive`；journal `complete`、trace 与候选绑定可重审；Refiner `needs_evaluation`，`not_lna_result=true`、`spec_pass=null`；没有第二次 Spectre 派发 |

`ok_with_warnings` 表示 Spectre 诊断运行可解析，不表示匹配、稳定性、线性度或规格通过。原始受限网表、PSF、日志和本机连接配置只在私有 `results/runs/` 与本机配置中，不写入公开文档或发送给外部模型。注入器记录的一次调用数还需与独立的远端源档/恢复来源一起看，不能单凭自述报告证明跨进程严格恰好一次。

## 实现与复核

`run_agent_diagnostic.run_diagnostic_agent` 增加可选 runner 注入，但必须与派发前绑定的远端配置完全相同。`probe_lost_reply_recovery.py` 的实验 runner 只拦截项目固定 Spectre 命令，先调用正常远端执行，再在其返回 0 时隐藏一次回复；并不替代正式后端。单元测试覆盖普通命令、不成功远端返回、重复派发拒绝及配置身份不一致。后续恢复仍调用项目原有 `inspect_pending_remote`、`recover_pending_remote`、`reconcile_pending`，没有实验专用的成功捷径。

定向测试 `11 passed`；加入本探针后的全量 Python 回归 `911 passed, 7 skipped`。软件测试没有覆盖物理网络断线、在途 Spectre 或 LNA 规格验收。

```powershell
$env:PYTHONPATH='src'
$template='results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs'
$hash=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower()
python -m orfadc.experiments.probe_lost_reply_recovery --template $template --template-sha256 $hash --spec S1 --seed 0 --rd-ohm 220 --vbias-v 0.67
python -m orfadc.agents.inspect_pending_remote --trace-dir <本次新私有trace目录> --stable-artifacts
python -m orfadc.agents.recover_pending_remote --trace-dir <同一trace目录> --template $template --template-sha256 $hash
python -m orfadc.agents.reconcile_pending --trace-dir <同一trace目录> --spec S1 --seed 0 --template $template --template-sha256 $hash
```

上述派发命令只应用于**全新** run；已对账的 trace 不得重复运行或再次恢复。本轮仍缺真正 SSH/主机中断时的在途进程可见性、跨进程竞争和端点认证，也没有合格 LNA fullchain。下一门禁是对受限真实在途/连接故障进行独立演练；在未证明远端作业状态前仍禁止自动重发。

后续 `docs/99_stage10_live_inflight_observation.md` 已在另一个新 run 中观察到真实 Spectre `active=1` 并完成同 run 恢复；这不回改本档“仅完成后丢回复”的历史范围，也没有完成物理 SSH 断线门禁。
