# Stage 10：planned OA 诊断的终态失败恢复

## 适用范围

`recover_pending_failure.py` 只处理已持久化 planned run ID、单次 RD/VBIAS 共源 OA 诊断的**远端 Spectre 终态失败**。它不运行、不重试 Spectre，不生成增益/NF/IP1dB 等指标；`not_lna_result=true`、`spec_pass=null`。本工具与成功结果的 `recover_pending_remote.py` 分开，绝不能把错误日志送进成功结果恢复。

先用 `inspect_pending_remote` 只读观察。即便没有看到 Spectre 进程，也不能立即判定失败或重发。失败恢复还逐项要求：

探针的 `--stable-artifacts` 使用**成功仿真**的全套 DC/SP/noise 原始文件作为观察对象；终态失败可能因缺 PSF 而显示 `remote_quiescent_incomplete`。这不是失败认证，也不是重发许可。失败恢复器独立对网表、伴随文件和失败日志执行两轮静止/哈希检查，必须再满足以下所有门禁。

1. journal、候选/规格及远端身份快照与当前 SSH 配置匹配；远端目录和文件不是符号链接；
2. 两次观察均未见该目录的 Spectre，且 `netlist.scs`、`ade_e.scs`、`spectre.log` 三文件哈希稳定；下载后再次重复两次观察，哈希与首次完全一致；
3. 下载的网表和伴随文件与本地受限 OA 模板、候选 RD/VBIAS 精确一致；
4. 下载的 `spectre.log` 只有一个形如 `spectre completes with 1 error` 的**非零错误终结汇总**。许可证等待文本、空/截断日志、零错误汇总、多个矛盾汇总均拒绝；
5. 本地只发布哈希绑定的失败 `metrics.json`、原始网表/伴随文件/日志、`candidate.json` 和远端快照来源。已有不同内容不覆盖。

若任一条件缺失，journal 保持 pending，不推断“已失败且可重试”。远端进程检查依赖 `/proc` 中的进程名和工作目录，可能漏检；双次哈希与终结行降低误判，但不是跨机器原子快照或服务端签名。因此仍未完成真实断线场景验收。

## 操作顺序

以下路径参数必须指向 Git 忽略的私有文件和**同一** pending run，模板摘要须与首次派发一致：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.agents.inspect_pending_remote --trace-dir <私有trace目录> --stable-artifacts
python -m orfadc.agents.recover_pending_failure --trace-dir <私有trace目录> --template <私有OA模板> --template-sha256 <模板SHA256>
python -m orfadc.agents.reconcile_pending --trace-dir <私有trace目录> --spec S1 --seed 0 --template <私有OA模板> --template-sha256 <模板SHA256>
```

第二步只建立 `remote_quiescent_failed_log_v1` 失败归档，不结束 journal；第三步对失败档重新验证来源、日志和与 trace 绑定的远端身份，再用 `RefineCandidate=needs_evaluation` 记录并结束。`agent_reconciliation.json` 才是对账后的状态；最初的 `agent_evaluation.json` 保留为派发时的 pending 快照。预算已用完，不自动创建新候选；后续是否改变设计须由新一轮带新 run ID 的设计决策决定。

## 证据与边界

历史私有 Spectre 失败日志中存在可解析的单错误终结行，但**没有**用它冒充同一 planned 候选的真实断线恢复。测试使用既有私有 OA 网表/伴随文件及模拟远端失败日志，覆盖无终结行、活动作业、身份不一致、文件哈希不一致、重哈希篡改、重复对账拒绝，以及失败 journal 的完整归档。相关定向测试 `24 passed`；纳入全项目默认环境回归后 `889 passed, 7 skipped`。真正的 SSH 断线、许可证等待后远端错误形态、跨进程竞争及合格 LNA fullchain 仍须在授权环境独立实测。
