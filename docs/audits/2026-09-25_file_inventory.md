# 文件清单与实现状态

范围：2026-09-25 的 `rg --files`、Git 已跟踪/未跟踪项及本地被忽略的运行产物。对源码、配置、网表、测试逐文件读过实现；长篇方案文档核对了结构、事实、当前状态、示例与交叉引用。`docs/project_history/` 中被忽略的原始聊天/清单只核对存在性与用途，未复制其敏感正文。论文插图属于参考素材，不是本工程仿真结果。

状态：`实测` 有本地 Spectre/OCEAN 原始结果；`测试` 有纯 Python 测试；`骨架` 有接口但不构成完整流程；`模板` 仅注释或待填 Cadence 脚本；`方案` 文档计划；`历史` 截止日期的记录。

## 入口、论文与配置

| 文件 | 用途与本次判定 |
| --- | --- |
| `README.md` | 入口；说明目标，新增审查入口；不得据其 MVP 清单推断 LNA 已完成。 |
| `.gitignore` | 忽略私有远程配置、模型路径及结果/日志；已核对关键私有与本地运行路径生效。 |
| `references/paper/RFAmpDesigner.pdf` | 英文论文原件；14 页；Table III/Fig. 7 已视觉核对，其余关键页文本和公式逐页核对。 |
| `references/paper/RFAmpDesigner_中文翻译.md` | 辅助翻译；与原文不一致时以 PDF 为准。 |
| `references/paper/source/RFAmpDesigner_extracted_text.txt` | 搜索定位用；公式和表格有抽取错位风险。 |
| `references/paper/source/2605.10093-source.tar` | 公开 arXiv 源码包；检查条目，未执行。 |
| `references/paper/figures/*`、`references/paper/README.md` | 原文图片与资料索引；非项目实验图。 |
| `config/specs_table_iii.yaml` | Table III 十行；PDF p.8 逐格核对，回归测试。 |
| `config/variable_ranges_table_ii.yaml` | Table II 两阶段范围；PDF p.5 逐格核对，符号边界保持符号。 |
| `config/remote_cadence.example.yaml` | 公开空模板；Xvfb 可选路径，真实配置被忽略。 |
| `config/remote_cadence.local.yaml` | 本地私有配置，Git 忽略；只核对存在性与连接结果，不将内容复制到审查报告。 |
| `config/model_paths.yaml` | PDK 路径占位，无商业模型。 |
| `config/sweep_settings.yaml` | 五 seeds、1 h 默认、dry-run；5 h 难任务只在论文/计划中，未运行。 |
| `config/agent_settings.yaml` | manager/refiner/memory 预算占位；现有骨架未读取。 |

## Cadence/Python 运行层

| 文件 | 用途与本次判定 |
| --- | --- |
| `src/orfadc/__init__.py`、`src/orfadc/cadence/__init__.py` | 包标记。 |
| `src/orfadc/schemas.py` | Spec/Candidate/SimResult/RunConfig；规格有限值、正频率/电流已加校验；非完整结果 schema。 |
| `src/orfadc/config_loader.py` | YAML/JSON I/O；已加重复 ID 与非有限 JSON 拒绝。 |
| `src/orfadc/cadence/remote_runner.py` | SSH/SCP/OCEAN 执行；此前实机验证且有 mock 测试；当前 SSH 探测超时。 |
| `src/orfadc/cadence/verify_remote.py` | 远端工具/传输探针；本次返回 banner exchange timeout。 |
| `src/orfadc/cadence/verify_cadence_environment.py` | Spectre 版本及 OCEAN smoke 验证；2026-09-24 有实机成功记录，本次未复验。 |
| `src/orfadc/cadence/run_ocean.py` | 本地 subprocess 封装；与 RemoteRunner 分离，未接真实 LNA。 |
| `src/orfadc/cadence/run_spectre.py` | 本地 subprocess 封装；未接真实 LNA。 |
| `src/orfadc/cadence/psfascii_reader.py` | 简单标量/复数迹线与 OTA 插值；有单元测试及真实 SP 文件交叉读取。 |
| `src/orfadc/cadence/parse_psf.py` | CSV reader 可用；原生 PSF 解析明确为占位。 |
| `src/orfadc/cadence/touchstone.py` | 二端口 RI/MA/DB 解析；已加入阻抗、非有限值、频率排序和零幅值处理；有测试。 |
| `src/orfadc/cadence/extract_rf_metrics.py` | 通带 S 参数汇总；已修正浮点端点与非法数据；没有 NF/压缩点提取。 |
| `src/orfadc/cadence/noise_metrics.py` | 审查后新增：人工 PSFASCII 样例的 NF/NFmin 规范化、频率对齐与 CSV；未用真实 Spectre noise 输出验收。 |
| `src/orfadc/cadence/netlist_template.py` | 字符串参数块生成器，尚未接白名单与真实网表；不可用于不可信输入。 |
| `src/orfadc/experiments/run_ideal_twoport.py` | 实测二端口 runner；已改独立运行目录、脱敏结构化指标和解析失败状态；新版本因 SSH 超时未实机复验。 |
| `src/orfadc/experiments/extract_noise.py` | 审查后新增：已有 PSFASCII 到标准化 noise CSV/metrics 的命令；固定 `parsed_unverified`，不声称仿真通过。 |
| `src/orfadc/experiments/run_spec.py` | S1 等规格的 dry-run 候选入口；现在强制 `--dry-run`。 |
| `circuit/spectre/ideal_twoport.scs` | 50 ohm 被动 RLC `sp` 网表；此前在 Spectre 25.1 实测 47 点。 |
| `circuit/spectre/ideal_twoport_noise_unverified.scs` | 审查后新增的被动二端口 SP-noise 候选网表；语法和结果格式尚未在本机 Spectre 验证。 |
| `circuit/ocean/verify_design.ocn` | OCEAN/SKILL 解释器 smoke，2026-09-24 实机通过；不检查 PDK。 |
| `circuit/ocean/create_lna_schematic.ocn` | 模板；没有真实 OA schematic 创建。 |
| `circuit/ocean/run_sparam.ocn` | 模板；真正 `sp` 运行目前由直接 Spectre 网表完成。 |
| `circuit/ocean/run_noise.ocn` | 模板；没有 NF/NFmin 仿真。 |
| `circuit/ocean/run_compression.ocn` | 模板；没有 HB/PSS/功率 sweep。 |
| `circuit/ocean/run_fullchain.ocn` | 模板；无全链执行。 |
| `circuit/ocean/export_results.ocn` | 模板；无通用 OCEAN 导出。 |

## 工具、多智能体、实验与绘图

| 文件 | 用途与本次判定 |
| --- | --- |
| `src/orfadc/tools/__init__.py`、`src/orfadc/agents/__init__.py` | 包标记。 |
| `src/orfadc/tools/cost_functions.py` | 论文公式 (1)(2) 有回归测试；全链违规量现在区分缺测、未验证评分和真实通过。默认全链 S11 -10 dB 是项目假设。 |
| `src/orfadc/tools/active_sizing.py` | 功率比例/电流与有限 lookup 选择；已拒绝负比率、跨 stage 匹配及超流；未生成真实 lookup。 |
| `src/orfadc/tools/impedance_matching.py` | 接口骨架；外部给定指标只得 `unverified_score`，无 PSO/OCEAN。 |
| `src/orfadc/tools/band_planning.py` | 公式 (2) 的低保真评分接口；无 MCR 公式 (3) 或 SA。 |
| `src/orfadc/tools/fullchain_eval.py` | dry-run 与真实模式 guard；真实模式明确 `not_implemented`，防止模板脚本冒充结果。 |
| `src/orfadc/agents/manager.py` | 候选列表与简单动作选择骨架；无预算、优先队列、终止闭环。 |
| `src/orfadc/agents/searcher.py` | 固定 power ratio 的初始候选；无真实 Stage 2 匹配。 |
| `src/orfadc/agents/refiner.py` | 规则式回溯；已拒绝缺测、负违规量和与分项不一致的总量直接 accepted；仍无完整 loop。 |
| `src/orfadc/agents/memory.py` | JSONL 读写；无 KB/EB 检索/置信度。 |
| `src/orfadc/agents/prompts/manager.md` | JSON-only 角色提示骨架。 |
| `src/orfadc/agents/prompts/searcher.md` | 简短提示骨架，未有可执行 schema。 |
| `src/orfadc/agents/prompts/refiner.md` | 规则提示骨架，未有可执行 schema。 |
| `src/orfadc/baselines/random_search.py` | 仅随机功率比函数，无 baseline 实验 runner。 |
| `src/orfadc/baselines/ga_vanilla.py`、`ga_subtool.py` | 仅 docstring 占位。 |
| `src/orfadc/baselines/bo_vanilla.py`、`bo_subtool.py` | 仅 docstring 占位。 |
| `src/orfadc/plots/plot_fig7_like.py`、`plot_fig8_like.py`、`plot_fig9_like.py`、`plot_fig10_like.py`、`plot_fig11_like.py` | 均为 docstring 占位；没有生成论文同类图。 |

## 测试文件

| 文件 | 覆盖与局限 |
| --- | --- |
| `tests/test_cost_functions.py` | Eq. (1)(2)、缺测/非有限与未验证评分；无 Cadence。 |
| `tests/test_paper_tables.py` | PDF Table II/III 数值及公式回归；防止配置漂移。 |
| `tests/test_touchstone.py` | 端口顺序、RI/DB、无效输入、带边、归档覆盖保护；部分 MA 路径尚无专测。 |
| `tests/test_noise_metrics.py` | 审查后新增：人工 PSFASCII 样例、缺测/非有限/频率不对齐、未验证 provenance；不能代替 Cadence 实测。 |
| `tests/test_psfascii_reader.py` | OTA 迁移解析与交叉迹线；没有 NF/压缩点格式测试。 |
| `tests/test_remote_runner.py` | SSH/SCP 命令构造、配置、安全路径、Xvfb 注入与超时；mock 不等于远程存活。 |
| `tests/test_verify_cadence_environment.py` | OCEAN 报告键值解析。 |
| `tests/test_config_contract.py` | Spec/重复 ID/非有限 JSON。 |
| `tests/test_agent_safety.py` | Refiner 对缺测/负值/布尔/总量不一致与 fullchain 模板不误报通过。 |

## 文档与外部项目

| 文件 | 本次判定 |
| --- | --- |
| `docs/00_index.md` | 当前文档入口，需保持与新增审查材料同步。 |
| `docs/01_paper_theory.md`、`02_rf_lna_basics.md`、`03_cadence_environment.md`、`04_tool_middleware.md` | 教学/结构精简入口，不构成实测。 |
| `docs/05_multi_agent_design.md`、`06_experiments.md`、`07_reproduction_limits.md`、`08_student_tutorial.md` | agent/实验/边界/教学计划。 |
| `docs/09_step_by_step_operation_guide.md` | 步进计划；末尾旧阶段示例已改为当前 noise 任务。 |
| `docs/10_detailed_prompts.md` | 旧阶段提示词库；历史实施顺序，不能代表最新状态。 |
| `docs/11_multi_agent_explained.md` | 已拆为 agent_system 的总入口；不再含旧第 17 节。 |
| `docs/12_cadence_environment_validation.md` | 历史 SSH/SCP/OCEAN 验收；已补被动 `sp` 与本次 SSH 复验失败。 |
| `docs/13_chatgpt_handoff.md` | 脱敏交接快照；更新本次审查状态。 |
| `docs/14_ideal_twoport_rf_smoke.md` | 2026-09-25 首次真实二端口结果；已注明后续运行独立目录。 |
| `docs/17_noise_data_pipeline.md`、`18_ssh_recovery_from_ota.md` | 审查后新增：noise 数据合同与 SSH/VMware 失响应排障证据；均明确了实测边界。 |
| `docs/15_autonomous_completion_prompts.md`、`16_paper_to_project_audit_prompt.md` | 实施/审查指令，不是完成证明。 |
| `docs/16_implementation_status.md` | 阶段状态入口；阶段 00 审查完成不等于阶段 01-14 实现。 |
| `docs/audits/2026-09-25_*.md`、`2026-09-26_audit_closure.md` | 英文论文事实、文件清单、跨层追踪、问题台账、主报告和收尾判定；历史快照与最新补记并存。 |
| `docs/open_rfampdesigner_cadence_design.md`、`open_rfampdesigner_cadence_full_plan.md` | 设计方案；样例数字与预期目录不可作为实测结果。 |
| `docs/ota_to_lna_migration_notes.md` | 迁移说明；已给 2026-09-12 旧 OCEAN 状态加历史注释。 |
| `docs/agent_system/README.md`、`00_overview_and_paper_agents.md`、`01_workflow_queue_memory_react.md`、`02_agent_roles_and_implementation.md` | 教学型 agent 说明与代码草图；代码草图尚未落地。 |
| `docs/agent_system/03_project_implementation_plan.md`、`04_paper_vs_project_gap.md`、`05_next_task_prompt.md`、`06_design_discipline.md` | 实施步骤、论文差异、历史提示词和纪律；已修正差异表中“无真实 RF S 参数”的过时说法。 |
| `docs/project_history/README.md`、`2026-08-31_directory_unification.md` | 脱敏历史索引与目录迁移记录；不修改其当时测试结果。 |
| `docs/project_history/` 下原始聊天、旧 README、MANIFEST | Git 忽略的本地历史；含个人上下文，审查只使用必要决策，不公开内容。 |
| `third_party_notes/README.md` | 开源项目链接和复用范围说明；目前没有第三方代码被复制进仓库，许可证尚未逐仓库重新核实。 |

## 本地结果

`results/runs/rf_smoke/ideal_twoport/` 保留首次真实 Spectre 的网表、S2P、PSFASCII、CSV、metrics 与日志；它们被 Git 忽略。审查复验产生一条单独 `mkdir_failed` 记录，原因是 SSH banner exchange 超时，未调用 Spectre。`results/runs/S1/seed0/dry_run_candidates.json` 是模拟候选，无 Cadence 数据。无 Table IV/V/VI-like 表格或 Fig.7-11-like 自有曲线。

后续同日补记：硬重置恢复来宾后，新版 runner 在独立目录 `results/runs/rf_smoke/ideal_twoport/20260925T152506Z_273884f2/` 成功实测；OCEAN 环境在 `results/logs/cadence_environment/20260925_after_vm_reset/` 复验成功。上文涉及“当前 SSH 超时”的表格项属于审查时快照，不再代表现状；详情见 `docs/18_ssh_recovery_from_ota.md`。

2026-09-26 补记：原配置启动后轻负载 SSH/Tools/SCP 与新一次被动二端口 Spectre 通过，结果在 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/`；此前持续失响应风险未由这次短时成功消除。noise、压缩点和有源 LNA 仍无真实结果。
