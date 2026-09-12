# 文档索引

- `open_rfampdesigner_cadence_design.md`：完整实现方案主文档。
- `open_rfampdesigner_cadence_full_plan.md`：按用户提示词扩展后的 24 节完整论文实现设计方案。
- `01_paper_theory.md`：论文目标、拓扑、工具中间件、公式和实验结果拆解。
- `02_rf_lna_basics.md`：从 OTA 到 LNA 的 RF 基础学习笔记。
- `03_cadence_environment.md`：Cadence/Virtuoso/Spectre/OCEAN 环境约定。
- `04_tool_middleware.md`：论文 Table I 工具中间件到 Python 模块的映射。
- `05_multi_agent_design.md`：Manager/Searcher/Refiner 的状态、动作和记录格式。
- `06_experiments.md`：三阶段复现实验、表格和图输出计划。
- `07_reproduction_limits.md`：不可严格复现边界和对外表述规范。
- `08_student_tutorial.md`：面向大二微电子学生的实施路线。
- `09_step_by_step_operation_guide.md`：从零推进到 Cadence LNA MVP、工具中间件、多智能体和论文级近似复现的逐步操作指导书。
- `10_detailed_prompts.md`：每个阶段可直接复制给 Codex/LLM 的详细提示词。
- `11_multi_agent_explained.md`：多智能体专题总入口，详细内容已拆分到 `agent_system/` 子目录。
- `agent_system/`：原论文多智能体机制、本项目 agent 实现、LLM 接入、论文差异和后续提示词的专题文档。
- `project_history/`：从原 Codex 对话任务迁移的聊天记录、继续任务指南、旧 README 和迁移清单。

论文原文、中文翻译、插图和 arXiv 源文件位于仓库根目录的 `references/paper/`。

后续拆分长文档时，保持本索引为唯一入口。
