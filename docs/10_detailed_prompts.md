# Open-RFAmpDesigner-Cadence 详细提示词库

> 用法：每次只复制一个阶段提示词给 Codex/LLM。不要一次要求它完成全部项目。  
> 原则：每个提示词都包含背景、目标、允许修改范围、输出格式、验收标准和禁止事项。

## Prompt 0：项目上下文恢复

```text
请读取并理解以下文件：

- README.md
- docs/project_history/继续任务指南.md
- docs/00_index.md
- docs/open_rfampdesigner_cadence_full_plan.md
- docs/09_step_by_step_operation_guide.md
- references/paper/README.md

我的目标是一步步实现 Open-RFAmpDesigner-Cadence，而不是一次性做完全部论文复现。

请先输出：
1. 当前项目已有文件和能力总结；
2. 当前最合理的下一步；
3. 本次任务建议修改哪些文件；
4. 本次任务不应该做什么。

注意：
- 不要虚构 PDK；
- 不要声称严格复现论文 TSMC N65；
- 不要跳过 Cadence/OCEAN/Python 自动仿真闭环；
- 所有建议必须能落到具体文件和命令。
```

## Prompt 1：本地 Python 骨架检查

```text
当前阶段：阶段 1，本地 Python 骨架检查。

请在 Open-RFAmpDesigner-Cadence 项目根目录中检查 Python 工程：

目标：
1. 确认 src/orfadc 能编译；
2. 确认 pytest 能通过；
3. 确认 run_spec.py --spec S1 --dry-run 能生成候选；
4. 如果失败，请修复最小必要代码；
5. 不要引入大型依赖；
6. 不要接 Cadence；
7. 不要接 LLM。

请执行：
- python -m compileall src
- 设置 PYTHONPATH 后运行 pytest
- python src\orfadc\experiments\run_spec.py --spec S1 --dry-run

验收标准：
- compileall 无错误；
- pytest 通过；
- dry_run_candidates.json 能生成；
- 清理 __pycache__ 和 .pytest_cache；
- 最终总结修改了哪些文件。
```

## Prompt 2：迁移 OTA 自动化工程能力

```text
当前阶段：阶段 2，迁移我已有的 OTA Cadence 自动化能力。

我的前置项目已经实现：
- Virtuoso 搭建折叠共源共栅全差分 OTA；
- TSMC40 CRN40LP PDK；
- OCEAN/SKILL 创建和验证 schematic；
- Python 通过 SSH 调用 Linux VM 中的 OCEAN/Spectre；
- 自动修改 MOS W/L；
- 批量扫描参数；
- 解析 PSFASCII；
- 提取 gain、0 dB 频率、PM、输出共模、电源电流。

请帮我在当前项目中设计“OTA 自动化能力迁移到 LNA”的执行方案。

允许修改：
- docs/ota_to_lna_migration_notes.md
- config/remote_cadence.local.example.yaml
- 如有必要，可新增 src/orfadc/cadence/remote_runner.py 和 psfascii_reader.py 的接口骨架。

输出要求：
1. 列出 OTA 旧代码中应迁移的模块；
2. 列出哪些模块不能直接迁移；
3. 设计 remote_runner.py 的函数接口；
4. 设计 psfascii_reader.py 的输入输出；
5. 给出本阶段手动验证命令；
6. 明确哪些真实账号/IP/PDK 路径不能提交。

禁止事项：
- 不要写真实密码、IP、PDK 路径；
- 不要复制商业 PDK 文件；
- 不要开始设计三阶段 LNA；
- 不要接 LLM agent。
```

## Prompt 3：Cadence RF 环境检查

```text
当前阶段：阶段 3，Cadence RF 环境准备。

请生成一份 Cadence RF 环境检查清单和最小验证脚本设计。

背景：
我会在 Linux VM 或服务器上运行 Cadence Virtuoso/Spectre/OCEAN。此前 OTA 项目已经能跑 Spectre，但本项目需要 RF 相关 sp/noise/HB 或功率 sweep。

请修改或新增：
- docs/03_cadence_environment.md
- circuit/ocean/verify_design.ocn
- 必要时新增 docs/cadence_rf_environment_checklist.md

请给出：
1. Linux 端要检查的命令；
2. cds.lib/library/cell/view 命名建议；
3. 如何判断 PDK 和 RF primitive 是否可用；
4. 如何先用 ADE 手工跑通；
5. 如何再用 OCEAN -nograph 跑通；
6. 如何导出 CSV/PSFASCII；
7. 失败排查表。

禁止事项：
- 不要假设有 TSMC N65；
- 不要写商业模型路径；
- 不要生成声称可直接运行的完整 PDK netlist。
```

## Prompt 4：最小 S 参数 testbench

```text
当前阶段：阶段 4，建立最小 RF S 参数 testbench。

目标：
设计一个最小 RF 放大级 testbench，使我能从 Cadence/Spectre 提取 S11/S21/S22，并用 Python 解析。

请修改：
- docs/08_student_tutorial.md
- circuit/ocean/run_sparam.ocn
- src/orfadc/cadence/extract_rf_metrics.py
- 如有必要，新增 tests/test_extract_rf_metrics.py

请输出：
1. Virtuoso schematic 手工搭建步骤；
2. port 设置方法；
3. sp analysis 设置；
4. OCEAN 模板伪代码；
5. 推荐 CSV 字段：freq_ghz,s11_db,s21_db,s22_db；
6. Python 如何计算 band 内最差 S11、最小 S21、最差 S22、ripple；
7. 单元测试。

验收标准：
- Python 测试通过；
- 不需要真实 Cadence 也能用示例 CSV 测试指标提取；
- 文档说明清楚哪些需要在 Cadence 里手动完成。
```

## Prompt 5：noise/NF 仿真接入

```text
当前阶段：阶段 5，加入 noise 仿真和 NF 提取。

目标：
在已有 S 参数 testbench 的基础上，设计 noise 仿真流程，并让 Python 能解析 nf_db 和 nfmin_db。

请修改：
- circuit/ocean/run_noise.ocn
- src/orfadc/cadence/extract_rf_metrics.py
- src/orfadc/tools/cost_functions.py
- tests 中新增或扩展 RF metrics 测试
- docs/02_rf_lna_basics.md

请输出：
1. Cadence noise/sp-noise 的 testbench 设置说明；
2. CSV 字段设计：freq_ghz,nf_db,nfmin_db；
3. Python 提取 nf_center、nf_worst、nfmin_center；
4. 如何把 NF 接入 stage2_cost；
5. 常见错误排查：端口、噪声源、温度、单位。

禁止：
- 不要伪造 NF 仿真结果；
- 没有 Cadence 时只能用 example CSV 做解析测试。
```

## Prompt 6：单级 LNA MVP 自动扫参

```text
当前阶段：阶段 6，单级 LNA MVP 自动扫参。

目标：
设计一个简化单级 LNA 自动扫参闭环，先不追论文三阶段 LNA，只要完成可运行的 RF 自动优化 MVP。

请新增或修改：
- config/mvp_rf_specs.yaml
- config/mvp_sweep_space.yaml
- src/orfadc/experiments/run_mvp_lna.py
- src/orfadc/tools/cost_functions.py
- docs/09_step_by_step_operation_guide.md

功能要求：
1. 读取 MVP spec；
2. 生成 W/VGS/Ls/Lg/Cmatch 候选；
3. 支持 dry-run；
4. 支持真实 Cadence run_config 但默认 dry-run；
5. 解析 sparams.csv/noise.csv；
6. 输出 metrics.json；
7. 按 cost 排序；
8. 保存 results/runs/MVP_RF1/seed0/<candidate>/。

验收标准：
- dry-run 可以生成候选和目录结构；
- 用示例 CSV 可以计算 cost；
- 不接 LLM；
- 不写商业 PDK netlist。
```

## Prompt 7：active lookup table 生成

```text
当前阶段：阶段 7，生成 active lookup table。

目标：
复现论文 Stage 1 思想：用 Cadence 批量表征不同 W/VGS 下的 Id、gm、阻抗和估计噪声，形成本 PDK 的 lookup table。

请设计并实现：
- config/active_lookup_sweep.yaml
- src/orfadc/experiments/build_active_lookup.py
- src/orfadc/tools/active_sizing.py 的 lookup 读取和最近匹配逻辑
- docs/04_tool_middleware.md 的 Stage 1 详细说明

lookup 输出字段：
topology,width_um,vgs_mv,current_ma,gm_ms,gds_ms,cgs_ff,cgd_ff,zin_real_ohm,zin_imag_ohm,zout_real_ohm,zout_imag_ohm,nf_est_db

要求：
1. dry-run 生成计划；
2. 支持从 CSV 读取 lookup；
3. active_sizing 根据 total_current_ma 和 power_ratio_list 选候选；
4. 写单元测试。

禁止：
- 不要使用论文作者 N65 lookup table；
- 不要把商业 PDK 日志提交。
```

## Prompt 8：Stage 2 impedance matching

```text
当前阶段：阶段 8，实现 Stage 2 impedance matching。

目标：
把论文 Table II Stage 2 变量和公式 (1) 接入 Python 工具，先实现随机候选/网格候选，再预留 PSO 接口。

请修改：
- src/orfadc/tools/impedance_matching.py
- src/orfadc/tools/cost_functions.py
- config/variable_ranges_table_ii.yaml
- src/orfadc/experiments/run_stage2_matching.py
- tests/test_stage2_matching.py
- docs/04_tool_middleware.md

功能：
1. 读取 Stage 2 变量范围；
2. 生成候选 k,L1,L2,R1,R2,C1,C2,Ls；
3. 对已有示例 sim_result 计算公式 (1)；
4. 支持 Cadence runner hook；
5. 输出 passive_params_cpstages 和 sim_result_cpstages。

验收：
- 无 Cadence 时 example data 测试通过；
- 有 Cadence 时可以替换 runner 获取真实 NF/S11；
- 不把 dry-run 当 pass。
```

## Prompt 9：Stage 3 band planning

```text
当前阶段：阶段 9，实现 Stage 3 band planning。

目标：
先实现低保真 RLC/MCR-like band planning，计算通带 gain 和 ripple，并用公式 (2) 排序。

请修改：
- src/orfadc/tools/band_planning.py
- src/orfadc/tools/cost_functions.py
- src/orfadc/experiments/run_stage3_band_planning.py
- tests/test_band_planning.py
- docs/04_tool_middleware.md

实现顺序：
1. 用简化二阶谐振峰模型；
2. 输入 fc_ghz、fbw_ratio、gain_user_db；
3. 自动生成 2-3 个交错峰；
4. 计算 gain_cal_db；
5. 用 stage3_cost 排序；
6. 预留论文 MCR 公式 (3) 的接口。

禁止：
- 不要声称简化 RLC 等于论文 MCR；
- 不要把理论曲线说成 Cadence 仿真曲线。
```

## Prompt 10：Fullchain evaluation

```text
当前阶段：阶段 10，连接 fullchain evaluation。

目标：
把 active_params 和 passive_params 合并成完整候选，调用完整 OCEAN/Spectre 流程，并保存统一结果。

请修改：
- src/orfadc/tools/fullchain_eval.py
- src/orfadc/cadence/run_ocean.py
- src/orfadc/cadence/parse_psf.py
- circuit/ocean/run_fullchain.ocn
- circuit/ocean/export_results.ocn
- docs/03_cadence_environment.md

输出目录结构：
results/runs/<spec>/<seed>/<candidate>/
  params.yaml
  ocean.log
  spectre.log
  sparams.csv
  noise.csv
  compression.csv
  metrics.json
  agent_trace.json

要求：
1. dry-run 明确 status=dry_run；
2. 真实仿真失败也写 failure report；
3. 不提交敏感 netlist；
4. metrics.json schema 稳定。
```

## Prompt 11：确定性 Manager/Searcher/Refiner

```text
当前阶段：阶段 11，实现确定性 Manager/Searcher/Refiner。

目标：
先不用 LLM，用规则引擎模拟论文多智能体流程，确认 candidate queue、search/refine 调度和 failure report 能跑通。

请修改：
- src/orfadc/agents/manager.py
- src/orfadc/agents/searcher.py
- src/orfadc/agents/refiner.py
- src/orfadc/agents/memory.py
- src/orfadc/experiments/run_agent_loop.py
- tests/test_agent_loop.py
- docs/05_multi_agent_design.md

规则：
- Manager 队列空则 SearchCandidates；
- 有候选则 RefineCandidate；
- pass 则 Stop；
- 预算耗尽则 Stop with failure。
- Refiner 根据 nf/s11/gain/ripple/ip1db/power violation 决定回溯阶段。

验收：
- dry-run 可以生成 agent_trace.json；
- KB/EB JSONL 可以写入；
- 单元测试通过；
- 不接 LLM。
```

## Prompt 12：LLM JSON agent 接入

```text
当前阶段：阶段 12，接入 LLM JSON agent。

目标：
在确定性 agent 已经跑通后，让 LLM 只输出结构化 JSON 决策，不直接改 netlist。

请修改：
- src/orfadc/agents/prompts/manager.md
- src/orfadc/agents/prompts/searcher.md
- src/orfadc/agents/prompts/refiner.md
- 新增 src/orfadc/agents/llm_client.py 或 llm_policy.py
- docs/05_multi_agent_design.md

要求：
1. 所有 prompt 明确 JSON schema；
2. 所有输出先 JSON parse，再执行；
3. parse 失败走 deterministic fallback；
4. 记录 prompt_tokens、completion_tokens、latency_s；
5. LLM 不接触 PDK 路径，不输出 netlist；
6. agent_trace.json 记录每次 action 和 observation。

验收：
- 用 mock LLM 测试通过；
- 真实 LLM 可选；
- 不因 LLM 输出错误破坏仿真目录。
```

## Prompt 13：KB/EB 自进化 memory

```text
当前阶段：阶段 13，实现 KB/EB 自进化 memory。

目标：
实现论文 Self-Evolving Retrieve-and-Refine Mode 的最小版本。

请修改：
- src/orfadc/agents/memory.py
- src/orfadc/agents/manager.py
- src/orfadc/experiments/run_self_evolution.py
- docs/05_multi_agent_design.md
- docs/06_experiments.md

KB 保存事实：
- spec
- candidate
- metrics
- pass/fail
- run_dir

EB 保存经验：
- condition
- insight
- source_candidate_ids
- confidence
- last_verified_at

要求：
1. 实现 top-k 相似 spec 检索；
2. 实现 EB confidence 更新；
3. 失败经验不能直接作为正向建议；
4. prompt context 中必须标注经验来源。

验收：
- JSONL 可读写；
- top-k 检索有测试；
- confidence 更新有测试。
```

## Prompt 14：GA/BO/PSO/SA baseline

```text
当前阶段：阶段 14，实现优化算法 baseline。

目标：
实现论文实验结构中的 baseline，但先在简化 MVP 上跑，不直接追三阶段 LNA。

请修改：
- src/orfadc/baselines/random_search.py
- src/orfadc/baselines/ga_vanilla.py
- src/orfadc/baselines/bo_vanilla.py
- src/orfadc/baselines/ga_subtool.py
- src/orfadc/baselines/bo_subtool.py
- src/orfadc/experiments/run_ablation.py
- docs/06_experiments.md

要求：
1. random_search 先可运行；
2. GA/BO 如果依赖缺失，提供接口和清晰报错；
3. 所有 baseline 使用同一 metrics schema；
4. 输出 pass@1、avg_time_s、num_sims；
5. 不伪造论文 Table IV/V 数值。
```

## Prompt 15：结果表和图生成

```text
当前阶段：阶段 15，生成 Table/Fig-like 输出。

目标：
把本工程实验结果汇总为论文结构类似的 CSV 和 PNG。

请修改：
- src/orfadc/plots/plot_fig7_like.py
- src/orfadc/plots/plot_fig8_like.py
- src/orfadc/plots/plot_fig9_like.py
- src/orfadc/plots/plot_fig10_like.py
- src/orfadc/plots/plot_fig11_like.py
- 新增 src/orfadc/experiments/export_tables.py
- docs/06_experiments.md

输出：
- results/tables/table_iii_specs.csv
- results/tables/table_iv_like.csv
- results/tables/table_v_like.csv
- results/tables/table_vi_like.csv
- results/figures/fig7_like_sparams.png
- results/figures/fig8_like_time.png
- results/figures/fig9_like_search_refine.png
- results/figures/fig10_like_sample_efficiency.png
- results/figures/fig11_like_fom.png

要求：
- 所有图标题写 like 或本工程结果；
- 数据来源写入 metadata；
- 无数据时生成 schema 和说明，不伪造结果。
```

## Prompt 16：论文级近似复现计划执行

```text
当前阶段：阶段 16，论文级近似复现。

前提：
- MVP 单级 LNA 已跑通；
- Stage 2/3/fullchain 已跑通；
- agent loop 已跑通；
- Table/Fig-like 输出脚本已跑通。

目标：
按 S1 -> S2 -> S4 -> S5/S6 -> S7 -> S8 -> S9/S10 的顺序，逐步尝试 Table III 的 10 个 specs。

请生成：
1. 每个 spec 的执行顺序；
2. 每个 spec 的仿真预算；
3. 失败后如何放宽或诊断；
4. 5 seeds 的目录组织；
5. 如何输出 pass@1；
6. 如何写不可严格对比说明。

禁止：
- 不要声称严格复现论文；
- 不要把 TSMC40/教学模型结果说成 N65；
- 不要删除失败记录。
```

## Prompt 17：课程设计/科研训练报告生成

```text
当前阶段：阶段 17，生成课程设计或科研训练报告。

请基于项目文档和 results/ 中的实际结果，生成一份报告草稿：

标题：
Open-RFAmpDesigner-Cadence：基于 Cadence 与多智能体 LLM 的 RF LNA 自动设计方法级复现

必须包含：
1. 论文背景；
2. 可复现边界；
3. 我的 OTA 前置基础；
4. 从 OTA 到 LNA 的技术迁移；
5. Cadence testbench；
6. Python 自动化；
7. 工具中间件；
8. 多智能体；
9. 实验结果；
10. 与论文差异；
11. 风险和改进；
12. 附录：命令、配置、schema。

要求：
- 只引用实际生成的结果；
- 没跑出来的部分写“计划/未完成/原因”；
- 不夸大；
- 面向本科课程设计可读。
```

## Prompt 18：每次故障排查通用提示词

```text
当前项目：Open-RFAmpDesigner-Cadence。

我遇到了一个错误。请按故障排查方式工作：

错误现象：
<粘贴命令和报错>

相关文件：
<列出文件>

最近改动：
<说明>

请你：
1. 先判断错误属于 Python、Cadence/OCEAN、Spectre、PSF解析、配置路径、数据格式、还是 agent 逻辑；
2. 列出最可能的 3 个原因；
3. 给出最小验证命令；
4. 只修改必要文件；
5. 修改后运行测试；
6. 不要重构无关代码；
7. 不要删除已有实验结果；
8. 如果涉及 PDK/授权/远程环境，请只给检查步骤，不要要求我公开敏感路径。
```

## Prompt 19：阶段完成验收提示词

```text
请对当前阶段做验收审查。

阶段名称：
<填写阶段>

目标：
<填写目标>

我认为已完成：
<填写完成项>

请检查：
1. 文件是否齐全；
2. 命令是否能运行；
3. 测试是否通过；
4. 是否有 dry-run 被误写成真实仿真；
5. 是否有 PDK/路径/日志泄露风险；
6. 是否满足进入下一阶段的条件；
7. 下一阶段第一步应该做什么。

请按“通过/不通过/需要补充”的格式输出。
```
