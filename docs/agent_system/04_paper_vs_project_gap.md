## 16. 本项目方案与论文原始方案的差异

本项目不是论文作者代码的复刻，因为论文没有公开完整代码、Cadence scripts、PDK lookup table、prompt、KB/EB 和最终参数。本项目的目标是“方法级复现”和“工程可执行近似实现”。

### 16.1 总体差异表

| 维度 | 论文原始 RFAmpDesigner | 本项目 Open-RFAmpDesigner-Cadence |
|---|---|---|
| 工艺 | TSMC N65 | 用户实验室授权 PDK，例如 TSMC40/TSMC65/SMIC/GF/IHP，或教学模型 |
| 电路 | 三阶段宽带 LNA，含 cascode、差分共源、中和电容、MCR | 从单级/两级 LNA MVP 开始，后续扩展三阶段和 MCR-like |
| 仿真 | Cadence Spectre + OCEAN，作者自有 scripts | 提供 OCEAN 模板和 Python runner，需要用户按本地 Cadence 环境补齐 |
| lookup table | 作者基于 N65 PDK 和 PEX 生成 | 本项目需要用本地 PDK 重新生成，不可复制作者表 |
| agent | Manager/Searcher/Refiner + ReAct + KB/EB | 先 Python 确定性 agent，再 mock LLM，再接真实 LLM |
| LLM backbone | GPT-5.1、Claude-Sonnet-4.5、Gemini-2.5-Flash、DeepSeek-V3.2、Qwen3 系列等 | 可接任意支持 JSON 输出的模型；推荐先不用模型跑通工具流 |
| 结果 | Table IV/V/VI，Fig. 7-11 | 生成 table-like / fig-like，自有实验结果，不声明严格复现 |
| 复现等级 | 作者原始实验 | 方法级、流程级、趋势级近似复现 |

### 16.2 当前本项目已经做到什么

当前项目已经做到：

- 建立 `Manager/Searcher/Refiner/Memory` Python 骨架；
- 定义 Table I 工具中间件文件结构；
- 实现 Stage 2/Stage 3 cost function；
- 建立 specs Table III YAML；
- 建立 OCEAN template 文件；
- 写出多智能体说明和 step-by-step 操作指导；
- 提供 dry-run 候选生成。

截至 2026-09-25，当前项目还没有做到：

- 真实 Cadence LNA schematic；
- 有源 RF/LNA 的 S 参数、noise 和 compression 仿真；被动理想二端口的 Spectre `sp` 分析已实机完成，见 `docs/14_ideal_twoport_rf_smoke.md`；
- 真实 active lookup table；
- 真实 Stage 2 PSO；
- 真实 Stage 3 MCR 多保真校准；
- 完整 agent loop；
- LLM backend；
- KB/EB 检索和自进化实验；
- Table IV/V/VI-like 的真实数据。

### 16.3 与论文做到的程度差别

可以把差别分成四级：

| 等级 | 含义 | 本项目当前状态 |
|---|---|---|
| L0 文档级 | 理解论文结构和实现方案 | 已完成较多 |
| L1 代码骨架级 | 有 Python 模块、配置、cost function、dry-run | 已初步完成 |
| L2 Cadence MVP 级 | 单级/简化 LNA 可真实仿真并自动提取指标 | 待完成 |
| L3 方法级复现 | Stage 1/2/3/fullchain + deterministic/LLM agent 可跑 | 待完成 |
| L4 论文级近似复现 | 10 specs、5 seeds、table-like/fig-like | 后期目标 |
| L5 严格论文复现 | 作者 N65 PDK、netlist、scripts、lookup、prompts、KB/EB 全部一致 | 不可实现 |

本项目最多应追求 L4。L5 不应该作为目标，因为缺少作者私有实验材料。

