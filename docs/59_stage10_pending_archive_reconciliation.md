# Stage 10：预分配运行 ID 与 pending 诊断档案对账

`docs/26_deterministic_manager_mvp.md` 的首次评估前恢复不能处理 `EvaluateCandidate` 已写入后的进程中断。旧事件只有 candidate ID；同一 ID 可能对应多次独立 Spectre 运行，不能从目录里猜一个归档再发起或接收评估。本增量仅为**专用 RD/VBIAS 共源诊断后端**增加可核对的派发 ID 和已完成档案接收，不改变论文级 LNA/fullchain 门槛。

## 派发与信任边界

`execute_manager_planned` 在调用 evaluator **之前**生成唯一 run ID，把它和 candidate ID 一起 fsync 到 `EvaluateCandidate` 事件。诊断后端用该 ID 独占创建 `results/runs/<spec>/seed<seed>/<candidate>/<run_id>/`；Manager 拒绝后端返回其他目录。`inspect_journal` 对 planned 事件缺 ID、后续精炼绑定到别的 run ID、超预算/重复动作一律拒绝。旧一参数 evaluator 与旧 journal 保持可读兼容，但旧 pending **没有自动对账资格**。本机 `agent_writer.lock` 防止两个合规进程同时写同一 trace；它不是跨主机分布式锁。

`audit_active_diagnostic_candidate` 在接收前重建原始档：

1. 验证证据清单及 `metrics.json`、候选快照、网表、伴随文件、Spectre 完成日志、DC/SP/noise PSFASCII、CSV 的存在和哈希；
2. 用受控 RD/VBIAS 与固定 OA 模板**重新渲染**网表，逐字节核对归档网表与伴随文件；
3. 从原始 47 点 PSFASCII 重新计算 S11/S21/S22、NF/NFmin、纹波、供电和采样稳定性，并逐项对比 JSON/CSV；
4. 限定 `active_common_source_smoke`、`not_lna_result=true`、`spec_pass=null`。即使有人改写指标并重算清单哈希，原始数据对照仍会拒绝。

`reconcile_pending_diagnostic` 只在 journal 为 planned pending、规格/候选快照已验证、**恰好一次搜索和一次评估**、没有终态 trace 时工作。它在进程锁内只打开预分配 ID 的档案，先执行上述原始审计，再把已有档案绑定到 `RefineCandidate`，写 `Stop`、终态 trace 和 `agent_reconciliation.json`。它**不调用 SSH、OCEAN 或 Spectre**，不重发仿真。若档案不存在、尚未完整归档、模型/原始数据不一致或写者仍在运行，保留 pending 等待核查。第二次调用已完成的 trace 会被拒绝。对账报告内 `spectre_dispatched_by_reconciliation=false`；这只说明对账过程未派发，原始 Spectre 仍由第一次 evaluator 执行。

操作前先只读检查 journal 和档案；只对符合上述范围的**新格式**回合执行：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.reconcile_pending `
  --trace-dir results/runs/agent_diagnostic/<pending-trace-id> `
  --runs-root results/runs --spec S1 --seed 0 `
  --template <授权且位于私有运行目录的OA源网表> `
  --template-sha256 <源网表的64位SHA256>
```

不要对已有 `agent_trace.json` 的完成回合重复运行该命令；只读重审使用 `inspect_journal(trace_dir, candidate_runs_root=Path("results/runs"))` 和 `audit_active_diagnostic_candidate`。

## 实机故障注入证据

在宿主可用物理内存约 4.17 GiB、高于 2.66 GiB 门禁时，以已有授权 OA 模板运行 RD=190 Ω、VBIAS=0.67 V。单次真实 Spectre DC/SP/noise 归档 `results/runs/S1/seed0/S1_seed0_oa_diag/20260927T010857Z_d04f3583/` 报 0 errors、5 条既有 `SFE-1131` 配置警告。后端归档完成后，测试 harness 刻意抛出 `KeyboardInterrupt`，使 `results/runs/agent_diagnostic/20260927T010857Z_0b8f0e70/` 保留 `reconcile_pending_evaluation`，没有终态 trace。journal 的预分配 run ID 与档案名一致。

只读审计先独立验证该档 47 点原始数据；再运行对账入口，得到 `reconciled_existing_diagnostic_archive`、`Refiner=needs_evaluation`。终态 journal/trace、规格快照、候选快照、候选清单绑定均经复审；第二次对账被拒绝。原始指标中带内最差 S11≈-0.0036 dB、S21≈0.556 dB、NF≈4.201 dB，采样最小 K≈0.0203，**远非合格 LNA**。`agent_reconciliation.json` 只存相对候选路径、源清单哈希及非 LNA 标志，不公开商业网表/模型。

`tests/test_reconcile_pending.py` 用假档验证唯一 ID、重复调用、缺档和审计失败时不改 journal；`tests/test_audit_active_diagnostic_candidate.py` 对真实档做只读重算，并检查指标/网表改写后重算哈希的拒绝。此故障注入确实发生在后端归档之后，不覆盖“远端 Spectre 仍运行、仅本地进程失联”、共享文件系统锁、模型警告解释或完整 LNA fullchain。若中断发生在精炼事件已写而终态未写，不能直接重复执行 pending 对账入口；使用下述独立终态恢复门禁。

## 精炼后终态快照恢复

`finalize_diagnostic_trace` 处理上述较晚的中断点，但仅限**单候选、planned run ID、已写入 RefineCandidate 且没有终态 trace** 的共源诊断 journal。它接受两种状态：精炼事件之后尚未写 Stop，或已写 Stop 但尚未保存 trace。入口在同一进程锁内验证 spec/候选快照、事件顺序、run ID、证据清单绑定，并重新运行 `audit_active_diagnostic_candidate`，从原始 PSFASCII 和固定 OA 模板审计档案；还用当前确定性 Refiner 对档案重算，要求状态与 journal 完全一致。全部通过后才补 Stop（如缺）并保存 trace，生成 `agent_terminal_recovery.json`，其中 `spectre_dispatched_by_recovery=false`、`spec_pass=null`。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.finalize_diagnostic_trace `
  --trace-dir results/runs/agent_diagnostic/<interrupted-trace-id> `
  --runs-root results/runs --spec S1 --seed 0 `
  --template <授权且位于私有运行目录的OA源网表> `
  --template-sha256 <源网表的64位SHA256>
```

此入口**不适用于 pending、旧版无 planned ID、多个候选、仿真仍在途、已有 trace 或未审计 LNA**；重复调用会被拒绝。`tests/test_finalize_diagnostic_trace.py` 通过模拟在 Stop 前和 trace 前中断、审计失败和精炼状态篡改的负例；还在临时 journal 副本上调用已有真实共源 Spectre 档案的原始数据审计并恢复终态，未再次派发仿真。测试副本不是一次新的 Spectre 样本。当前仅补本机单候选诊断的终态落盘缺口，不提供跨主机锁、远端在途核验或论文级 LNA 通过判定。
