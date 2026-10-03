# Stage 10：无终结证据的远端不完整作业隔离

当前实现已升级为**远端不可覆盖决定 + 本地侧车的 v2 协议**，见 `docs/114_stage10_remote_quarantine_fence.md`。下述文字记录最初本机隔离闭环及其负例；现在的非审计入口会写入一个远端 fence 元数据文件，且命令行必须显式传入 `--publish-remote-fence`。旧真实断线档仍未执行此转换。

## 本轮完成的边界

`quarantine_pending.py` 为**单候选 planned OA 共源诊断**增加一个受限隔离事务。它只适用于已有 124/255 不确定派发记录、已绑定的远端身份和仍为 pending 的 journal。它不运行 Spectre，不发新 run ID，也不把旧候选转为仿真失败或规格结果。预算记为 `dispatched_outcome_unknown`；原 journal、候选 run、控制日志和任何失败 staging 保留。新侧车 `agent_pending_quarantine.json` 明确 `safe_to_dispatch=false`、`safe_to_reconcile=false`、`new_run_authorized=false`、`not_lna_result=true`、`spec_pass=null`。

流程在本机写者锁内检查 journal、规格/候选快照、pending 索引、控制返回、候选副本和本地原始输入；确认连接配置与计划远端身份相同；只读探测进程及目录，拒绝 remote_unknown、仍在运行、无日志、已有 SP/noise 或非普通原始文件。对远端网表、ADE 伴随文件和非终结日志作前后两轮静止哈希，隔离下载到**新 staging**，核对下载哈希与本地计划输入；v2 随后先原子发布远端不可覆盖决定、再复核原始文件，最后独占发布本地侧车，详见 `docs/114_stage10_remote_quarantine_fence.md`。日志无可信 Spectre 终结汇总是必要条件；静止本身绝非失败证据。成功/失败恢复和本地对账入口看到侧车后拒绝接管旧 run。

已发布的侧车可不接触远端地重复只读审计；重复隔离调用返回同一记录，不生成新 staging。若在下载或发布前崩溃，journal 保持 pending，下一次必须重新核对远端和来源；若在原子发布后崩溃，下一次审计已有侧车。staging 失败残留保留供追查。本机锁只协调共享该锁文件的控制进程；**未证明跨主机互斥、远端作业终止或远端将来不会重新启动**，故隔离后仍不授权任何新派发。若将来要放弃旧候选并建立新独占 run，需另行设计跨主机/端点协议及预算转移审批；本轮没有这条转换。

## 负例、原始档和当前连接

`docs/100_stage10_live_ssh_disconnect_incomplete.md` 的真实在途 SSH 控制连接断开档是目标负例：trace `results/runs/agent_live_disconnect_probe/20260927T161928Z_8de49aaa/`，原候选 run ID `20260927T161928Z_9b6cac2e`。本轮只读复核本地 journal 仍为 `reconcile_pending_evaluation`，原候选没有正式 metrics/manifest、trace 没有终态文件，也**没有隔离侧车**。没有重派或覆盖原档。

2026-09-29 的授权连接预检 `python -m orfadc.cadence.verify_remote` 返回 SSH 255、密钥交换时连接被重置；故不能把 docs/100 的**历史**远端静止观察当成本轮新鲜观察，也不能对该真实档执行隔离转换。其现时远端状态是 `remote_unknown`，旧 trace 继续 pending。此前在线审计出现 `remote_probe_failed` 是环境未验证，不是代码回归，也不是通过。所有生产端点认证、跨主机互斥及旧真实档的在线隔离验收仍为 partial。

一次远端**只读**探针在私有 trace 追加了独立诊断报告 `pending_remote_probe_20260928T163242Z_76dfd275.json`：`status=remote_unknown`、`reason=remote_probe_failed`、`safe_to_dispatch=false`、`not_lna_result=true`、`spec_pass=null`。该命令会在本地新增报告文件；没有改写原 journal/候选或生成隔离侧车，报告作为失败证据保留。

模拟远端与故障注入覆盖：未知/活动/变化/终结日志/身份漂移/来源篡改拒绝；两个本机控制进程竞争；发布前与发布后异常模拟进程中断的重入；重复调用幂等；已有恢复/对账入口拒绝隔离档。定向组合为 `48 passed, 5 skipped`；5 项旧档在线审计默认跳过，离线部分只用私有临时根和假 runner，不接入 SSH/Cadence。离线测试通过不等于实机隔离通过。

## 复现和下一门禁

```powershell
$env:PYTHONPATH='src'
$env:ORFADC_RUN_LIVE_SSH_AUDIT='0'
$testRoot = "results/runs/pytest_stage10_quarantine_$(Get-Date -Format yyyyMMddTHHmmssfff)"
python -m pytest tests/test_quarantine_pending.py tests/test_live_ssh_disconnect_audit.py tests/test_recover_pending_failure.py tests/test_recover_pending_remote.py tests/test_reconcile_pending.py -q --basetemp=$testRoot
python -m orfadc.cadence.verify_remote
```

只在授权 SSH、实际端点认证和远端硬链接语义都验收，且原档经过**新鲜**只读探针确认来源相同、稳定不完整时，才考虑对旧档运行带 `--publish-remote-fence` 的显式转换；当前不得执行。侧车生成后可用 `--audit-only` 做纯本地重审，或用 `--verify-remote` 只读核对远端 fence。若远端仍未知、文件变化或身份不一致，应原样保持 pending 并调查连接/作业，不以新实验绕过旧 run。当前未执行该实机转换，也未创建新诊断 run。

此协议仅是 Stage 10 的软件隔离闭环，不改变 Stage 03/08/09 CDF/PCell、DRC、工艺模型、有损无源 Q/k/SRF 和合格 LNA fullchain 的门禁。通用 fullchain evaluator 与工具注册表未因本协议获得可用后端；教学、mock、理想无源和不完整档不得填论文 Table IV/V/VI 或称 pass@1。
