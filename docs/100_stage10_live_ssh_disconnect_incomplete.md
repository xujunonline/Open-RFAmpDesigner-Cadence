# Stage 10：运行中真实 SSH 控制连接断开与不完整结果门禁

## 实验范围

`docs/99_stage10_live_inflight_observation.md` 曾在一个新 Spectre 作业内通过独立 SSH 观察到 `active=1`，但只在作业**完成之后**注入丢回复。本轮又使用另一个全新、独占的 S1 单候选 OA 共源诊断：一条 SSH 派发真正的 Spectre；第二条 SSH 从同一远端 run 目录的 `/proc` 读到 `active=1` 后，实验 runner 才终止**本次创建的本机 SSH 控制子进程**。这是真实运行中控制连接断开，不是网络设备断线、VM 崩溃或许可证修改。没有更改既有 OA cell、商业 PDK、VM 设置，也不对中断作业自动重派发。

运行前宿主可用物理内存约 3.75 GiB、来宾约 2472 MiB，SSH 正常、远端无 Spectre。所有受限网表、OA、原始日志、SSH 状态及本机连接配置留在 Git 忽略的私有 `results/runs/`。

| 环节 | 私有证据与观察 |
| --- | --- |
| 新派发 | trace `results/runs/agent_live_disconnect_probe/20260927T161928Z_8de49aaa/`，候选 run `20260927T161928Z_9b6cac2e`；单个 RD/VBIAS 白名单共源诊断 |
| 在途与断开 | 第二条 SSH 原始响应 `directory=present, active=1, log=0, sp=0, noise=0`，返回码 0；随后只终止该次创建的本机 SSH 子进程，记录其非零退出；planned agent 的控制返回为 255，保留 `pending_remote_evaluation` |
| 断开后的远端 | 独立只读探针显示目录存在、无 Spectre 进程、有日志、无 SP/noise 原始文件，分类 `remote_quiescent_incomplete`；`safe_to_dispatch=false` |
| 失败来源核对 | 网表、伴随文件和日志的两次远端哈希稳定，但日志既无 0-error 也无非零错误终结汇总。正式 `recover_pending_failure` 下载到**私有 staging** 后拒绝发布终态；成功恢复器也缺完整原始文件 |
| 最终状态 | journal 仍 `reconcile_pending_evaluation`；没有终态 `metrics.json`、证据清单、`agent_trace.json` 或对账报告。`audit_live_ssh_disconnect.py` 重核在途原始行、planned 身份、控制返回、远端静止哈希、staging 与无终结行，结论 `live_ssh_disconnected_remote_quiescent_incomplete`，禁止接收和重发 |

这份结果**不能**因为 Spectre 进程消失或文件短时稳定就归类为一次已证实的仿真失败：没有 Spectre 终结行，且 DC/SP/noise 并不齐全。它必须保持 pending/隔离状态；同一 planned run ID 不可再次派发。若以后决定放弃该候选并启动一个新 run，需要独立定义和验收具有审计证据的中止/隔离事务，不能通过改写失败日志或伪造指标绕过门禁。`spec_pass=null`、`not_lna_result=true`。

本轮定向测试 `37 passed`，覆盖受限本机 SSH 终止、未观察到在途时不终止、已退出连接不误报，以及实际私有档和原始状态篡改拒绝。真实探针之后再次只读检查远端 Spectre 空闲。它没有证明跨主机竞争、任意断线时序、SSH 重连后的长时稳定性或合格 LNA fullchain，也不关闭 Stage 03/08/09 的 CDF/PCell、无源物理/DRC 和工艺模型门禁。

本轮代码纳入全量 Python 回归后为 `927 passed, 7 skipped`（850.59 秒），无失败；回归后再核 journal 仍 pending、正式 metrics/manifest 缺失且远端 Spectre 空闲。测试通过只验证软件拒绝路径及可重审来源，不给中断作业补造终态。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.inspect_pending_remote --trace-dir results/runs/agent_live_disconnect_probe/20260927T161928Z_8de49aaa --stable-artifacts
python -m orfadc.experiments.audit_live_ssh_disconnect --trace-dir results/runs/agent_live_disconnect_probe/20260927T161928Z_8de49aaa
$env:ORFADC_RUN_LIVE_SSH_AUDIT='1' # 仅在授权 SSH 当前可用时启用在线审计
$testRoot = "results/runs/pytest_live_disconnect_$(Get-Date -Format yyyyMMddTHHmmssfff)"
python -m pytest tests/test_live_ssh_disconnect_probe.py tests/test_live_ssh_disconnect_audit.py tests/test_recover_pending_failure.py tests/test_inspect_pending_remote.py -q --basetemp=$testRoot
Remove-Item Env:ORFADC_RUN_LIVE_SSH_AUDIT
```

上述 trace 已发生真实断开，**不要**再次运行同一候选；`probe_live_ssh_disconnect.py` 仅供有资源门禁的新独占诊断 run 使用。审计器需要当前授权 SSH 环境才能重取远端哈希；如果远端不可达，结论应降为未能重审，而不是默认通过。

2026-09-29 更新：当前 SSH 预检返回 255（密钥交换阶段连接重置）；显式启用的在线只读审计在远端探针处失败，不能据此推翻当时的原始观察或认定代码回归。旧 trace 仍 pending 且没有隔离侧车；仅模拟远端通过的受限隔离协议见 `docs/113_stage10_incomplete_remote_quarantine.md`。未获得新鲜远端证据前不得对旧档执行转换或重复派发。
