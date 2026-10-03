# Stage 10：planned pending 的只读远端状态探针

## 作用与输入

`src/orfadc/agents/inspect_pending_remote.py` 只接受现有 `run_agent_diagnostic.py` 形成的**单候选 RD/VBIAS planned pending**。它先用 `inspect_journal` 核查事件顺序、预算、规格/候选快照，再从 `candidate_id` 和**已持久化**的 `run_id` 推导 `run_active_diagnostic_candidate.py` 使用的唯一远端目录。检查失败时不发 SSH。当前只适用于这个共源诊断后端，不是通用 LNA fullchain 恢复器。

SSH 命令只读取目录、`spectre.log`/SP/noise 原始文件是否非空，以及 `/proc` 中工作目录位于该目录的 Spectre 进程。它不运行 Spectre，不下载、清理或更改远端文件，也不采信目录存在作为仿真成功。返回状态：

| 状态 | 含义与下一步 |
| --- | --- |
| `spectre_in_flight` | 观察到可能仍在运行的 Spectre；继续等待并重新观察，不重发。 |
| `remote_quiescent_unverified` | 有远端目录，本次未观察到 Spectre；尚未进行两次原始文件哈希观察，不能开始接收。 |
| `remote_quiescent_raw_audit_required` | `--stable-artifacts` 下两次原始文件哈希一致，但仍需恢复器验证干净结束标记、来源网表和 PSFASCII；不等于仿真成功。 |
| `remote_quiescent_incomplete`/`remote_artifacts_changing` | 原始文件缺失或两次观察之间变化；保持 pending，不走成功恢复。 |
| `local_raw_audit_required` | 本地已有上下文一致的哈希清单；仍须运行 `audit_active_diagnostic_candidate` 的原始 PSFASCII 重算，再用 `reconcile_pending_diagnostic` 接收。 |
| `local_archive_invalid` | 本地清单或上下文不一致；停下调查，不接收。 |
| `remote_unknown`/`remote_unsafe` | SSH 失败、格式异常或远端目录为符号链接；保持 pending，不推测运行已停止。 |
| `dispatch_not_observed` | 未看到远端目录；这不证明原任务从未派发，仍不自动重发。 |

**所有返回均固定 `safe_to_dispatch=false`、`spectre_dispatched_by_probe=false`、`not_lna_result=true`、`spec_pass=null`。** CLI 会在私有 trace 目录独占命名保存带时间戳的观察报告；其中记录 journal 摘要和远端目录摘要，不公开远端路径或商业 PDK 内容。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.inspect_pending_remote `
  --trace-dir results/runs/agent_diagnostic/<实际未完成的planned trace> `
  --runs-root results/runs `
  --config config/remote_cadence.local.yaml
```

命令必须指向**真实仍 pending** 的 trace；已完成 trace 会被拒绝。首次判断不要恢复或重复派发，先据状态检查。现有 `reconcile_pending_diagnostic` 只接收本地完整、经原始数据重审的归档，不调用 Spectre。

后续 `docs/95_stage10_uncertain_remote_dispatch.md` 已补计划式超时保留及成功结果的只下载恢复器；`--stable-artifacts` 可请求两次原始哈希观察，但无论返回哪个状态，仍必须通过恢复器的完成标记和原始审计。此处下段数字和“尚无回收器”描述的是本探针初版的历史验收状态，不代表当前能力。

## 验证与边界

8 个定向测试覆盖活跃、静止、缺失、符号链接、连接失败、本地哈希档和篡改候选快照的拒绝；与旧 agent/journal 测试合跑为 `33 passed, 1 skipped`，全量 Python 回归 `753 passed, 3 skipped`。在授权虚拟机上，对**历史已完成**的诊断运行 `20260927T010857Z_d04f3583` 的远端目录只读实测返回：目录存在、Spectre 日志及 SP/noise 文件存在、未观察到 Spectre 进程。该实测验证 SSH 脚本能读取静止目录，**没有**在真正进行中的 Spectre 作业上测试，也没有制造新的 pending 运行。

`/proc` 进程名、可见性及采样时刻可能漏掉在途进程；journal 是结构/摘要一致性记录，不是带密钥的防篡改签名。后续**新** planned 诊断回合已增加远端配置快照与当前配置的派发前比对，见 `docs/81_stage10_remote_identity_binding.md`；旧 trace 没有该绑定，探针现在拒绝对其查询。新绑定也不是服务器 host-key 的密码学证明。因此“没有看到进程”和“目录缺失”均**不是重发许可**。远端静止但未下载的结果尚无自动回收器；跨主机锁、部分下载、许可证超时及实际运行中断后的重复观察仍待验证。不能据此提高 Stage 10 或合格 LNA 的验收状态。
