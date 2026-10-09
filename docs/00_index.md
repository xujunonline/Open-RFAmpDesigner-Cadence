# 文档索引（v1.1）

入口：`../README.md` → `../CLAUDE.md` → 117（运行手册）→ 125（总报告）。
路线 B 历史文档（docs/01–114 等）已删除，见 `LEGACY.md`，可从标签 `v1-decision-points` 找回。

| 文档 | 内容 |
|---|---|
| `115_repro_surrogate_pipeline.md` | 代理复现：论文→代码映射、代理模型、Table IV/V、Fig. 5/7/8/10-like 结果（基线 `results/repro/2026-10-03`） |
| `116_project_audit_2026-09-29.md` | 论文↔代码审查、B01–B21 问题台账、Eq.(3) 勘误推导（审查对象为清理前的仓库） |
| `117_step_by_step_runbook.md` | 阶段 0–7 运行手册（命令、判据、PDK 开关） |
| `118_claude_prompts.md` | Claude Code 总控/阶段/续接/审查提示词 |
| `119_subscription_llm_and_cadence_backend.md` | 订阅 LLM 主干（claude-cli / codex-mcp）与 Spectre 宏模型后端；LLM seed 0、5 seed 封顶、不封顶结果 |
| `120_cadence_v2_plan.md` | PDK 后端分阶段计划（已执行） |
| `121_cadence_v2_pdk_results.md` | TSMC 40LP RF 盘点与器件表征；S1/S2/S4 Spectre(PDK) 通过 |
| `122_pdk_model_fit_and_s1_s8.md` | B16 修正（Y/噪声拟合、大信号 1 dB）；S1–S8 seed 0：5/8 |
| `123_stage1_three_port_y.md` | 第一级三端口 Y、差分级 Y2、噪声 k = 1.2；S5 转为通过（累计 6/8）；B20；S7 NF 下限 |
| `124_ours_gaps_and_cascode_noise.md` | 代理路径 Ours 短板（B20/B21）、共源共栅噪声表征 |
| `125_final_reproduction_report.md` | 最终复现总报告（结论对照、勘误、边界） |
| `126_passive_q_and_s6_budget.md` | S7 匹配电感 Q 敏感度（Q = 100 时 3/3）、S6 3× 预算仍未过 |
| `127_paper_budget_alignment.md` | 论文预算口径；PDK pass@1 34/40（论文 32/40）；Codex 不封顶 5 seed；Spectre ≈697/1000 |
| `128_ic618_vm_pdk_survey.md` | 新虚拟机 IC618_rf 的工艺盘点（磁盘扫描：TSMC 65 nm LP RF，待开机确认） |
| `129_v1_cleanup_prompt.md` | v1.1 清理提示词与执行记录 |
| `130_v2_kickoff.md` | v2 启动任务说明：A 线 ReAct 智能体 + B 线 N65（IC618_rf）接入与 v1 基线，在 Claude Code 中执行 |
| `131_agent_v2_design.md` | 智能体实现 v2：LLM ReAct Manager/Searcher/Refiner 设计、论文对应、终止与预算、离线验证（A2） |
| `132_n65_bringup.md` | N65（IC618_rf）接入记录：`run_job_queue.sh`、可配置的 PDK 盘点、N0 密钥登录（用户 IC）；N1 盘点与表征（CRN65LP v1.7）；N2 冒烟（上限 14，4/8）；N3 v1 基线 24/40（crn40lp 34/40，差距全在 S3）；Spectre 837/1500 |
| `133_agent_v2_results.md` | v2 真实 LLM 结果（A3）：S2 冒烟 codex-mcp 与 claude-cli 都通过（55 / 39 次调用，0 非法动作）；S9s/S10s v2+codex 6/10（v1 0/10）；N65 v2+codex 21/40（v1 24/40，差在 S5）；B/C/D/E 实验；N65 上 S9/S10：v2 与 v1 都是 S9 4/5、S10 0/5，v2 的 Spectre 用量约为 1/3；Fig. 9/11-like；实验 a：v2 自进化 18/18（§13）；实验 b：Spectre 锚点不改变通过与否（§12）；Spectre 2619/3000 |
| `134_macbook_handoff.md` | 迁移到 MacBook 的交接状态、Mac 准备步骤、续接提示词（docs/132、133 预留给 N65 接入与 v2 结果） |
| `135_v2_reproduction_report.md` | 复现总报告 v2 更新版：论文结论逐条对照（v1、v2、N65）、主要数字、未复现原因、资源与工程记录 |
| `LEGACY.md`、`LEGACY_files.txt` | v1.1 删除内容与找回方法 |
