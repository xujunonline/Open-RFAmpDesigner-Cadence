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
| `127_paper_budget_alignment.md` | 论文预算口径；PDK pass@1 29/40（论文 32/40；原记 34/40 为加法错误，已更正）；Codex 不封顶 5 seed；Spectre ≈697/1000 |
| `128_ic618_vm_pdk_survey.md` | 新虚拟机 IC618_rf 的工艺盘点（磁盘扫描：TSMC 65 nm LP RF，待开机确认） |
| `129_v1_cleanup_prompt.md` | v1.1 清理提示词与执行记录 |
| `130_v2_kickoff.md` | v2 启动任务说明：A 线 ReAct 智能体 + B 线 N65（IC618_rf）接入与 v1 基线，在 Claude Code 中执行 |
| `131_agent_v2_design.md` | 智能体实现 v2：LLM ReAct Manager/Searcher/Refiner 设计、论文对应、终止与预算、离线验证（A2） |
| `132_n65_bringup.md` | N65（IC618_rf）接入记录：`run_job_queue.sh`、可配置的 PDK 盘点、N0 密钥登录（用户 IC）；N1 盘点与表征（CRN65LP v1.7）；N2 冒烟（上限 14，4/8）；N3 v1 基线 24/40（crn40lp 29/40，差距全在 S3）；Spectre 837/1500 |
| `133_agent_v2_results.md` | v2 真实 LLM 结果（A3）：S2 冒烟 codex-mcp 与 claude-cli 都通过（55 / 39 次调用，0 非法动作）；S9s/S10s v2+codex 6/10（v1 0/10）；N65 v2+codex 21/40（v1 24/40，差在 S5）；B/C/D/E 实验；N65 上 S9/S10：v2 与 v1 都是 S9 4/5、S10 0/5，v2 的 Spectre 用量约为 1/3；Fig. 9/11-like；实验 a：v2 自进化 18/18（§13）；实验 b：Spectre 锚点，v1 通过与否不变，v2 S5 两个仍失败，seed 1 原来的通过不稳定（§12、§12b）；Spectre 3144/3300 |
| `134_macbook_handoff.md` | 迁移到 MacBook 的交接状态、Mac 准备步骤、续接提示词（docs/132、133 预留给 N65 接入与 v2 结果） |
| `135_v2_reproduction_report.md` | 复现总报告 v2 更新版：论文结论逐条对照（v1、v2、N65）、主要数字、未复现原因、资源与工程记录 |
| `136_student_guide_prompt.md` | 提示词：为微电子专业本科生生成《项目设计方案与仿真过程学习指南》（输出到 docs/137） |
| `137_student_guide.md` | 学习指南（面向微电子本科生）：射频预备知识、规格、电路方案与 Eq.(3) 勘误、两端口仿真引擎与 IP1dB、四个工具、v1/v2 智能体与记忆、Spectre/PDK 链路、动手实践、结果解读、术语表与思考题；算例来自 S2 实际运行（代理结果） |
| `138_experiment_report_prompt.md` | 提示词：生成提交导师的《v2 阶段实验报告》（重算数字、统计检验、过程记录、有效性分析；输出到 docs/139） |
| `139_experiment_report.md` | v2 阶段实验报告（提交导师）：摘要、引言、方法、环境、实验设计、过程记录与异常汇总、结果（Wilson 区间、Fisher 检验）、分析、有效性威胁、结论与后续工作、附录；数字与图由 `scripts/report/` 从原始文件重算；更正 crn40lp 合计为 29/40 |
| `LEGACY.md`、`LEGACY_files.txt` | v1.1 删除内容与找回方法 |

## 十一月接管与标称复现

| 文档 | 内容 |
|---|---|
| [140_takeover_review_2026-11-19.md](140_takeover_review_2026-11-19.md) | 接手准备：源快照与论文核对、论文到代码映射、Linux 离线回归与 v1/v2 S2 冒烟、存量结果重算、Mac 运行方案、PDK 数据选择和资源记账风险、下一步接管顺序 |
| [141_mac_locations_and_git_recovery_2026-11-19.md](141_mac_locations_and_git_recovery_2026-11-19.md) | 原 Mac 项目/VM/文档位置、Git 历史与标签补全、可恢复与本地独有资产、Mac 定位及缺失文件恢复脚本 |
| [142_s5_matching_diagnosis_2026-11-19.md](142_s5_matching_diagnosis_2026-11-19.md) | S5 十次 N65 历史运行的离线诊断、带边 S11 和回退证据；独立 Refiner S11 提示开关、回归验证、尚未执行的单 seed 试验入口 |
| [143_environment_run_2026-11-23.md](143_environment_run_2026-11-23.md) | 云端 106 次离线设计与同日原 Mac 首次验收，S2 宏模型及 S5 首轮 N65 实测 |
| [144_s5_workflow_improvement_2026-11-23.md](144_s5_workflow_improvement_2026-11-23.md) | S5 反馈、预算退出、最佳方案与日志改进；历史 N65 回放、离线完整流程及初学者工作日志；新增真实调用为零 |
| [145_s5_verified_run_2026-11-23.md](145_s5_verified_run_2026-11-23.md) | S5新工作流真实限时运行；自主搜索未过；历史方案MCR3耦合+3%后N65两次通过，资源账本与学习日志 |
| [146_s5_resume_refiner.md](146_s5_resume_refiner.md) | S5 seed0 历史方案续调，局部 Refiner 自主选择 MCR2 −3% 并经 N65 两次确认 |
| [147_s1_s8_ordered_optimization.md](147_s1_s8_ordered_optimization.md) | N65 S1–S8 seed0 逐项优化，原始基线与候选 |
| [148_s1_s8_spectre_results.md](148_s1_s8_spectre_results.md) | N65 逐规格实测与难例优化，S6 标称通过及重复确认 |
| [149_s3_noise_20261124.md](149_s3_noise_20261124.md) | S3 噪声优化及独立复测，中心 NF 5.683 dB |
| [150_s3_noise_contributions.md](150_s3_noise_contributions.md) | S3 噪声来源与实测匹配优化，两种候选独立复测 |
| [151_s7_noise_20261124.md](151_s7_noise_20261124.md) | S7 扩展偏置标称六项通过，原网格与全带噪声分别复核 |
| [152_s3_fullband_20261124.md](152_s3_fullband_20261124.md) | S3 原偏置六项通过，扩展偏置另达 45–55 GHz 全带增益和噪声要求 |
| [153 十月报告证据复核](153_october_report_evidence_review.md) | 锚点、器件限制、仿真成本及通过率的统计口径 |
| [154 N65 宽带低噪声放大器自动设计复现实验总报告](154_november_experiment_report.md) · [Word 版](154_november_experiment_report.docx) | 电路拓扑、多种子基线、S3 首级几何、S5 从零决策、S10 增益整形与全带验收 |
| [155 S10 定向优化与验证](155_s10_n65_optimization.md) | 接续 154 的待解规格；N65 原偏置网格六项与全带 NF 均通过，增益整形、HB 和独立复测 |
| [156 限时从零设计与首级几何对照](156_cold_start_pilot.md) | S3/S5 配对运行、S5 自主通过回放、S3 提前退出候选补测与首级两管的四点对照 |
| [157 S4 前仿与首级器件版图](157_s4_layout_start.md) | 加密前仿、隔离 RF 版图库、六个 PCell、GDS 导出及 Calibre 许可诊断 |
| [158 S4 首级布线与匹配](158_s4_layout_closeout.md) | 首级几何连通核查与输入电感替换估算 |
| [159 单智能体与三智能体对照](159_agent_comparison.md) | S9 与 S10 的配对代理试验 |
| [160 N65 宽带低噪声放大器自动设计方法复现](160_rfa_final_report_draft.md) · [Word 版](160_rfa_final_report_draft.docx) | 论文格式总报告，含逐规格验收、从零设计和版图验证范围 |
