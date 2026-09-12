## 17. 后续要实现的多智能体代码任务提示词

下面这段提示词可以直接复制给 Codex，用来完成“详细描述论文多智能体与本项目差异，并继续实现确定性 agent loop”的任务。

```text
请基于以下文件继续推进 Open-RFAmpDesigner-Cadence 的多智能体部分：

- references/paper/RFAmpDesigner.pdf
- references/paper/RFAmpDesigner_中文翻译.md
- docs/11_multi_agent_explained.md
- src/orfadc/agents/manager.py
- src/orfadc/agents/searcher.py
- src/orfadc/agents/refiner.py
- src/orfadc/agents/memory.py

任务目标：
1. 详细核对论文中 RFAmpManager、RFAmpSearcher、RFAmpRefiner 的工作原理；
2. 说明论文中的 agent 是 Python 工程框架 + prompt + 工具调用 + 可替换 LLM backbone，而不是三个固定模型；
3. 说明论文测试过的 backbone：GPT-5.1、Claude-Sonnet-4.5、Gemini-2.5-Flash、DeepSeek-V3.2、Qwen3-Coder-480B-A35B-Instruct、Qwen3-30B-A3B-Instruct；
4. 说明 LLM 在论文中负责策略推理和工具调用决策，不负责直接写 netlist 或替代 Spectre；
5. 说明本项目当前做到的程度：文档级、代码骨架级、dry-run 级；
6. 说明本项目与论文原始系统的差异：PDK、OCEAN scripts、lookup table、KB/EB、prompt、最终参数、真实 Cadence 仿真数据均不相同；
7. 探讨 docs/11_multi_agent_explained.md 的文档标题是否准确；如果要改，只讨论多智能体说明文档的标题，不讨论工程项目名；
8. 在文档中明确写出本项目可追求方法级/流程级/趋势级复现，不能追求严格论文数值复现。

实现目标：
在文档说明完成后，开始实现确定性 agent loop 的最小版本：

- 新增 src/orfadc/agents/tool_registry.py；
- 新增 src/orfadc/agents/trace.py；
- 新增 src/orfadc/experiments/run_agent_loop.py；
- 扩展 Manager，使其支持 add_candidates、pop_best_candidate、update_candidate、stop；
- Candidate 增加 priority/history 字段，如果 schema 改动太大，先用 notes/status 兼容；
- 写 tests/test_agent_loop.py；
- dry-run 下生成 results/runs/<spec>/<seed>/agent_trace.json。

限制：
- 不接真实 LLM；
- 不调用真实 Cadence；
- 不伪造仿真 pass；
- 不写商业 PDK 路径；
- 不声称严格复现论文；
- 所有 agent 输出必须可 JSON 序列化。

验收命令：

$env:PYTHONPATH = "$PWD\src"
python src\orfadc\experiments\run_agent_loop.py --spec S1 --seed 0 --dry-run
python -m pytest tests -q

最终请总结：
1. 文档补充了哪些内容；
2. 代码新增了哪些文件；
3. dry-run agent loop 产生了哪些输出；
4. 下一步如何从确定性 agent 升级到 mock LLM，再升级到真实 LLM。
```

