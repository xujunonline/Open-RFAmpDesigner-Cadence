## 9. 本工程中的推荐代码架构

建议逐步扩展为：

```text
src/orfadc/agents/
├─ manager.py          # 全局调度
├─ searcher.py         # 新候选生成
├─ refiner.py          # 失败诊断和回溯
├─ memory.py           # KB/EB JSONL
├─ policy.py           # 确定性策略接口
├─ llm_policy.py       # LLM JSON 策略
├─ tool_registry.py    # agent 可调用工具注册表
├─ trace.py            # agent_trace.json
└─ prompts/
   ├─ manager.md
   ├─ searcher.md
   └─ refiner.md
```

工具层保持独立：

```text
src/orfadc/tools/
├─ active_sizing.py
├─ impedance_matching.py
├─ band_planning.py
├─ fullchain_eval.py
└─ cost_functions.py
```

Cadence 层保持独立：

```text
src/orfadc/cadence/
├─ run_ocean.py
├─ run_spectre.py
├─ parse_psf.py
├─ extract_rf_metrics.py
└─ netlist_template.py
```

这种分层非常重要：  
Agent 不直接运行 Cadence，Tool 不直接调用 LLM，Cadence 层不理解多智能体。

## 10. 最小可运行 agent loop 方案

第一版实现目标：

```text
run_agent_loop.py --spec S1 --seed 0 --dry-run
```

执行逻辑：

```python
spec = load_spec("S1")
manager = Manager()
searcher = Searcher()
refiner = Refiner()
memory = JsonlMemory(...)

while budget_not_exhausted:
    action = manager.next_action()
    if action == "SearchCandidates":
        manager.search_candidates(spec, seed)
    elif action == "EvaluateCandidate":
        candidate = manager.pop_candidate()
        run_dir = backend.run(candidate)  # Planned: not implemented yet.
        refined = manager.record_result(candidate, run_dir, spec, refiner)
        # Planned: revise parameters before requeueing a failed candidate.
    elif action == "AwaitEvaluation":
        wait_for_backend_or_record_failure()
    elif action == "Stop":
        break
```

dry-run 下：

- Searcher 只生成结构化候选；
- fullchain_eval 返回 `status=dry_run`；
- Refiner 不允许接受为真实 pass；
- agent_trace 仍然记录完整流程。

上面的 `backend.run`、`wait_for_backend_or_record_failure` 和可执行的 `run_agent_loop.py` 仍是设计目标，不是当前仓库已经提供的函数。当前 Manager 的预算/去重/单 pending 转移仅有 mock 测试；详见 `docs/26_deterministic_manager_mvp.md`。

## 11. 真实 LLM 接入方案

LLM 接入点不是替换整个系统，而是替换 policy：

```text
DeterministicPolicy -> LlmJsonPolicy
```

确定性版本：

```python
action = policy.decide(state)
```

LLM 版本：

```python
prompt = render_prompt(state)
raw = llm_client.complete(prompt)
action = parse_json(raw)
action = validate_schema(action)
```

必须有 fallback：

```text
如果 JSON 解析失败 -> deterministic policy
如果 action 不在允许列表 -> deterministic policy
如果 arguments 缺字段 -> deterministic policy
如果 LLM 要求直接写 netlist -> 拒绝
```

## 12. 多智能体和 Cadence 的关系

多智能体不会替你画版图，也不会魔法般知道 PDK。它只决定“下一步该跑什么仿真/该调什么参数”。

真正产生可信结果的是：

```text
Virtuoso schematic
-> Spectre netlist
-> OCEAN/Spectre simulation
-> PSF/CSV
-> Python metrics
-> Agent observation
```

所以结果可信度顺序是：

1. Cadence/Spectre 真实仿真结果；
2. Python 从真实结果提取的 metrics；
3. 工具中间件计算的 cost；
4. Agent 对 cost 的解释和下一步策略。

Agent 的解释不能替代仿真。

## 13. 如何判断多智能体做得好不好

不要只看它说得像不像专家。要看实验指标：

| 指标 | 含义 |
|---|---|
| pass@1 | 5 个 seeds 中有几个成功 |
| avg_time_s | 平均找到可行解耗时 |
| num_sims | 用了多少次 Cadence 仿真 |
| num_search | 调用了几次 Searcher |
| num_refine | 调用了几次 Refiner |
| total_violation trend | violation 是否逐步下降 |
| token cost | LLM 使用成本 |

如果 LLM 说得很好但 violation 不下降，它没有用。  
如果确定性规则比 LLM 更稳定，先保留确定性规则。

## 14. 本项目建议的实现里程碑

### 里程碑 A：无 LLM agent loop

目标：

- Manager/Searcher/Refiner 能跑 dry-run；
- agent_trace.json 能生成；
- KB/EB 能写入。

### 里程碑 B：接入真实 metrics

目标：

- fullchain_eval 返回真实 Cadence metrics；
- Refiner 根据真实 violation 回溯；
- 队列优先级能更新。

### 里程碑 C：Mock LLM

目标：

- prompts 可渲染；
- JSON parser 可用；
- schema 校验可用；
- fallback 可用。

### 里程碑 D：真实 LLM

目标：

- LLM 只输出 JSON；
- token/latency 记录；
- 不接触 PDK；
- 与确定性版本对比。

### 里程碑 E：消融实验

目标：

- full multi-agent；
- single-agent；
- without Refiner；
- without ReAct；
- with/without EB；
- tool-only baseline。

## 15. 你现在应该先做什么

当前项目的 agent 代码还只是最小骨架。下一步最合理的是实现“确定性 agent loop”，而不是马上接 LLM。

具体任务：

1. 新增 `src/orfadc/agents/tool_registry.py`。
2. 新增 `src/orfadc/agents/trace.py`。
3. 新增 `src/orfadc/experiments/run_agent_loop.py`。
4. 扩展 `Manager`，支持 add/pop/update queue。
5. 扩展 `Candidate`，加入 priority/history。
6. 写 `tests/test_agent_loop.py`。
7. dry-run 生成 `agent_trace.json`。

验收标准：

```powershell
$env:PYTHONPATH = "$PWD\src"
python src\orfadc\experiments\run_agent_loop.py --spec S1 --seed 0 --dry-run
python -m pytest tests -q
```

