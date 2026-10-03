# Stage 10：静止远端共源诊断的受控回收

## 范围

本阶段只处理新格式、远端身份快照已绑定、单次 planned 派发且仍 pending 的 RD/VBIAS 共源诊断。`recover_pending_remote.py` **不启动 Spectre，也不直接改写 agent journal**。它检查原 spec/候选/派发 ID/远端配置，观察进程和六个文件的双次哈希，要求 Spectre 日志有 0 errors 完成标记，然后下载原始 OA 网表、ADE 伴随文件、日志、DC/SP/noise PSFASCII。下载前后再比较远端哈希，逐文件核对本地字节；网表从固定 OA 模板及候选参数重建，指标从原始 PSFASCII 重算，最后生成哈希清单并执行只读审计。

远端没有保存控制端的 `spectre.stdout.log` / `spectre.stderr.log`。回收档不创建这两份文件，而在 `recovery_provenance.json` 与 `metrics.json` 明确记录 `remote_quiescent_download_v1`、`controller_stdout_stderr_captured=false`、`spectre_dispatched_by_recovery=false`。清单包含远端六文件对应的本地原始内容、来源与派生指标；正常档案继续要求原控制端日志。`reconcile_pending_diagnostic` 在接收这种恢复档时，额外核对 provenance 的 trace ID、远端配置摘要和远端目录摘要与原 planned journal 一致。回收和接管均不允许重新派发。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.recover_pending_remote `
  --trace-dir results/runs/agent_diagnostic/<真实仍pending且身份已绑定的trace> `
  --runs-root results/runs `
  --config config/remote_cadence.local.yaml `
  --template results/runs/<私有OA模板目录>/netlist.scs `
  --template-sha256 <本地模板SHA256>
```

只有返回 `recovered_raw_audited`，才可用同一 `trace-dir`/`runs-root`、原 spec/seed/模板调用 `reconcile_pending_diagnostic`。若进程可见、目录不静止、文件/哈希/日志/原始数据/身份任一不一致，保持 pending，不清理源文件且**不重发**。

恢复器现先在私有 staging 子目录完成指标、CSV、清单和原始数据审计，再将完整文件以不覆盖的同卷操作逐个发布，`evidence_manifest.json` 最后发布。发布前检查正式档案中任何已有同名文件的哈希及父路径；相同字节可在再次恢复时复用，不一致或父路径受阻则拒绝且不覆盖。Windows 使用同卷重命名，其他系统使用硬链接；两者都避免把复制到一半的文件暴露为正式产物。故障注入分别在第 3、第 10 个文件后中断，两次重新下载并完成审计；对改动过的半成品则拒绝。若中断发生在清单发布后、命令返回前，无须再次下载，可直接调用 `reconcile_pending_diagnostic` 重新审计并接管。失败 staging 和半成品保留供检查；**没有自动清理或覆盖，也尚未证明任意异常、跨主机故障下的事务原子性**。恢复相关定向测试 `21 passed`，本轮全量 Python 回归 `784 passed, 3 skipped`。

## 实机演练与证据边界

以**已完成**的远端共源诊断 `20260927T081306Z_57cfbd7e` 为只读源，使用 `validate_recovery_fixture.py` 在 Git 忽略目录 `results/runs/synthetic_remote_recovery/20260927T084410Z_189def41/` 创建了一个明确标记为合成的 pending journal。实际 SSH 下载六个远端文件后，恢复档重算 47 个频点，原始数据审计及 journal 接管均通过。改为暂存/不覆盖发布后，独立的第二次实际 SSH 演练 `20260927T085543Z_963b0e41` 同样通过 47 点和 journal 接管。两份 `validation_summary.json` 均记录 `synthetic_pending_journal=true`、`actual_interruption_observed=false`、`spectre_dispatched_by_validation=false`、`not_lna_result=true`、`spec_pass=null`。它们不是新的 Spectre 仿真样本，也**不是**真实运行中断后恢复成功的证据。

离线测试覆盖正常接管、下载字节损坏、缺失日志完成标记、SSH 配置变更，以及重哈希后伪造 trace 来源的拒绝；还验证回收档不虚构 stdout/stderr。实机演练未验证 SSH 断线时进程可见性、跨主机互斥、恶意或被替换的远端端点，也未解决主机密钥/身份文件内容绑定。当前源目录真实运行已结束，远端进程观察仅为瞬时快照；不能据此许可自动重发。OA 共源诊断不是论文三阶段 LNA，5 条原有模型警告仍待解释。

下一门禁：在可控故障注入下，对真实派发的 in-flight/中断回合验证进程和断线语义；补 SSH 端点认证、跨主机锁与全程失败事务核验。之后才能考虑真实 LNA fullchain 的远端恢复协议，不能将本六文件白名单泛化到 HB、PEX 或论文规格实验。
