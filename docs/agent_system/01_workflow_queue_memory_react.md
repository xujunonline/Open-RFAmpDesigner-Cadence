## 4. 一次完整设计任务如何流动

假设用户给出规格：

```yaml
spec_id: S10
fc_ghz: 30
fbw_ratio: 0.20
power_ma: 30
gain_db: 25
nf_max_db: 3.5
ip1db_min_dbm: -15
```

### 4.1 Step 1：Manager 读取规格

Manager 判断：

- NF 要求比普通 S1/S2 更紧；
- IP1dB 要求也更高；
- 所以这是 `nf-hard + linearity-hard` 任务；
- 不能盲目做平坦 GA/BO 搜索；
- 应先从 KB 检索相似任务，如果没有，再调用 Searcher。

Manager 状态：

```json
{
  "spec_id": "S10",
  "queue": [],
  "budget": {
    "max_sims": 200,
    "max_time_s": 18000
  },
  "next_action": "SearchCandidates"
}
```

### 4.2 Step 2：Searcher 生成初始候选

Searcher 做的不是直接生成完整 netlist，而是生成设计意图：

- 第一级多给一点电流，因为 NF 紧；
- 后级保留线性度余量，因为 IP1dB 紧；
- 尝试多个 `power_ratio_list`；
- 对每个电流分配调用 active sizing；
- 对关键级调用 impedance matching。

典型输出：

```json
{
  "new_candidates": [
    {
      "candidate_id": "S10_seed0_search0",
      "power_ratio_list": [0.45, 0.25, 0.30],
      "nf_headroom_db": 0.35,
      "target_gain_stage1_db": 10,
      "status": "needs_stage2_matching"
    },
    {
      "candidate_id": "S10_seed0_search1",
      "power_ratio_list": [0.35, 0.30, 0.35],
      "nf_headroom_db": 0.25,
      "target_gain_stage1_db": 9,
      "status": "needs_stage2_matching"
    }
  ]
}
```

这些候选进入 Manager 的 candidate queue。

### 4.3 Step 3：工具中间件调用 Cadence

工具不是 agent，本质是 Python 函数。Searcher 或 Refiner 只能通过工具调用 Cadence。

流程：

```text
active_sizing()
  -> 根据 power_ratio_list 查 lookup table
  -> 输出 W/VGS/gm/Id/阻抗候选

impedance_matching()
  -> 写 Cadence 参数
  -> 调 run_sparam.ocn 和 run_noise.ocn
  -> 解析 S11/NF
  -> 计算 Stage 2 cost

band_planning()
  -> 用低保真 MCR/RLC 模型算通带 gain/ripple
  -> 必要时少量 Cadence 校准

fullchain_eval()
  -> 调完整 S 参数、noise、compression 仿真
  -> 输出 metrics.json
```

Agent 不直接碰 `ocean` 命令，agent 只看到工具返回的 observation。

### 4.4 Step 4：Refiner 读取失败指标

假设 fullchain 结果：

```json
{
  "s11_db_worst": -18.0,
  "s21_db_min": 24.2,
  "nf_db_worst": 3.8,
  "ip1db_dbm": -18.5,
  "power_ma": 29.7,
  "ripple_db": 2.1,
  "pass": false,
  "violation": {
    "s11_violation": 2.0,
    "gain_violation": 0.8,
    "nf_violation": 0.3,
    "ip1db_violation": 3.5,
    "power_violation": 0.0
  }
}
```

Refiner 判断：

- NF 失败：说明第一级噪声余量不够；
- IP1dB 也失败：说明线性度瓶颈严重；
- 不能只调匹配，可能要降低前级增益或重新分配电流；
- 回到 Stage 2/3，如果连续失败，回到 Stage 1。

Refiner 输出：

```json
{
  "candidate_id": "S10_seed0_search0",
  "refine_action": "retry_stage1_or_stage3",
  "changes": {
    "power_ratio_list": [0.40, 0.25, 0.35],
    "target_gain_stage1_db": 8.5,
    "nf_headroom_db": 0.45
  },
  "reason": "NF and IP1dB both fail; reduce first-stage gain pressure and reserve more output-stage linearity."
}
```

### 4.5 Step 5：Manager 更新队列

Manager 根据 Refiner 报告更新优先级：

- 如果候选接近 pass，则继续 refine；
- 如果失败幅度太大，则降权；
- 如果所有候选都失败，则重新调用 Searcher；
- 如果有 pass 候选，则 Stop 并输出 final report。

## 5. Candidate queue 是什么

Candidate queue 是 Manager 的“候选方案队列”。它不是简单列表，而是带优先级的列表。

每个候选至少包含：

```json
{
  "candidate_id": "S1_seed0_search0",
  "spec_id": "S1",
  "seed": 0,
  "priority": 0.82,
  "power_ratio_list": [0.4, 0.3, 0.3],
  "active_params": {},
  "passive_params": {},
  "latest_metrics": {},
  "status": "needs_refine",
  "history": [
    {"action": "SearchCandidates", "result": "created"},
    {"action": "FullchainEval", "result": "nf_fail"}
  ]
}
```

优先级可以先用简单规则：

```text
priority = - total_violation
```

后续升级为：

```text
priority =
  - total_violation
  - 0.1 * estimated_runtime
  + 0.5 * memory_similarity_bonus
  + 0.3 * improvement_trend
```

## 6. KB 和 EB 的区别

以下 KB/EB JSON 中的数值用于说明数据结构，不代表本项目已完成 Cadence LNA 仿真或得到通过候选。

很多初学者会混淆 KB 和 EB。可以这样理解：

### 6.1 KB：事实数据库

KB 保存“发生过什么”。

例子：

```json
{
  "type": "kb_record",
  "spec_id": "S4",
  "candidate_id": "S4_seed2_cand004",
  "params": {
    "power_ratio_list": [0.4, 0.3, 0.3]
  },
  "metrics": {
    "s21_db_min": 25.4,
    "nf_db_worst": 4.6,
    "ip1db_dbm": -24.0
  },
  "pass": true
}
```

用途：新任务来时，Manager 从 KB 找相似规格的成功候选，作为初始候选。

### 6.2 EB：经验数据库

EB 保存“从事实中总结出的设计经验”。

例子：

```json
{
  "type": "eb_record",
  "condition": "30 GHz, 20% BW, tight IP1dB",
  "insight": "First-stage gain above 12 dB tends to worsen compression; reserve at least 6 dB gain for stage 2.",
  "source_candidates": ["S9_seed1_cand003", "S10_seed0_cand008"],
  "confidence": 0.7
}
```

用途：给 Searcher/Refiner 提示，不是直接当作事实。

### 6.3 为什么两者都需要

只用 KB：能找相似候选，但不知道为什么成功。  
只用 EB：有经验，但缺少具体参数起点。  
KB + EB：既有候选起点，也有调参方向。

## 7. ReAct 在这里是什么意思

ReAct = Reason + Act。中文可以理解为“先解释为什么，再调用工具，再看结果，再反思”。

在本工程中不要让 LLM 输出长篇内部推理，只保存简短工程理由即可。

一个合规 ReAct 记录：

```json
{
  "thought_summary": "NF is tight and current budget is normal, so increase first-stage current ratio and Stage 2 NF headroom.",
  "action": "impedance_matching",
  "arguments": {
    "candidate_id": "S7_seed0_search0",
    "nf_headroom_db": 0.4
  },
  "observation": {
    "nf_db": 2.8,
    "s11_db": -21.0,
    "stage2_cost": 300.0
  },
  "reflection": "S11 passes but NF still fails; retry with larger first-stage device or current."
}
```

