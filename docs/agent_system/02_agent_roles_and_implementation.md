## 8. 多智能体如何“生成”

本文件中的 JSON、指标和 Python 片段用于解释接口与待实现设计，不是当前可运行的完整 agent loop，也不是 LNA 实测结果。实际进度见 `docs/16_implementation_status.md`。

“生成智能体”不是自动凭空生成程序，而是你定义四件事：

1. **角色**：这个 agent 负责什么，不负责什么。
2. **输入**：它能看到哪些信息。
3. **动作**：它允许调用哪些工具。
4. **输出 schema**：它必须返回什么 JSON。

### 8.1 Manager 的定义

角色：

```text
维护全局状态、候选队列、预算和最终报告。
```

输入：

```json
{
  "spec": {},
  "queue": [],
  "latest_reports": [],
  "memory_hits": [],
  "budget": {}
}
```

动作：

```text
SearchCandidates
RefineCandidate
UpdateMemory
Stop
```

输出：

```json
{
  "action": "SearchCandidates",
  "candidate_id": null,
  "arguments": {},
  "reason": "queue is empty",
  "risk_note": "method-level reproduction only"
}
```

### 8.2 Searcher 的定义

角色：

```text
生成新候选，重点解决 Stage 1 和 Stage 2。
```

输入：

```json
{
  "spec": {},
  "queue_summary": [],
  "kb_hits": [],
  "eb_hints": []
}
```

动作：

```text
active_sizing
impedance_matching
return_candidates
```

输出：

```json
{
  "power_ratio_list": [0.4, 0.3, 0.3],
  "nf_headroom_db": 0.2,
  "gain_require_db": 12,
  "candidate_count": 4
}
```

### 8.3 Refiner 的定义

角色：

```text
根据仿真失败指标进行局部修正。
```

输入：

```json
{
  "candidate": {},
  "metrics": {},
  "violation": {},
  "history": []
}
```

动作：

```text
retry_stage2
retry_stage3
retry_stage1
mark_infeasible
accept
```

输出：

```json
{
  "refine_action": "retry_stage3",
  "changes": {
    "gain_distribution": [10, 8, 7]
  },
  "reason": "gain ripple violates target while NF passes"
}
```

## 8A. 三个 agent 的任务和实现细节

本节把 `Manager`、`Searcher`、`Refiner` 拆到可以直接写代码的粒度。先记住一条主线：

```text
Manager 负责“选下一步”
Searcher 负责“找新候选”
Refiner 负责“修旧候选”
```

三者都不直接跑 Cadence。Cadence 由工具层调用。三者都不直接相信 LLM 输出。LLM 输出必须先经过 JSON 解析和 schema 校验。

### 8A.1 RFAmpManager：总调度智能体

#### 8A.1.1 Manager 的核心任务

`RFAmpManager` 是整个多智能体系统的主控。它像项目负责人，不负责亲自设计每个电感电容，而是负责判断：

1. 当前有没有候选设计；
2. 哪个候选最值得继续仿真；
3. 是应该调用 Searcher 生成新候选，还是调用 Refiner 细化旧候选；
4. 是否达到成功条件；
5. 是否仿真预算耗尽；
6. 是否需要查询 KB/EB；
7. 最后输出成功报告或失败报告。

论文中 Manager 的状态空间是候选关键模块的优先队列，动作空间主要是：

```text
SearchCandidates
RefineCandidate
```

本项目实现时可以扩展为：

```text
SearchCandidates
RefineCandidate
UpdateMemory
StopSuccess
StopFailure
```

#### 8A.1.2 Manager 不应该做什么

Manager 不应该：

- 直接生成 W/VGS/L/C/k 等底层参数；
- 直接调用 `ocean`；
- 直接解析 PSF；
- 直接判断某个没有仿真的候选 `pass=true`；
- 直接让 LLM 写 netlist；
- 把 dry-run 结果当成真实结果。

#### 8A.1.3 Manager 的输入

Manager 每一轮应看到：

```json
{
  "spec": {
    "id": "S10",
    "fc_ghz": 30,
    "fbw_ratio": 0.2,
    "power_ma": 30,
    "gain_db": 25,
    "nf_max_db": 3.5,
    "ip1db_min_dbm": -15
  },
  "candidate_queue": [
    {
      "candidate_id": "S10_seed0_search0",
      "priority": -3.2,
      "status": "needs_refine",
      "latest_violation": {
        "nf_violation": 0.3,
        "ip1db_violation": 2.9
      }
    }
  ],
  "latest_reports": [],
  "budget": {
    "max_iterations": 20,
    "used_iterations": 4,
    "max_sims": 200,
    "used_sims": 37
  },
  "memory_summary": {
    "kb_hits": 3,
    "eb_hints": 2
  }
}
```

#### 8A.1.4 Manager 的输出

确定性版本输出 Python 字典即可；LLM 版本必须输出 JSON：

```json
{
  "agent": "manager",
  "action": "RefineCandidate",
  "candidate_id": "S10_seed0_search0",
  "arguments": {
    "refine_budget": 3
  },
  "reason": "This candidate has small NF violation and is closer than newly searched candidates.",
  "stop": false
}
```

#### 8A.1.5 Manager 内部数据结构

建议 Manager 维护：

```python
class Manager:
    queue: list[Candidate]
    completed: list[Candidate]
    failed: list[Candidate]
    iteration: int
    sim_count: int
    best_candidate: Candidate | None
```

Candidate 最好逐步扩展为：

```json
{
  "candidate_id": "S1_seed0_search0",
  "spec_id": "S1",
  "seed": 0,
  "priority": -999.0,
  "power_ratio_list": [0.4, 0.3, 0.3],
  "active_params": {},
  "passive_params": {},
  "sim_result": {},
  "status": "needs_impedance_matching",
  "history": [],
  "notes": []
}
```

#### 8A.1.6 Manager 的最小 Python 实现

当前 MVP 使用 FIFO 和有限预算，实际接口为：

```python
manager = Manager(max_searches=1, max_evaluations=1)
manager.search_candidates(spec, seed=0)
candidate = manager.pop_candidate()  # Consume one evaluation slot.
refined = manager.record_result(candidate, run_dir, spec)
assert refined.status != "accepted"  # Raw fullchain re-extraction is not implemented.
```

`next_action()` 在队列为空时给 `SearchCandidates`，有候选且有预算时给 `EvaluateCandidate`，候选已取出等待后端结果时给 `AwaitEvaluation`，预算结束时给 `Stop`。只有一条 pending 评估；当前实现已持久化 trace、journal 和候选快照。带证据质量的优先级、`StopSuccess`、失败变异后重新入队和已验收的 accepted/completed 列表仍属后续实现，不能把上面的 MVP 描述为论文完整 Manager。

实现进度补充：持久化事件/journal 与候选快照已另行实现；可选 `LLMManagerPolicy` 仅能在**已有队列**中选择下一评估 ID，`QueuePriority` 由 journal 审计并支持派发前恢复，详见 `docs/92_stage11_llm_manager_priority_contract.md`。默认仍 FIFO；完整 Search/Refine/Stop 模型调度、失败变异与合格 LNA 采纳仍未实现。以上旧 MVP 示例用于解释初始状态，不能作为当前能力清单。

#### 8A.1.7 Manager 的验收测试

至少测试：

- 队列为空时返回 `SearchCandidates`；
- 队列非空且有预算时返回 `EvaluateCandidate`；
- 取出候选后返回 `AwaitEvaluation`，回传后按预算转到下一动作；
- 重复 ID、不匹配的 spec/seed 和错位回传被拒绝；
- 未来补测优先级、`StopSuccess`、失败变异与持久化 trace。

### 8A.2 RFAmpSearcher：候选搜索智能体

#### 8A.2.1 Searcher 的核心任务

`RFAmpSearcher` 负责从零产生一批“有希望的初始候选”。它像设计初稿工程师，主要解决：

1. 总电流怎么分到各级；
2. 第一级是否需要更多电流来压低 NF；
3. 后级是否需要更多电流来提高线性度；
4. 是否给 Stage 2 更大的 `NF_headroom`；
5. 是否对第一级 gain 做约束；
6. 调用 `active_sizing()` 生成有源候选；
7. 调用 `impedance_matching()` 做关键级初始匹配；
8. 把候选交给 Manager。

论文中 Searcher 的输入是搜索指令和当前候选队列，输出是一组新候选 `Delta S`。对三阶段 LNA，关键级包括第一级晶体管及输入/输出匹配网络，以及作为第一级负载的第二级晶体管。

#### 8A.2.2 Searcher 不应该做什么

Searcher 不应该：

- 做完整 fullchain final pass 判断；
- 负责最终报告；
- 在没有仿真时声称候选满足 NF/S11；
- 无限生成候选；
- 直接操作 PDK netlist；
- 负责所有后续 refinement。

#### 8A.2.3 Searcher 的输入

```json
{
  "spec": {
    "id": "S7",
    "fc_ghz": 30,
    "fbw_ratio": 0.2,
    "power_ma": 30,
    "gain_db": 25,
    "nf_max_db": 2.5,
    "ip1db_min_dbm": -25
  },
  "queue_summary": [],
  "kb_hits": [],
  "eb_hints": [
    {
      "insight": "Low NF tasks benefit from larger first-stage current.",
      "confidence": 0.7
    }
  ],
  "search_budget": {
    "max_new_candidates": 4
  }
}
```

#### 8A.2.4 Searcher 的输出

```json
{
  "agent": "searcher",
  "new_candidates": [
    {
      "candidate_id": "S7_seed0_search0",
      "power_ratio_list": [0.5, 0.25, 0.25],
      "nf_headroom_db": 0.4,
      "gain_require_db": 12,
      "active_params": {},
      "passive_params": {},
      "status": "needs_fullchain_eval"
    }
  ],
  "summary": "Generated low-NF candidates with increased first-stage current."
}
```

#### 8A.2.5 Searcher 的工程启发规则

第一版可以不用 LLM，直接用规则：

| 规格特征 | Searcher 策略 |
|---|---|
| `nf_max_db <= 3.5` | 增大第一级电流比例，例如 `[0.5,0.25,0.25]` |
| `ip1db_min_dbm >= -15` | 给后级更多电流，例如 `[0.35,0.30,0.35]` |
| `fbw_ratio >= 0.6` | 生成更多 band planning 候选 |
| `power_ma <= 15` | 避免过高第一级电流，保留低功耗候选 |
| 普通任务 | 从 `[0.4,0.3,0.3]` 开始 |

#### 8A.2.6 Searcher 调用的工具

Searcher 主要调用：

```text
active_sizing(power_ratio_list, total_current_ma, lookup_table)
impedance_matching(active_params, nf_user_db, nf_headroom_db, gain_require_db)
```

工具调用顺序：

```text
power_ratio_list
-> active_sizing()
-> active_params candidates
-> impedance_matching()
-> passive params for critical stage
-> new Candidate
```

#### 8A.2.7 Searcher 的最小 Python 实现

当前项目已有：

```python
class Searcher:
    def __init__(self, power_ratio_options=None):
        self.power_ratio_options = power_ratio_options or [[0.4, 0.3, 0.3]]

    def search(self, spec, seed=0):
        candidates = []
        for index, ratios in enumerate(self.power_ratio_options):
            active = active_sizing(ratios, spec.power_ma)
            candidates.append(Candidate(...))
        return candidates
```

下一步应扩展：

```python
def propose_power_ratios(spec):
    ratios = [[0.4, 0.3, 0.3]]
    if spec.nf_max_db <= 3.5:
        ratios.append([0.5, 0.25, 0.25])
    if spec.ip1db_min_dbm >= -15:
        ratios.append([0.35, 0.30, 0.35])
    if spec.power_ma <= 15:
        ratios.append([0.34, 0.33, 0.33])
    return ratios
```

再把每个候选写入 history：

```json
{
  "agent": "searcher",
  "action": "active_sizing",
  "arguments": {
    "power_ratio_list": [0.5, 0.25, 0.25]
  },
  "result": "candidate_created"
}
```

#### 8A.2.8 Searcher 的验收测试

至少测试：

- S1 生成默认 `[0.4,0.3,0.3]`；
- S7 低 NF 任务生成偏第一级的 power ratio；
- S9/S10 高线性度任务生成偏后级的 power ratio；
- 每个候选有唯一 `candidate_id`；
- 每个候选 status 初始合理，例如 `needs_impedance_matching` 或 `needs_fullchain_eval`。

### 8A.3 RFAmpRefiner：候选细化智能体

#### 8A.3.1 Refiner 的核心任务

`RFAmpRefiner` 负责看仿真失败原因，并决定最小回溯步骤。它像调试工程师。

它不从零生成候选，而是拿到一个已有候选和仿真结果，然后判断：

1. 是 NF 不够；
2. 是 S11 不够；
3. 是 gain 不够；
4. 是 ripple 太大；
5. 是 IP1dB 不够；
6. 是 power 超预算；
7. 是多个指标同时失败；
8. 应该回到 Stage 2、Stage 3，还是 Stage 1。

论文中 Refiner 的停止条件：

- 所有用户约束满足；
- 仿真或迭代预算耗尽；
- 候选在当前约束下被判定不可行。

#### 8A.3.2 Refiner 不应该做什么

Refiner 不应该：

- 忽略仿真结果随便调；
- 一次改太多无关参数；
- 把失败候选删除不记录；
- 在没有 fullchain eval 时接受候选；
- 无限制重复同一类 refinement；
- 直接写 netlist。

#### 8A.3.3 Refiner 的输入

```json
{
  "candidate": {
    "candidate_id": "S10_seed0_search0",
    "power_ratio_list": [0.45, 0.25, 0.30],
    "active_params": {},
    "passive_params": {},
    "history": []
  },
  "metrics": {
    "s11_db_worst": -18.0,
    "s21_db_min": 24.2,
    "nf_db_worst": 3.8,
    "ip1db_dbm": -18.5,
    "power_ma": 29.7,
    "ripple_db": 2.1
  },
  "violation": {
    "s11_violation": 2.0,
    "gain_violation": 0.8,
    "nf_violation": 0.3,
    "ip1db_violation": 3.5,
    "power_violation": 0.0
  },
  "refine_budget": {
    "used_refine_steps": 1,
    "max_refine_steps": 8
  }
}
```

#### 8A.3.4 Refiner 的输出

```json
{
  "agent": "refiner",
  "candidate_id": "S10_seed0_search0",
  "refine_action": "retry_stage1_or_stage3",
  "changes": {
    "power_ratio_list": [0.40, 0.25, 0.35],
    "target_gain_stage1_db": 8.5,
    "nf_headroom_db": 0.45
  },
  "status": "retry_stage1_or_stage3",
  "reason": "NF and IP1dB both fail; reduce first-stage gain pressure and reserve output-stage linearity."
}
```

#### 8A.3.5 Refiner 的规则表

第一版建议用明确规则，不要先上 LLM：

| 失败指标 | 物理含义 | Refiner 动作 |
|---|---|---|
| `nf_violation > 0` 且其他基本正常 | 第一级噪声不够 | 增加 `NF_headroom`，回到 Stage 2 |
| `s11_violation > 0` 且 NF 正常 | 输入匹配不够 | 调 `Ls/Lg/MCR/balun`，回到 Stage 2 |
| `gain_violation > 0` | 通带最低增益不够 | 提高总 gain 分配，回到 Stage 3 |
| `ripple_violation > 0` | 宽带峰位/网络规划不好 | 调 MCR 峰位和 Q，回到 Stage 3 |
| `ip1db_violation > 0` | 线性度不够，某级压缩 | 降低前级 gain 或增加后级电流，回到 Stage 1/3 |
| `power_violation > 0` | 电流超预算 | 重新分配电流，缩小非关键级 |
| NF 和 IP1dB 同时失败 | 低噪声和线性度冲突 | Stage 1 重新分配电流和 gain |
| 多次相同失败 | 局部不可行 | 标记 `infeasible` |

#### 8A.3.6 Refiner 的最小 Python 实现

当前代码入口是 `Refiner.refine(candidate, result, spec)`，其中 `result` 应由受控仿真 backend 从原始产物构造，而不是由 LLM 填写。它先运行指标 envelope 校验，核对候选 ID、seed、spec、频带、Cadence 来源与 DC/SP/noise/compression 分析，再调用本地 `fullchain_violations` **重算**五项违规量。`refine_from_run` 可额外核对同一运行目录的文件哈希，并让失败候选得到回溯建议。缺测、来源不符、仅有模型声称的 `pass/total_violation` 或未独立重提取的“零违规”都只能返回 `needs_evaluation`。当前**没有任何可达的 `accepted` 分支**；只有在真实 fullchain backend 从原始数据重算并验证后，才允许补上这个分支。不能把 mock 测试说成 agent 闭环完成。

后续应补充：可追溯的后端原始产物绑定；NF 与 IP1dB 同时失败时的联合回溯；由仿真频率曲线计算而非信任输入字段的 ripple violation；失败次数/预算停止规则、candidate history 和 Manager 队列。结果 JSON 的字段校验无法单独证明仿真真实性，Manager 不得把 LLM 提交的指标直接送入 Refiner。

#### 8A.3.7 Refiner 的验收测试

至少测试：

- NF fail -> `retry_stage2`；
- S11 fail -> `retry_stage2`；
- gain/ripple fail -> `retry_stage3`；
- IP1dB fail -> `retry_stage1_or_stage3`；
- 当前零违规 mock/文件哈希清单 -> `needs_evaluation`；将来原始数据独立重提取和后端来源均验收通过 -> 才允许 `accepted`；
- 连续失败次数超过阈值 -> `infeasible`；
- 每次 refine 都向 candidate history 写入原因。

### 8A.4 三个 agent 的协作接口

为了避免代码混乱，三者之间不要互相直接调用内部细节。推荐统一事件格式。

#### 8A.4.1 Agent action record

```json
{
  "step": 3,
  "agent": "manager",
  "action": "RefineCandidate",
  "candidate_id": "S1_seed0_search0",
  "arguments": {},
  "timestamp": "2026-08-05T10:00:00",
  "status": "ok"
}
```

#### 8A.4.2 Tool observation record

```json
{
  "step": 4,
  "tool": "fullchain_eval",
  "candidate_id": "S1_seed0_search0",
  "status": "dry_run",
  "metrics": null,
  "note": "dry_run cannot be accepted as simulation pass"
}
```

#### 8A.4.3 Refine report

```json
{
  "candidate_id": "S1_seed0_search0",
  "success": false,
  "violations": {
    "nf_violation": 0.2
  },
  "next_stage": "stage2",
  "reason": "NF exceeds target after fullchain evaluation."
}
```

### 8A.5 三个 agent 的实现顺序

不要同时实现所有高级功能。建议顺序：

1. `Manager` 增加 queue 管理。
2. `Searcher` 增加基于 spec 的 power ratio 规则。
3. `Refiner` 增加完整 violation 规则表。
4. `trace.py` 记录 action/observation。
5. `run_agent_loop.py` 串起三者。
6. `memory.py` 写 KB/EB。
7. `llm_policy.py` 接 mock LLM。
8. 最后接真实 LLM。

### 8A.6 三个 agent 和 LLM backend 的关系

确定性阶段：

```text
Manager/Searcher/Refiner = Python rules
```

Mock LLM 阶段：

```text
Manager/Searcher/Refiner = Python shell + mock JSON policy
```

真实 LLM 阶段：

```text
Manager/Searcher/Refiner = Python shell + prompt + LLM JSON policy + schema validator + fallback
```

也就是说，LLM backend 是可插拔策略，不是 agent 文件本身。即使没有模型，本项目也应该能跑通最小 agent loop。

