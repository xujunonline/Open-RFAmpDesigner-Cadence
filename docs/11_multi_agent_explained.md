# RFAmpDesigner 多智能体系统详解与实现方案

本文是多智能体部分的总入口。原来的单文件说明已经拆分到 `docs/agent_system/`，便于按主题阅读和继续维护。

## 为什么拆分

原 `11_multi_agent_explained.md` 已超过 1500 行，混合了论文机制、工作流、三个 agent 实现、项目差异、实现计划和后续提示词。继续在一个文件里扩展会导致查找困难、重复解释和后续修改风险。因此改为“总入口 + 专题子文档”的结构。

## 推荐阅读顺序

1. [00_overview_and_paper_agents.md](agent_system/00_overview_and_paper_agents.md)  
   先理解多智能体是什么、为什么论文拆成 Manager/Searcher/Refiner，以及论文接入了哪些模型 backbone。

2. [01_workflow_queue_memory_react.md](agent_system/01_workflow_queue_memory_react.md)  
   看一次完整 LNA 设计任务如何在 Manager、Searcher、工具、Cadence、Refiner、Memory 之间流动。

3. [02_agent_roles_and_implementation.md](agent_system/02_agent_roles_and_implementation.md)  
   重点阅读三个 agent 的任务边界、输入输出 JSON、Python 实现草图和测试验收。

4. [03_project_implementation_plan.md](agent_system/03_project_implementation_plan.md)  
   看本工程如何从确定性 Python agent loop，升级到 mock LLM，再升级到真实 LLM backend。

5. [04_paper_vs_project_gap.md](agent_system/04_paper_vs_project_gap.md)  
   明确论文原始系统与本项目复现方案的差异，避免把方法级复现说成严格数值复现。

6. [05_next_task_prompt.md](agent_system/05_next_task_prompt.md)  
   后续让 Codex 实现确定性 agent loop 时，直接复制这里的提示词。

7. [06_design_discipline.md](agent_system/06_design_discipline.md)  
   实现过程中必须遵守的边界：agent 不伪造结果、tool 不自由推理、Cadence 层不理解 LLM、dry-run 不当作 pass。

## 命名说明

当前文件名 `11_multi_agent_explained.md` 仍然合适，因为它现在作为“多智能体解释总入口”。详细内容已经按主题拆到 `agent_system/`。暂不建议改名。

## 和原文档的关系

本次拆分没有删除有用内容。原文档主体内容按章节迁移到 `agent_system/00-06_*.md`；本文件只保留导航、阅读顺序和维护说明。
