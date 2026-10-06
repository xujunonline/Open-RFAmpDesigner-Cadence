# 131 智能体实现 v2：LLM 驱动的 ReAct Manager / Searcher / Refiner（设计）

> 阶段：docs/130 A2。实现：`src/orfadc/repro/agents_v2.py`、`src/orfadc/repro/prompts/v2/*.md`。
> 本文档先于代码写成，代码与本文不一致时以本文为准修改代码（或在此处记录变更）。
> v2 只是新增模块；v1（`agents.py` + `llm.py`）不变，默认仍是 v1（docs/130 约束 4）。

## 1. v1 与 v2 的区别

| | v1（`agents.py`/`llm.py`，docs/119、127） | v2（本文） |
|---|---|---|
| Manager | 程序循环；LLM 只在 `next_split` 选功率分配 | LLM ReAct 循环：自己决定何时搜索、细化哪个候选、何时停 |
| Searcher | 程序：固定枚举 4 配置 × 2 增益目标 | LLM ReAct 循环：自己调用 `active_sizing` / `impedance_matching`，自己选返回哪些候选 |
| Refiner | 程序循环；LLM 只在 `refine_action` 选动作 | LLM ReAct 循环：自己调用 `band_planning` / `fullchain_evaluation`（及同配置的 Stage 2 重综合） |
| LLM 失败 | 回落 `RulePolicy`（计 `fallbacks`） | **不回落**：错误观测让 LLM 重试；连续失败或超限即终止并写 `terminated_reason` |
| 功率比范围 | 校验 0.1–0.8（提示词写 0.15–0.7，docs/129 §3-2） | 提示词与校验都来自 `llm.V2_SPLIT_RANGE` = (0.15, 0.7) |

## 2. 与论文的逐条对应（Sec. II-C、Fig. 6）

| 论文 | v2 实现 |
|---|---|
| 两层架构：中央主智能体 + 两个无状态子智能体 | `ManagerAgent` 持有会话状态（候选队列、已试分配、报告）；`SearcherAgent`/`RefinerAgent` 每次调用新建，不带上一次的对话 |
| 每个智能体执行基于 ReAct 的多轮循环，标准化 schema | `ReActAgent.run()`：每步 LLM 输出 `<rationale>…</rationale><tools>{"tool":…, "args":{…}}</tools>`，执行后回填 `<observation>` |
| 每个智能体支持自主提前终止 | 每个智能体都有 `finish` 工具 |
| Manager 动作空间 {SearchCandidates, RefineCandidate}，状态为候选优先队列 | Manager 工具 `search_candidates`、`refine_candidate`（调用子智能体），另有只读的 `list_candidates`、`query_memory`，以及模式 2 的 `load_kb_candidates` |
| Manager 沿 NF、线性度、大信号三轴排序候选 | `list_candidates` 给出每个候选的关键级 NF / IP1dB / 增益 / 可行性；排序由 LLM 决定（另附 v1 规则分数 `rule_score` 作参考） |
| Searcher：先提出前两级功率分配；每种分配枚举两种极端尺寸；每种尺寸两种综合变体（带/不带增益约束） | Searcher 工具 `active_sizing(power_ratio_list)`（Stage 1，返回 4 个极端配置）、`impedance_matching(power_ratio_list, config_id, nf_headroom_db, gain_require_db)`（Stage 2）；`finish(cids)` 返回 ΔS |
| Refiner：剩余变量为第三级功率与第二、三级增益分配；直到满足约束或预算耗尽；不可行时提前终止并返回失败报告 | Refiner 工具 `band_planning(cid, gain_user_db, gain_req_list)`（Stage 3）、`fullchain_evaluation(did)`（Stage 4）、`impedance_matching(nf_headroom_db, gain_require_db)`（同一分配与配置下重做 Stage 2，即论文的分级回溯）；`finish(success, did, bottleneck, reason)` |
| 总结报告：成功标志、性能指标、违反的约束及幅度、简要失败原因 | Refiner 返回 `{success, did, metrics, violations, bottleneck, reason, steps, terminated_reason}`（与 v1 `RefineReport` 同字段） |
| KB：Searcher/Refiner 保存结构化设计记录；EB：Refiner 按模板保存推导指标 | 每次 Refiner 结束（有评估过的设计时）写 KB/EB，字段与 v1 `_remember` 相同，另加 `agent_impl`、`pdk` |
| 检索-细化模式：Manager 查询 KB top-k 预加载；EB 提供初始化提示与剪枝 | 模式 2：Manager 任务中给出 EB 洞察；`query_memory` 返回 KB top-k 摘要与 EB；`load_kb_candidates(k)` 预加载（Stage 2 重综合，计仿真费用） |
| Fig. 6 对话格式 `<think>…</think><tools>…</tools><observation>…</observation><answer>…</answer>` | 用 `<rationale>` 代替 `<think>`（要求模型输出推理会触发 Claude 的 reasoning_extraction 防护，见 `llm.py` 文件头）；`finish` 对应 `<answer>` |

## 3. ReAct 循环（`ReActAgent`）

每步：
1. 组装用户消息：任务（JSON）+ 历史（最近 6 步完整的动作与观测，更早的步骤每步一行摘要）+ 剩余预算（等效 EDA 秒、LLM 调用余量、本智能体剩余步数）。
   传输层是无状态的 `complete(system, user)`（与 v1 相同的 claude-cli / codex-mcp / anthropic / openai / scripted），所以每步重发裁剪后的历史。
2. 调用 LLM（计 1 次调用、token、延迟）。
3. 解析 `<tools>` 中的 JSON：`{"tool": 名称, "args": {…}}`。
4. 校验：工具存在、参数名与类型、取值范围（功率比 0.15–0.7 且和为 1、未重复；`nf_headroom_db` 0–3；`gain_require_db` 0–45；候选/设计 id 存在）。
   非法 → 观测 `{"error": …}`，计 `invalid_actions`，回到 1 让 LLM 重试。
5. 执行工具；观测经 `_public`（去私有键、浮点保留 4 位）后截断到 3000 字符。

终止（`terminated_reason`）：

| 原因 | 条件 | 作用范围 |
|---|---|---|
| `finish` | LLM 调用 `finish` | 本智能体 |
| `spec_met` | Refiner 的 `fullchain_evaluation` 通过（自动结束，不再花 LLM 调用） | Refiner |
| `max_steps` | 本智能体步数到上限（Manager 60、Searcher 24、Refiner 16） | 本智能体 |
| `invalid_actions` | 连续 3 次非法动作 | 本智能体 |
| `eda_budget` | `SimCounter.exhausted()`（等效时间预算或 Spectre 每设计上限） | 全局 |
| `llm_call_cap` | LLM 调用次数达到 `ORFADC_LLM_MAX_CALLS`（默认 200） | 全局 |
| `llm_unavailable` | 连续 3 次传输错误（网络、额度、认证、超时） | 全局 |

全局终止时子智能体立即返回，Manager 不再调用 LLM，直接汇总已有结果。**不会**换成规则策略继续跑。
子智能体因本地原因终止时，返回已有结果（Searcher：已生成的候选；Refiner：违例最小的已评估设计），由 Manager 决定下一步。

## 4. 预算记账

- 等效 EDA 时间：沿用 `SimCounter`（`tools.EQUIV_COST_S`）与 `bench.budget_for`（S1–S8 1 h，S9/S10 5 h，`ORFADC_BUDGET_SCALE` 缩放）。
  v2 的工具调用逐个顺序执行，`ORFADC_PARALLEL` 不作用于 Searcher 扇出（v2 没有程序化扇出）；PSO 粒子等工具内部的并行规则不变。
- LLM：调用上限 `ORFADC_LLM_MAX_CALLS`，Manager 与子智能体共用一个计数。LLM 时间不计入等效 EDA 时间（与 v1 相同），单独记录延迟与 token。
- 两个预算先到先停。
- Spectre：`ORFADC_SPECTRE_MAX_PER_DESIGN` 通过 `SimCounter.hard_stop` 生效（A1 已让 cadence 与 pdk 后端都遵守）。

## 5. 记忆

- 沿用 `memory.MemoryStore`（KB/EB JSONL）。v2 写入的记录多两个字段：`agent_impl: "v2"`、`pdk`（无 PDK 时为 null）。
- 默认目录按实现与工艺分开：`results/memory/repro`（v1，原样）、`results/memory/repro_v2`、`…_n65`（N65 PDK）。`--memory` 显式指定时以指定为准。

## 6. 开关与输出

- `ORFADC_AGENT_IMPL=v2` 或 `bench design --agent-impl v2`；MCP `run_autonomous(agent_impl="v2")`。
- v2 必须配 LLM 策略（`scripted`、`claude-cli`、`codex-mcp`、`anthropic`、`openai`）；`--policy rule` 与 v2 组合报错。
- 输出文件名带 `_v2`（A1 的后缀规则）。结果 JSON 字段与 v1 相同（`success`、`report`、`sims`、`n_search`、`n_refine`、`splits_tried`、`design`、`sweep`、`trace`），另有：
  `agent_impl`、`terminated_reason`、`llm_usage`（调用、token、延迟、错误、`invalid_actions`；`fallbacks` 与 `rule_after_disable` 恒为 0）、
  `llm_log`（每步：智能体、步号、动作、观测摘要、token、延迟）。

## 7. 离线验证（`scripted`）

`ScriptedReActTransport`：先消耗一段预置回复（字符串或异常），之后由"规则神谕"生成合法动作（各智能体的 `oracle()` 按 v1 规则策略给出下一步；只供离线测试，真实运行中从不使用）。
测试覆盖：正常完成（S2 端到端，`terminated_reason=finish`）、非法动作（错误观测后恢复；连续 3 次终止）、超预算（`eda_budget`）、LLM 中断（`llm_unavailable`）、调用上限（`llm_call_cap`）。

## 8. 离线验证记录（2026-10-06，A2）

- 代码：`agents_v2.py`、`prompts/v2/{manager,searcher,refiner}.md`；接入 `bench design --agent-impl v2`、MCP `run_autonomous(agent_impl=…)`。
- 测试：`tests/test_repro_agents_v2.py` 12 项（正常完成、非法动作重试、连续 3 次非法终止、`eda_budget`、开局与子智能体内的 `llm_unavailable`、`llm_call_cap`、提示词与校验同源、工具守卫、模式 2 记忆标签与 KB 预加载、记忆目录、bench 开关）；全量 111 passed。
- S2 seed 0、1 h、代理后端、`scripted`（规则神谕，不代表 LLM 能力）：通过，`terminated_reason=spec_met`，3 次搜索、3 次细化，
  等效 2036 s，66 次（离线）调用（Manager 6 / Searcher 30 / Refiner 30）。同条件 v1 规则策略：通过，等效 1901 s，3/3。
  差异来自 v2 的功率比范围：v1 第三个分配 [0.35, 0.1, 0.55] 超出 0.15–0.7，神谕改取 [0.325, 0.15, 0.525]。
- 调用量提示：每次细化迭代需要 `band_planning` + `fullchain_evaluation` 两次调用，S2 一次设计约 60–70 次调用；
  S9s/S10s 5 h 预算下预计数百次，A3 的论文口径上限 1000 次足够，200 次默认上限可能先到。
- v1 冻结：`replot` Table IV/V 与 SUMMARY 与 2026-10-03 逐字节一致（生成时间行除外）；S2 rule JSON 与 v1.1 相比只多 `labels`（`cpu_s`、`t` 为墙钟时间）。

## 9. 边界

- v2 的结论只在真实 LLM 运行（A3，需确认）后才有意义；离线 `scripted` 只验证协议与记账，不代表 LLM 能力。
- 代理后端结果仍是趋势级证据；PDK 结果是原理图级、无版图寄生（docs/130 约束 8）。
