# RFAmpDesigner 多智能体系统详解与实现方案

> 本文回答四个问题：  
> 1. 多智能体到底是什么；  
> 2. 为什么 RFAmpDesigner 要拆成 Manager/Searcher/Refiner；  
> 3. 每个智能体如何生成、如何调用工具、如何协作；  
> 4. 论文原始系统接入了哪些模型、如何实验；  
> 5. 在本工程 Open-RFAmpDesigner-Cadence 中应该怎样一步步实现，以及与论文做到的程度有什么区别。

本文档当前文件名 `11_multi_agent_explained.md` 和标题“RFAmpDesigner 多智能体系统详解与实现方案”是合适的：它强调本文是解释多智能体机制与本项目实现方案，而不是论文官方代码说明。暂时不建议改名；如果后续拆分文档，可把“原论文多智能体机制”和“本项目 agent 实现方案”拆成两个文件。

## 1. 先用一句话理解多智能体

在本项目里，“多智能体”不是多个机器人，也不是多个独立程序随便聊天。它更像一个 RF 设计小组：

- `Manager` 是项目负责人，负责看规格、排队候选、决定下一步做搜索还是细化。
- `Searcher` 是初始方案工程师，负责提出电流分配、关键级尺寸和初始匹配方案。
- `Refiner` 是调试工程师，负责看仿真失败指标，然后决定改哪里。
- `Tool Registry` 是工具台，里面有 active sizing、impedance matching、band planning、fullchain evaluation。
- `Cadence/Spectre/OCEAN` 是实验设备，给出真实仿真结果。
- `Memory` 是实验记录本，保存过去成功和失败经验。

你可以把它类比成你做 OTA 自动扫参：

| OTA 自动扫参中的角色 | 多智能体中的对应 |
|---|---|
| 你手动决定扫哪些 W/L | Searcher |
| 你看结果决定下一轮怎么调 | Refiner |
| 你决定先扫哪个候选、什么时候停止 | Manager |
| Python 脚本 | Tool Registry + Experiment Runner |
| Spectre/ADE/OCEAN | Cadence backend |
| CSV/JSON 结果记录 | KB/EB Memory |

区别是：RFAmpDesigner 把这些人为判断拆成结构化模块，并允许 LLM 在这些模块里做有限决策。

## 2. 为什么不让一个 LLM 直接完成全部任务

一个大模型直接做全部 RF 设计会有几个问题：

1. **任务太长**：从规格理解、候选生成、仿真、失败诊断、再次修改，到最后报告，步骤太多，容易丢上下文。
2. **RF 反馈稀疏**：很多候选都会失败，一个单智能体容易盲目继续试。
3. **工具成本不同**：有些动作便宜，例如计算 MCR 低保真响应；有些动作昂贵，例如 Cadence fullchain 仿真。需要有人调度。
4. **错误隔离差**：如果一个 agent 同时负责所有事，它一旦判断错，整个流程都会偏。
5. **token 成本高**：论文消融显示，单智能体可以成功，但 prompt token 明显更多。

所以论文把任务拆成两层三类 agent：

```text
上层：RFAmpManager
  - 维护全局状态；
  - 决定 SearchCandidates / RefineCandidate / Stop；
  - 读写 KB/EB；
  - 对候选排序。

下层：RFAmpSearcher、RFAmpRefiner
  - Searcher 负责生成新候选；
  - Refiner 负责局部修正旧候选；
  - 二者每次调用可以是无状态的，便于并行和隔离失败。
```

## 3. 多智能体不是一开始就用 LLM

本项目推荐分三层实现：

### 3.1 第 1 层：确定性规则智能体

先用普通 Python 类实现：

- `Manager.next_action()`
- `Searcher.search()`
- `Refiner.refine()`

这一步不需要 LLM。好处是你能先把“状态机”和“数据流”跑通。

当前项目已经有最小骨架：

- `src/orfadc/agents/manager.py`
- `src/orfadc/agents/searcher.py`
- `src/orfadc/agents/refiner.py`
- `src/orfadc/agents/memory.py`

### 3.2 第 2 层：Mock LLM 智能体

用一个假 LLM 函数返回固定 JSON，例如：

```json
{
  "action": "SearchCandidates",
  "arguments": {
    "power_ratio_list": [0.4, 0.3, 0.3],
    "nf_headroom_db": 0.2
  }
}
```

这一步验证 prompt schema、JSON parser、fallback 和 agent trace。

### 3.3 第 3 层：真实 LLM 智能体

最后再接真实 LLM。真实 LLM 只能输出 JSON 决策，不能：

- 直接写 PDK netlist；
- 直接修改商业模型；
- 自己编造仿真结果；
- 接触私有 PDK 路径；
- 把 dry-run 结果说成 Cadence pass。

## 3A. 论文原始多智能体到底是“代码”还是“模型”

论文里的多智能体可以理解为：

```text
Python 工程框架
+ 工具中间件
+ Cadence/OCEAN/Spectre 后端
+ 可替换 LLM backbone
+ KB/EB 记忆库
```

也就是说，`RFAmpManager`、`RFAmpSearcher`、`RFAmpRefiner` 不是模型厂家提供的三个独立模型名，而是作者实现的三个智能体角色。每个角色背后都需要：

1. **Python 控制代码**：负责状态、队列、工具调用、日志、预算、停止条件。
2. **Prompt 模板**：告诉 LLM 当前角色、可用工具、输入输出 schema。
3. **工具调用接口**：把 LLM 的动作翻译成 Python 函数调用。
4. **仿真后端**：通过 Python-shell 接口调用 Cadence OCEAN scripts。
5. **LLM backbone**：负责在 agent 的受限角色内做推理和决策。

所以更准确的说法是：

```text
Agent = Python 编排逻辑 + 角色 prompt + 工具 schema + 可选 LLM backend
```

如果不接 LLM，agent 仍然可以作为“确定性规则 agent”运行；如果接 LLM，LLM 只是 agent 的策略决策器，不是整个 agent 系统本身。

## 3B. 论文原始系统接入了哪些模型

论文不是只接一个固定模型，而是用同一套 RFAmpDesigner 框架测试多个 LLM backbone。论文中列出的模型包括：

| 类别 | 模型 | 论文用途 |
|---|---|---|
| 前沿闭源模型 | GPT-5.1 | 对比成功率、耗时、token、成本 |
| 前沿闭源模型 | Claude-Sonnet-4.5 | 作为主要强 backbone，并用于多项消融 |
| 前沿闭源模型 | Gemini-2.5-Flash | 对比低成本/快速模型表现 |
| 前沿/强推理模型 | DeepSeek-V3.2 | 对比成功率和 token 开销 |
| 开源/开放权重模型 | Qwen3-Coder-480B-A35B-Instruct | 测试工具使用微调的大模型 |
| 开源/开放权重模型 | Qwen3-30B-A3B-Instruct | 测试较小模型在 RF 工具推理中的稳定性 |

论文观察到：

- 在 Spec 9 上，多个强模型都能达到较高成功率。
- 在更难的 Spec 10 上，Claude-Sonnet-4.5 和 DeepSeek-V3.2 保持更稳定。
- DeepSeek-V3.2 的 prompt token 消耗明显更大。
- Claude-Sonnet-4.5 在成功率、时间和 token 成本之间比较均衡。
- Qwen3-Coder-480B-A35B-Instruct 表现接近强闭源模型。
- Qwen3-30B-A3B-Instruct 更容易出现格式失败和复杂 RF 概念误解。

这说明原论文的结论不是“必须使用某一家模型”，而是：

```text
RFAmpDesigner 是模型无关的 agent 框架。
强模型、工具使用能力好、格式稳定的模型更适合。
小模型可以尝试，但需要更严格 schema、fallback 和微调。
```

更具体地说，原论文不是“某一个固定模型 + agent”，而是：

```text
同一套 RFAmpDesigner 多智能体框架
+ 不同 LLM backbone 替换测试
```

论文表 V 和表 VI 对比了这些模型在 S9/S10 难任务上的成功率、平均时间、token 和有效成本。论文结论中，`Claude-Sonnet-4.5` 在成功率、运行时间和 token 成本之间表现较均衡；`DeepSeek-V3.2` 也能达到较高成功率，但 prompt token 消耗更大。小型或工具使用能力较弱的模型更容易出现 JSON/格式失败，或者误解 RF 电路概念。

因此本项目复现时不应绑定某一家模型。合理策略是：

1. 先用 Python 规则 agent 跑通；
2. 再用 mock LLM 测试 JSON schema；
3. 最后接一个可替换的模型后端；
4. 后续如果条件允许，再对比多个模型的 pass@1、平均耗时、token 和成本。

## 3C. 论文原始系统中 LLM 具体做什么

论文中的 LLM 不负责：

- 直接生成最终 Cadence netlist；
- 直接读写 PDK；
- 直接判断仿真是否真实成功；
- 直接替代 Spectre；
- 直接输出论文图表结果。

论文中的 LLM 负责：

1. 理解用户规格属于哪类难度，例如 `NF hard`、`linearity hard`、`bandwidth hard`。
2. 给出资源分配建议，例如 `power_ratio_list=[0.4,0.3,0.3]`。
3. 选择工具调用，例如 search 或 refine。
4. 阅读工具返回的 observation，例如 NF、IP1dB、ripple 是否失败。
5. 总结失败原因，例如“第一级 gain 太高导致压缩点恶化”。
6. 根据 KB/EB 的历史经验调整下一步策略。

这与普通“让 ChatGPT 写一个电路”完全不同。论文的 LLM 被限制在“工程决策层”，真正数值计算和验证由工具与 Cadence 完成。

