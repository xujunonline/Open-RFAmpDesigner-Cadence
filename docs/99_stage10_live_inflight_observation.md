# Stage 10：真实 Spectre 在途观察与同 run 原始恢复

## 与前一轮的区别

`docs/98_stage10_real_spectre_lost_reply_probe.md` 证明了新真实 Spectre **完成之后**控制端丢失一次回复时，planned pending 能通过原始文件恢复；它没有看到仿真仍在运行的瞬间。本轮对另一个全新、独占的 S1 单候选 OA 共源诊断，同时使用第二条 SSH 连接只读观察 `/proc`。实验 runner 仅在即将派发固定 Spectre 命令时发送本地事件；**事件本身不算在途证据**。观察器必须从远端取得 `directory=present` 且 `active=1`，才记录命中。其后仍只在真实 Spectre 返回 0 时对控制端注入一次 255，留下可恢复的 pending journal。

| 环节 | 私有来源与审计结果 |
| --- | --- |
| 派发和即时只读观察 | trace `results/runs/agent_inflight_probe/20260927T155701Z_64fdb795/`；一次独立 SSH 原始响应 `directory=present, active=1, log=0, sp=0, noise=0`，返回码 0；同目录的 Spectre 尚在运行，原始文件尚未齐备 |
| 完成后 pending | 真实 Spectre 返回 0，控制端按实验设定只隐藏这一次回复，`agent_evaluation.json` 为 `pending_remote_evaluation`；新候选 run ID `20260927T155701Z_59f4eadb` |
| 静止复查 | 后续 `inspect_pending_remote --stable-artifacts` 报 `remote_quiescent_raw_audit_required`，两次原始文件哈希稳定，仍 `safe_to_dispatch=false`，没有把“进程已消失”当作成功或重发许可 |
| 恢复及对账 | `recover_pending_remote` 下载并重新审计 47 点 DC/SP/noise，`reconcile_pending` 使 journal `complete` 且候选/规格/远端身份绑定通过；后端 `ok_with_warnings`，Refiner `needs_evaluation`、`not_lna_result=true`、`spec_pass=null`，恢复/对账不派发第二次 Spectre |

审计器 `audit_inflight_lost_reply.py` 要求采样时的原始 SSH 状态行与解析布尔值一致、唯一远端目录摘要与 planned journal 身份一致、pending 索引与终态 run ID 一致，并重审恢复后的 OA 网表、伴随文件、Spectre 原始数据及清单。篡改原始 `active`、解析字段、目录摘要或一次派发计数都会拒绝。私有单次证据档只读重审返回 `inflight_seen_and_recovered_diagnostic`。记录并非远端签名或跨主机原子快照，不能证明在整个仿真期持续可见。

定向测试 `31 passed`；纳入本轮代码后的全量 Python 回归 `918 passed, 7 skipped`（826.83 秒）。远端回合后再次检查无 Spectre 进程。软件回归不构成电路规格或物理设计验收。

本轮是**真实在途进程观察**，但 SSH 连接没有在仿真运行时物理断开；“完成后回复被注入器丢弃”仍是受控故障。它也不是被授权验证过的三阶段 LNA，不测压缩点，不满足 Stage 03/08/09/13。真正的传输中断、并发控制进程竞争和跨主机端点身份仍未验收，不允许据此自动重发任何 pending 仿真。

```powershell
$env:PYTHONPATH='src'
$template='results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs'
$hash=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower()
python -m orfadc.experiments.audit_inflight_lost_reply --trace-dir results/runs/agent_inflight_probe/20260927T155701Z_64fdb795 --template $template --template-sha256 $hash
python -m pytest tests/test_lost_reply_probe.py tests/test_inflight_lost_reply_audit.py tests/test_inspect_pending_remote.py -q
```

`probe_inflight_lost_reply.py` 仅供**新**单候选受控实验使用；上述 trace 已对账，不得重派发。真实复现实验须先重新检查宿主/来宾物理内存、SSH 身份和远端空闲；完整原始波形、OA、日志、SSH 状态及本机配置均留在 Git 忽略的私有目录。公开文档不包含商业模型或网表。
