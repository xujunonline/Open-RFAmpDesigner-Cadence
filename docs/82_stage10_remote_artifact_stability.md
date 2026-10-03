# Stage 10：远端诊断原始文件双次哈希观察

## 已实现的只读门禁

`inspect_pending_remote.py` 的 `--stable-artifacts` 选项只对**远端身份已绑定**、journal 仍处于 planned pending 的单候选共源诊断生效。先查目标目录和可见 Spectre 进程，再对以下六个文件调用远端 `sha256sum`；等待至少 3 秒后再次查询进程及哈希：

```text
netlist.scs       ade_e.scs       spectre.log
psf/dcOp.dc       psf/sp.sp       psf/sp.noise.sp
```

文件缺失、SSH 错误、输出格式异常、任一次看到 Spectre 或前后哈希变化均不给出稳定结论。相同哈希只返回 `stable_unverified`，并固定 `safe_to_adopt=false`、`safe_to_dispatch=false`；它不执行仿真、下载、修改或清理远端文件。结果可随 pending 探针保存到私有 trace 报告。旧未绑定 trace 仍在 SSH 前被拒绝。该文件集特指现有 OA v2 共源诊断（含 `ade_e.scs`），不是通用 LNA 全链恢复协议。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.inspect_pending_remote `
  --trace-dir results/runs/agent_diagnostic/<真实仍pending的新格式trace> `
  --runs-root results/runs `
  --config config/remote_cadence.local.yaml `
  --stable-artifacts
```

## 实机来源与结果

使用 `docs/81_stage10_remote_identity_binding.md` 的已完成、**非 pending** 诊断运行 `20260927T081306Z_57cfbd7e` 只读核查远端：目录保留网表、ADE 伴随文件、Spectre 日志、DC/SP/noise 原始文件及额外 PSF 信息；原控制端 `spectre.stdout.log`/`spectre.stderr.log` **未保留在远端**。两次相隔 3 秒的目录/进程观察均未看到该目录的 Spectre 进程；六个远端文件哈希逐一稳定，并与原本地已审计归档完全一致。调用的是低层只读函数，未制造假的中断 trace，也没有新发 Spectre。定向测试 `17 passed`，包括真实 pending 入口的假远端整合测试、哈希变化/缺失/进程在途/连接异常负例。

上述只能校准**已完成目录上的探针和远端文件可得性**。本轮完整 Python 回归 `770 passed, 3 skipped`。文件稳定不等于 Spectre 已成功结束、没有不可见的进程、PSFASCII 可解析、模型有效或 LNA 规格通过。真实在途中断后的下载/接管尚未实测。

## 恢复档案下一门禁

后续若从真实静止远端目录回收，应先核对原派发配置和 planned ID，确认 Spectre 日志完成标记；传输前后再次比较远端六文件哈希，并核对本地下载哈希；用原 OA 模板重建 `netlist.scs`，再从原始 PSFASCII 重算指标。必须单独记录“控制端 stdout/stderr 未捕获”的恢复来源，不能伪造为空日志并冒充原始输出。`audit_active_diagnostic_candidate` 的现行正常档案要求 stdout/stderr；恢复模式须新增明确区分的审计契约，只有原始数据复核后才允许 `reconcile_pending_diagnostic` 接收。任何一步不一致保留 pending 和失败档，绝不重发 Spectre。
