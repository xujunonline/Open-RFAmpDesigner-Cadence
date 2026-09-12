# 多智能体文档目录

`11_multi_agent_explained.md` 是总入口。本目录保存从原 11 文档拆分出的详细内容，按阅读顺序排列。

| 文件 | 内容 |
|---|---|
| `00_overview_and_paper_agents.md` | 多智能体直观解释、为什么拆 agent、论文原始 agent 与模型 backbone。 |
| `01_workflow_queue_memory_react.md` | 一次完整设计任务如何流动、candidate queue、KB/EB、ReAct。 |
| `02_agent_roles_and_implementation.md` | Manager/Searcher/Refiner 的定义、任务边界、输入输出、Python 实现和测试。 |
| `03_project_implementation_plan.md` | 本工程推荐代码架构、最小 agent loop、真实 LLM 接入、Cadence 关系、评价指标、里程碑。 |
| `04_paper_vs_project_gap.md` | 论文原始方案与本项目方案的差异、当前做到的程度、复现等级。 |
| `05_next_task_prompt.md` | 后续实现多智能体代码的详细提示词。 |
| `06_design_discipline.md` | 多智能体实现纪律。 |

拆分原则：保留原文有效内容，只改变组织结构。
