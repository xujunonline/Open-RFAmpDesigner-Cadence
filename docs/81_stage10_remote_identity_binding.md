# Stage 10：planned 派发前的远端配置身份绑定

## 为什么增加绑定

`docs/80_stage10_pending_remote_readonly_probe.md` 的首版只按本机当前 SSH 配置推导远端目录。若原回合派发后本机 `remote_cadence.local.yaml` 改成另一台机器或工作根目录，探针会查错位置，即使 journal 中的 planned run ID 未变。现在**新建的 RD/VBIAS 共源诊断回合**在 `RunStarted` 前保存私有 `agent_remote.json`，并把规范化文件的 SHA-256 写入首事件。`run_agent_diagnostic.py` 将同一个已加载的 `RemoteCadenceConfig` 同时传给 planned 执行器和 Spectre 后端，消除两个调用点重复读配置的时间差。

快照保存 SSH host、user、port、remote root、身份文件的**路径**及 host-key 检查策略；不保存密钥内容。它与原始网表、PSFASCII 一样只位于 Git 忽略的私有 `results/runs`。`inspect_journal` 只读检查快照字段、规范编码和摘要；新的远端 pending 探针在发 SSH 前还比较该快照与当前连接配置，不一致立即拒绝。旧 planned trace 仍可按旧规则审计和对账，但 `remote_identity_verified=false`，远端探针拒绝查询，不能把当前配置误认为历史派发配置。

## 真实 Cadence 验证

宿主可用物理内存约 3.88 GiB，超过既定 2.66 GiB 门禁，远端起始无 EDA 残留。用原授权 OA v2 模板仅调整 RD=210 Ω、VBIAS=0.67 V，新 trace `results/runs/agent_diagnostic/20260927T081306Z_f14323f5/` 绑定独立候选档 `results/runs/S1/seed0/S1_seed0_oa_diag/20260927T081306Z_57cfbd7e/`。Spectre 0 errors、5 条既有模型配置警告；47 点 DC/SP/noise 原始 PSFASCII 经 `audit_active_diagnostic_candidate` 重算通过。journal、trace、候选源档清单及远端身份快照均通过独立只读审计；再用同一配置只读检查该次远端目录，日志/SP/noise 文件存在，作业结束后无可见 Spectre 进程。

这仍是 `active_common_source_smoke`：最差 S11≈-0.0038 dB、S21≈0.791 dB，`not_lna_result=true`、`spec_pass=null`。它证明**新诊断回合的配置接线和证据链**，不是合格 LNA、真实在途进程或断线恢复实验。定向测试 `40 passed, 1 skipped`；全量 Python 回归 `763 passed, 3 skipped`。

## 复核与限制

```powershell
$env:PYTHONPATH='src'
python -m pytest -q --disable-warnings `
  tests/test_remote_identity.py tests/test_inspect_pending_remote.py `
  tests/test_agent_diagnostic.py tests/test_agent_journal.py tests/test_reconcile_pending.py `
  --basetemp=results/runs/pytest_remote_identity_stage10_final
```

配置快照是**一致性绑定，不是密码学远端主机身份认证**：它没有保存当时协商的服务器 host-key 指纹，DNS、身份文件内容及远端进程可见性仍可能变化；journal 本身也不是带密钥的签名。当前候选 `metrics.json` 没有独立写入远端身份摘要，归档与 trace 的连接仍依赖执行器传入同一配置对象及候选证据绑定。真正的远端静止结果回收、原始文件校验、实际在途进程演练和跨主机锁仍待完成；本项不能升级 Stage 10 或论文式多智能体验收。
