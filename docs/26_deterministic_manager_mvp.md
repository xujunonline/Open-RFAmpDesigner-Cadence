# 阶段 10：确定性 Manager 最小状态机

`src/orfadc/agents/manager.py` 现提供有边界的候选调度，而不是仅靠“队列非空”猜测下一动作。它仍是**普通 Python 规则**，不调用 LLM，也不运行 Cadence；阶段 10 保持 partial。

## 状态与动作

| 条件 | `next_action()` | 含义 |
| --- | --- | --- |
| 有候选且评估预算未满 | `EvaluateCandidate` | 取队首，登记为待评估；一次只允许一个 pending 候选。 |
| 已取候选但尚未回传结果 | `AwaitEvaluation` | 不再发起搜索/第二个评估，避免结果串候选。 |
| 队列空且搜索预算未满 | `SearchCandidates` | 调 Searcher 提出资源分配候选。 |
| 预算耗尽或无后续动作 | `Stop` | 停止；不能把停止等同于找到可行解。 |

`search_candidates` 检查 seed、spec ID 和候选上下文，并将单个 Manager 绑定到首次有效搜索的 spec/seed；非列表 Searcher 返回值被拒绝，同一 candidate ID 只入队一次。重复搜索仍消耗搜索预算。`pop_candidate` 消耗评估预算；`record_result` 只接受刚取出的**同一对象**，调用 `Refiner.refine_from_run` 从运行目录读取证据清单，记录最终状态。trace 是按步骤编号的 JSON 可序列化事件，只存动作、候选 ID、计数和状态，不写 SSH/PDK 路径。当前队列是 FIFO，没有论文级优先级、重试变异或成功回收机制。

`save_trace(run_dir)` 可显式独占写入 `agent_trace.json`，含预算、当前队列/pending ID、下一动作和事件。若目录内已有有效 `evidence_manifest.json`，只有其中 `run_id` 与目录名一致才记录该 ID；没有清单则 `run_id=null`，不能冒充有证据运行。重复保存拒绝覆盖。执行器在已分类的结局后自动调用；逐事件日志也已加入，但仍没有崩溃后状态恢复，不能把它称作完整持久化调度系统。

`src/orfadc/agents/executor.py` 现可在现成 trace 目录上自动运行有限预算的 Search -> Evaluate -> Refine -> Stop 循环，并在正常终止或已分类的工具失败后独占保存 trace。evaluator 必须由调用方提供，返回其自行归档的 run 目录；执行器不启动 Cadence，也不把返回目录或异常文本写入 trace。搜索异常、后端异常/超时、非法目录对象分别记录固定失败码。空队列和预算耗尽只是停止原因，不是规格通过。工具的运行日志、超时控制和失败归档仍由 evaluator 负责；意外中断可保留已写事件，但不能自动恢复执行。

```python
manager = Manager(max_searches=1, max_evaluations=1)
manager.search_candidates(spec, seed=0)
candidate = manager.pop_candidate()
refined = manager.record_result(candidate, candidate_run_dir, spec)
assert refined.status != "accepted"  # 尚无原始 fullchain 数据重提取
```

此处 `candidate_run_dir` 需来自受控 backend；示例本身不是现有可运行 LNA 结果。`tests/test_manager.py` 用缺失运行目录和 mock Searcher 验证 Search → Evaluate → Refine → Stop、重复候选、超预算和错候选拒绝；另测 trace 独占保存及 run_id 与证据目录绑定。仅有 trace 中的 `EvaluateCandidate` 不能证明 Spectre 已运行，必须核对实际候选归档。下文已有一个真实**共源诊断**后端回合，仍没有 LNA fullchain 或可接受结果。

`tests/test_agent_executor.py` 覆盖自动循环、无候选、工具异常/超时去敏、目录错误、trace 独占和中断时事件保留。下一门槛是**合格 LNA fullchain** 的有源 evaluator、可信状态恢复、候选变异和优先级；执行器本身已由下文的真实诊断回合调用，`accepted` 仍无可用路径。

执行器现在会在首个动作前独占创建 `agent_events.jsonl`，每次事件写入后刷新到磁盘，终态再保存 `agent_trace.json`。模拟 `KeyboardInterrupt` 的测试证明中断前的 Search/Evaluate 两条事件仍在，而终态快照不存在；这是**增量审计日志**，不是自动恢复执行。异常后队列/pending 的可信重建、原始候选运行目录核验和重复动作防止仍待实现。日志只含既有去敏事件字段，不含 evaluator 异常文本或私有路径。

新增 `agents/journal.py` 的 `inspect_journal(run_dir)` 只读检查执行器日志：首条 `RunStarted` 固定 spec/seed/预算，搜索事件列出已校验候选 ID，后续事件必须符合 FIFO、单 pending、预算、失败及终态转换；若有最终 trace，还会核对事件、计数和证据 run_id。它区分 `complete`、`terminal_snapshot_missing`、`reconcile_pending_evaluation` 和 `interrupted`。所有结果的 `safe_to_auto_resume` 均为 false：日志没有完整候选参数、evaluator 运行目录与原始仿真结果的事务性绑定，不能据此重发 Spectre。旧版无 `RunStarted` 的日志明确拒绝恢复推断；本地一致性检查也不是防篡改签名。模拟中断及损坏日志的测试见 `tests/test_agent_journal.py`。

最小离线调用示意如下，`trace_dir` 必须预先存在且没有 `agent_trace.json` 或 `agent_events.jsonl`。返回不存在的目录只会得到 `needs_evaluation`，不会产生 Cadence 指标：

```python
from pathlib import Path
from orfadc.agents.executor import execute_manager
from orfadc.agents.manager import Manager

outcome = execute_manager(
    Manager(max_searches=1, max_evaluations=1),
    spec,
    lambda candidate: Path("missing_evaluation"),
    trace_dir,
    seed=0,
)
assert outcome.status == "budget_exhausted"  # 停止原因，不是规格通过
```

默认 Searcher 产出的是论文风格的 power-ratio 候选，而阶段 05 的共源诊断后端只接受 RD/VBIAS 两个数值，两者不能直接互接。后续须由工具注册表提供论文四工具的显式映射和参数校验；当前不把诊断后端包装成论文 fullchain evaluator。

## 真实后端的受控诊断回合（2026-09-26）

`src/orfadc/experiments/run_agent_diagnostic.py` 增加**专用** `DiagnosticSearcher`：只提交一个受控 RD/VBIAS 候选，拒绝越界/非有限值；运行前检查私有 OA 网表哈希和宿主 2.66 GiB 物理内存门禁。`execute_manager` 调现有白名单 Cadence 后端，`Refiner` 从候选运行目录的哈希清单读取结果。agent 目录独占保存逐事件 journal、trace 与 `agent_evaluation.json`；索引仅记录相对路径/run_id、后端/证据状态，不复制私有网表或日志。CLI 只有在候选证据**已验证且后端仿真成功**时返回 0；失败归档虽可哈希验证，也返回非零。一个失败运行的 mock 测试和退出码测试覆盖此区别。

本地两个不同 RD 值的真实回合已完成。最终入口语义下的 `results/runs/agent_diagnostic/20260926T111640Z_ee7e8702/` 指向独立候选 `results/runs/S1/seed0/S1_seed0_oa_diag/20260926T111640Z_a1565190/`：S1/seed0，1 次搜索、1 次评估，Spectre 25.1 DC/SP/noise `ok_with_warnings`，47 点原始 PSFASCII 的 9 项指标重提取最大差 0，清单核验通过；日志/trace 为 Search → Evaluate → Refine → Stop。最差 S21 约 -0.44 dB、S11 约 -0.003 dB，采样网格稳定性不满足，且未跑压缩点；Refiner 输出 `needs_evaluation`，`spec_pass=null`。`budget_exhausted` 仅是预算终止，不是成功设计。前一 RD=130 Ω 回合也归档在独立 trace/candidate run 中，但其索引生成于后端状态字段修补前，不回写历史文件。

这是**确定性 Python agent 调用真实诊断工具**的证据，不是论文 Manager/Searcher/Refiner 加真实 LLM 的完整实现。`agent_evaluation.json` 是可查的目录索引；下述摘要校验虽把一次 journal 精炼事件绑定到候选清单，仍不是跨目录签名或事务性恢复，不能用它自动重发仿真。下一门槛仍是可信 fullchain 原始数据重提取、参数变异与恢复、工具注册表、模型接入和真正满足规格的 LNA。

## 候选归档绑定增量

`Manager.record_result` 先核对候选归档清单、spec/seed 和完整候选快照；只有一致时才将 run_id 与清单 SHA-256 写入 `RefineCandidate` 事件。现在清单有效但候选参数、spec、seed、run_id 或读取前后清单内容不一致时，直接拒绝该评估，执行器记录 `EvaluationFailed`，不让异候选结果进入 Refiner。缺失或损坏证据仍由 Refiner 保守返回 `needs_evaluation`。`inspect_journal(..., candidate_runs_root=...)` 从 spec/seed/candidate/run_id 重新构造唯一相对路径，拒绝符号链接、清单变动、文件哈希错误或上下文不符。旧 journal 仍可只读审计，但没有摘要时 `candidate_bindings_verified=false`；所有情况 `safe_to_auto_resume=false`。测试在生成 trace 后修改候选 `metrics.json`，验证跨目录审计拒绝。摘要只提供本地一致性检查，不是对抗具有文件系统写权限者的数字签名。

新独立实测 trace `results/runs/agent_diagnostic/20260926T113051Z_23447ca2/` 绑定候选 `results/runs/S1/seed0/S1_seed0_oa_diag/20260926T113051Z_5475bf0d/`，RD=150 Ω、VBIAS=0.67 V。审计 `complete` 且 `candidate_bindings_verified=true`，Spectre DC/SP/noise 47 点/9 项指标从原始 PSFASCII 独立重提取最大差 0；最差 S21 约 -0.18 dB、S11 约 -0.003 dB、NF 约 4.29 dB。它仍有既有工艺警告、匹配与稳定性问题，无压缩点；Refiner 正确返回 `needs_evaluation`、`spec_pass=null`。

## 论文四工具的受限注册表（接口层）

`src/orfadc/agents/tool_registry.py` 现提供 `AgentToolRegistry(spec).invoke({"tool": ..., "arguments": ...})`，仅允许 Table I 的四个工具名，拒绝多余键、任意 netlist/路径/命令字段、非有限数值、超出电流预算的资源分配和不匹配的候选 ID。默认 `Searcher` 已经通过这个入口调用 `active_sizing`；例如：

```json
{"tool":"active_sizing","arguments":{"power_ratio_list":[0.4,0.3,0.3],"total_current_ma":10}}
```

此调用仅确定分级电流。没有经原始 Cadence 表征绑定的 lookup 时，状态为 `needs_verified_active_lookup`，不生成 W/L/VGS；仅元数据匹配的 lookup 也仍标为未验证。`impedance_matching` 的输入只有可信候选 ID 和 NF headroom；`band_planning` 只有候选 ID 与三级增益目标；`fullchain_eval` 只有候选 ID。模型不得在调用参数里填写 S11、NF、仿真结果、运行目录或 `spec_pass`。后三者目前分别返回缺少有源 lookup/匹配后端、频带规划后端、fullchain 后端的明确状态，不输出成本或“通过”。这仅完成**工具调用契约与默认 Searcher 接线**，尚未实现 Table I 的 Cadence 仿真工具本体；专用 RD/VBIAS 诊断 Searcher 仍走原有白名单后端，不被包装成论文四工具。

测试 `tests/test_agent_tool_registry.py` 覆盖工具白名单、数值/预算/候选上下文、伪造指标和大比例求和溢出；最新全量回归见 `docs/16_implementation_status.md`。下一步把可信 Cadence lookup、Stage 2 PSO、Stage 3 SA 与 fullchain evaluator 逐个接入，同时保持原始文件重提取和 `spec_pass` 门禁；在那之前，LLM 即使接入也不能绕过这些状态。

## 候选参数快照与中断审计增量

新运行的 `agent_candidates.jsonl` 在每次 `SearchCandidates` 事件前持久化一条**未评估**候选批次，包含完整候选参数、spec/seed、搜索步号；搜索事件记录该行 SHA-256。侧文件和事件均刷新到磁盘，旧回合没有该文件也不回填。`inspect_journal` 检查侧文件大小、完整行、候选字段/上下文、有限数值、无仿真成绩、敏感路径/密钥文本拒绝、候选 ID 顺序和事件摘要；额外/缺失/改写记录均拒绝。它只是一致性校验，不是对有本机写权限者的数字签名。新 `candidate_snapshots_verified=true` 不改变 `safe_to_auto_resume=false`：pending 评估仍须人工核对后端是否已经产生结果，执行器没有事务性续跑或幂等重发策略。

这次补丁还修正了 Searcher 在首次搜索前报错时的 trace 上下文缺失：执行器于 `RunStarted` 前绑定 spec/seed，失败回合可被只读审计，且不会执行 evaluator。快照含参数，只留在 Git 忽略的私有运行目录，不写入去敏 trace 或模型请求。

一个全新 RD=160 Ω/VBIAS=0.67 V 的真实单候选诊断回合位于 `results/runs/agent_diagnostic/20260926T213331Z_7b584495/`，绑定独立 Spectre 候选 `results/runs/S1/seed0/S1_seed0_oa_diag/20260926T213331Z_37cca80f/`。journal、快照、trace、候选证据清单均经只读审计；47 点 DC/SP/noise 的原始重提取与归档指标完全一致，后端 `ok_with_warnings`。带内最差 S21 约 `0.046 dB`、S11 约 `-0.003 dB`，仍不满足匹配/稳定性，且无压缩点。`budget_exhausted` 只是预算停止，Refiner 为 `needs_evaluation`、`spec_pass=null`，不得纳入论文 Table IV/V 或成功候选。一次错误 OA 模板在预检阶段被结构门禁拒绝，未启动仿真；随后使用已验收的 v2 模板完成上述新运行。下一门槛是跨进程恢复协议、pending 仿真幂等协调、候选优先级/失败变异及真正 LNA fullchain。

## 首次评估前的受限跨进程恢复（2026-09-27）

新回合在 `RunStarted` 前独占持久化 `agent_spec.json`，其规范 JSON 字节的 SHA-256 进入首个 journal 事件。`inspect_journal` 验证规格数值、摘要和 ID；旧回合仍可只读审计，但因缺少该绑定而 `spec_verified=false`，**不回填旧档**。`agent_writer.lock` 使用 Windows/POSIX 操作系统文件锁；执行器从首个事件到终态 trace 写入都持锁，进程退出或崩溃后由操作系统释放。独立子进程争锁测试确认运行中的另一写者被拒绝，锁释放后可重新取得。

`resume_manager_after_search(spec, evaluator, trace_dir, seed=...)` 只在以下条件全部成立时接管：journal 经审计为 `interrupted`、完整候选快照和规格快照都已验证、规格值及 seed 未变、搜索预算已经用尽、队列非空、**评估次数为 0 且没有 pending**、无终态 trace，并成功独占写者锁。它按快照原顺序重建队列和已见候选 ID，追加 journal 而非重新搜索，随后运行受控 evaluator。任何 `EvaluateCandidate` 已记录、候选档案可能在途、旧格式、损坏/改写快照、规格变化或另一个进程仍持锁时，均**拒绝自动续跑**；不猜测 Spectre 是否已启动，也不幂等重发。被动 `inspect_journal.safe_to_auto_resume` 仍为 false，因为单独读取时没有获取写者锁。这是一条严格的崩溃窗口恢复路径，**不是**完整 pending 协调协议，也没有处理跨机器共享目录/网络文件系统锁语义。

测试 `tests/test_agent_resume.py` 使用纯假 evaluator 验证合法恢复仅评估一次、pending/规格变更/哈希篡改/锁竞争和旧档拒绝。新真实诊断 trace `results/runs/agent_diagnostic/20260927T005553Z_3e9aa553/` 绑定独立候选 `results/runs/S1/seed0/S1_seed0_oa_diag/20260927T005554Z_9f36c477/`：RD=170 Ω、VBIAS=0.67 V，Spectre DC/SP/noise 0 errors/5 条既有模型配置警告；47 点原始 PSFASCII 重提取 9 项指标最大差 0。journal/trace、规格快照、候选快照、候选清单均只读审计通过；带内最差 S11≈-0.0034 dB、S21≈0.241 dB、NF≈4.238 dB，仍 `needs_evaluation`、`not_lna_result=true`、`spec_pass=null`。该新回合验证**正常执行路径**的规格绑定和锁，不冒称实机发生过崩溃恢复；恢复路径只在上述离线故障注入中测过。

首次评估前恢复之外，**新格式诊断后端**又实现了预分配 run ID 的已完成 pending 档案对账，并通过一次真实 Spectre 归档后中断注入；详见 `docs/59_stage10_pending_archive_reconciliation.md`。仍未覆盖远端进程在途判定、崩溃在精炼与终态之间的事务性收尾、失败候选的受限变异及队列优先级。恢复后仍只能由可信 Cadence 后端原始数据评价，不能把诊断共源级当成论文三级 LNA。
