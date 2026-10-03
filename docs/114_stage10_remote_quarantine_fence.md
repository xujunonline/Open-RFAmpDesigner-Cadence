# Stage 10：远端不可覆盖隔离决定的模拟竞争协议

## 状态转换与写入边界

本轮将 `docs/113_stage10_incomplete_remote_quarantine.md` 的本机隔离侧车升级为 schema v2。它仍只接受**单候选 planned OA 共源诊断**的 124/255 不确定派发档；原 journal 始终 pending，预算为 `dispatched_outcome_unknown`。`safe_to_dispatch=false`、`safe_to_reconcile=false`、`new_run_authorized=false`、`not_lna_result=true`、`spec_pass=null` 不变。它不运行 Spectre、不重派原 run ID、不写 metrics/manifest/终态 trace，也不释放预算。

在远端非活动、缺 SP/noise、有非终结日志且来源双次哈希稳定、隔离下载和本地计划输入核对通过**之后**，控制端构造不含网表内容的规范化决定（run/trace/候选、journal/输入/远端身份与原始文件哈希、未知预算和禁止派发字段）。远端脚本在**原有独占 run 目录内**将此决定写入临时文件，用 `ln` 原子创建 `.orfadc_quarantine_fence_v1.json`：首次创建为 `created`；字节完全相同为 `existing_same`；其他已有内容或不安全文件为冲突，保持 pending。它不覆盖或删除原始文件、旧 staging 或已有决定。临时文件若因强制终止残留，留作诊断，不作为接管许可。

控制端随后重新读取远端 fence SHA-256、下载 fence 到新本地 staging 并逐字节比对，再复核远端原始文件和进程状态、冻结的本地来源，最后独占发布本地 `agent_pending_quarantine.json`。本地审计绑定 fence 原文/哈希；`--verify-remote` 仅重新核对远端 fence 哈希，**不代表**重新证明 Spectre 进程、原始文件仍静止或授权端点已认证。显式 `--publish-remote-fence` 才允许执行有远端元数据写入的转换；`--audit-only` 纯本地只读。

这不是带超时的租约：没有过期、自动抢占或自动释放。控制回执在远端 `ln` 成功后丢失时，本地不写侧车；重启后只有重新观察到**同一**来源和决定才能得到 `existing_same` 并接续。若原始文件变化、两个 trace 对同一远端 run 提出不同决定、远端回执/哈希未知或 fence 被改动，拒绝本地转换，旧作业继续 pending；已经创建的远端 fence 保留，不凭静止状态重发。两个控制端提出同一决定时，模拟远端只创建一次，两端最多归档同一不可覆盖的决定。这个协议围住的是**隔离决定**，并不提供整个项目的跨主机派发锁。

## 验证及尚未验收

模拟远端分别使用两个独立本地控制根和共享的原子决定存储，测试同时提出相同/冲突决定、单一获胜、提交后丢回复、提交后原始文件变化、身份漂移、未知/畸形回复、远端与本地 fence 篡改、发布断点和重复调用。上述只验证 Python 状态机及模拟的原子 `ln` 语义；当前 SSH 连接失败，无法在授权 Linux 端执行脚本。远端文件系统的硬链接原子性、主机密钥与实际端点绑定、跨真实控制主机竞争、机器掉电耐久性均未验收。因此 Stage 10 仍为 `partial`，不开放新 run 或放弃旧预算。

本轮 `python -m orfadc.cadence.verify_remote` 仍返回 SSH 255（密钥交换时连接重置）。`docs/100` 的真实在途断线 trace `20260927T161928Z_8de49aaa` 保持 pending；本轮未向原远端执行 fence 脚本，本地也没有 v2 隔离侧车。保留此前 `remote_unknown / remote_probe_failed` 的私有探针报告。无新 Cadence 实验，也无物理 CDF/PCell、DRC、模型或有损无源验收。

本轮隔离/恢复/安全入口定向组合 `82 passed, 5 skipped`；5 项实时 SSH 审计按离线门禁跳过。仅收集项目 `tests/` 的离线全量回归 `1078 passed, 12 skipped`；跳过或 SSH 255 均不构成远端协议通过。代码编译检查与 `git diff --check` 通过。

## 复现

```powershell
$env:PYTHONPATH='src'
$env:ORFADC_RUN_LIVE_SSH_AUDIT='0'
$testRoot = "results/runs/pytest_remote_fence_$(Get-Date -Format yyyyMMddTHHmmssfff)"
python -m pytest tests/test_quarantine_pending.py tests/test_live_ssh_disconnect_audit.py tests/test_recover_pending_failure.py tests/test_recover_pending_remote.py tests/test_reconcile_pending.py tests/test_agent_safety.py tests/test_agent_tool_registry.py -q --basetemp=$testRoot
$fullRoot = "results/runs/pytest_full_$(Get-Date -Format yyyyMMddTHHmmssfff)"
python -m pytest tests -q --basetemp=$fullRoot
git diff --check
python -m orfadc.cadence.verify_remote
```

在 SSH、授权端点及远端文件系统语义分别验收之前，不要对旧真实档使用 `--publish-remote-fence`。若未来满足这些门禁，只能先新鲜只读复核旧 run，再在资源许可下执行一次显式隔离；`--verify-remote` 只用于隔离完成后的远端 fence 复核。任何缺失证明都维持 pending 和 `safe_to_dispatch=false`。
