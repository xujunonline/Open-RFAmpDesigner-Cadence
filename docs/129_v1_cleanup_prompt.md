# 129 v1 清理审查：详细提示词与执行记录（2026-10-05）

v1（标签 `v1-decision-points`，提交 e80dfd3）由两段工作叠加而成：
- 前期在 Codex 中完成"路线 B"（Virtuoso/OCEAN 实机链路、教学电路、远程恢复与隔离等）；
- 后期在 Claude Cowork 中完成"路线 A"（`src/orfadc/repro` 可运行复现、PDK v2 后端、docs/115–128）。

因此仓库里有大量与当前复现无关的历史代码、测试、脚本和文档。本文件给出清理的**详细提示词**（可直接交给 Claude Code / Cowork 执行），
并在 §3 记录本次实际执行的结果。

---

## 1. 提示词（原文，可复用）

```text
你是本仓库（Open-RFAmpDesigner-Cadence，复现 arXiv:2605.10093 RFAmpDesigner）的维护者。目标：在不改变任何已发布结果的前提下，
把 v1 清理成"只包含当前复现所需内容"的干净版本 v1.1，并修正发现的问题。全程用中文汇报；代码注释与标识符用英文。

硬性约束
1. 不读、不打印、不提交 config/remote_cadence.local.yaml、config/model_paths.local.yaml、私钥；不做任何 ssh/scp/Spectre。
2. 不改变结果：results/repro 下的原始档不改；清理后 `bench replot` 重建的表格必须与 results/repro/2026-10-03 逐字节一致；
   全量 pytest 必须通过（允许删除仅测试已删除代码的测试，但不得删除测试保留代码的测试）。
3. 删除只针对"当前复现不依赖、且在 v1 标签中可完整找回"的内容；不做 git 历史改写。每一项删除都写进 docs/LEGACY.md，
   并给出找回命令 `git checkout v1-decision-points -- <path>`。
4. 不伪造结果，不改动结论数字；文档中如发现与原始档不符的数字，以原始档为准并注明更正。

步骤
A. 盘点：列出全部受版本控制文件；以 src/orfadc/repro 的全部模块为种子，用 AST 求 orfadc 内部导入闭包，得到"必须保留的代码"。
   同时列出每个测试导入的 orfadc 模块；只导入保留模块的测试保留，其余标记为路线 B 测试。
B. 判定删除（路线 B / 一次性 / 冗余）：
   - 代码：orfadc/agents、orfadc/experiments、orfadc/baselines、orfadc/plots、orfadc/metric_contract.py、
     orfadc/cadence 中除 psfascii_reader/remote_runner 外的模块、orfadc/tools 中除 cost_functions/mcr_lumped 外的模块。
   - 测试：只覆盖上述代码的测试。
   - circuit/（OCEAN/SKILL/教学网表；复现后端自行生成网表）。
   - 文档：docs/01–114、docs/agent_system、docs/audits、docs/project_history、open_rfampdesigner_cadence_*.md、ota_to_lna_migration_notes.md；
     其中仍有效的规则（远程隔离/预算，原 docs/113–114）合并进 CLAUDE.md。
   - 配置：未被保留代码/测试/文档引用的 config 文件（agent_settings、sweep_settings、metrics_v1.schema、requirements_bo）。
   - 脚本：一次性脚本（fix_claude_rationale、claude_fix/、a09_stability_acceptance）与已用过的 v1 发布脚本（git_snapshot_v1*、git_push_v1*、export_v1_tree*）。
   - 冗余产物：*.bak；与 2026-10-03 逐字节相同的 results/repro/2026-09-29（保留 2026-10-03 作为基线）。
C. 修正问题：
   - 保留代码：pyflakes 无未使用导入/未定义名；硬编码的本机路径（如 /home/claude/proj）改为相对仓库根；
     docstring/注释中指向已删除模块或文档的引用改掉。
   - 文档：00_index 重写为只列保留文档；README、CLAUDE.md 与当前结构一致；docs/115–128 中指向已删除文档、旧基线路径、
     过期数字（如 Spectre 累计、上限、PDK 名称）的地方逐条更正；`.claude` 的 skills/agents/commands/hooks 不再引用已删除路径。
   - 其他：.gitignore 与新结构一致；确认没有 PDK 原始数据被跟踪。
D. 验证：全量 pytest；`bench smoke`；`bench replot --out <临时副本>` 与 results/repro/2026-10-03 表格对比一致；
   全仓库 grep 已删除路径（docs/0x–114、orfadc.experiments、orfadc.agents、circuit/ 等）无残留引用（LEGACY.md 除外）。
E. 交付：生成补丁与应用脚本，在 Windows 宿主上从 main 应用、跑测试、提交 "v1.1: cleanup"、打标签 v1.1-clean；
   推送到 GitHub 需用户确认。写本文件 §3 的执行记录。
```

## 2. 判定依据（摘要）

- `src/orfadc/repro` 的导入闭包只依赖：`orfadc/__init__.py`、`schemas.py`、`config_loader.py`、
  `cadence/{__init__,psfascii_reader,remote_runner}.py`、`tools/{__init__,cost_functions}.py`；测试另需 `tools/mcr_lumped.py`（Eq.(3) 节点分析参考）。
- 其余 `orfadc` 子包（agents 37、experiments 133、cadence 其余 21、tools 其余 11、baselines 5、plots 8 个文件）只被路线 B 的脚本与测试使用。
- 路线 A 的 GA/BO 基线在 `repro/baselines.py`，与 `orfadc/baselines/` 无关。

## 3. 执行记录（2026-10-05，Claude Cowork）

**方法：** 在 Windows 宿主上 `git archive v1-decision-points` 导出 v1 树，在云端工作区建临时仓库做清理与验证；
两个只读审查子智能体分别审查代码（含 `.claude`、脚本、配置）与文档一致性，结论经逐条核对后采纳。
最后由 `scripts/apply_v1_cleanup.cmd` 在 Windows 仓库上从 main 应用、跑测试、提交并打标签 `v1.1-clean`。

**规模：** 受版本控制文件 734 → 173；删除 566 个（清单 `docs/LEGACY_files.txt`），修改/新增 45 个。

**验证：**
- 清理前（v1 树，统一为 LF 后）：全量 764 passed、382 skipped；清理后：88 passed（删除的 148 个测试只覆盖已删代码）。
- `pyflakes src tests scripts` 无告警。
- `bench replot` 从 `results/repro/2026-10-03/raw` 重建的 Table IV/V（md、csv）与 SUMMARY 和已提交版本逐字节一致（除生成时间行）；`bench smoke` S2 通过。
- 全仓库已无对已删路径的现行引用（docs/116、docs/119 中的历史记录与 LEGACY.md 除外）。

**代码修正：**
- `.claude/hooks/guard_bash.py`：远程动作规则改为对 ssh/scp、`bench cadence-check`、`bench pdk-*`、`--backend cadence|pdk` 要求确认
  （原规则只拦已不存在的开关，PDK/Spectre 运行实际上被 `bench:*` 自动放行）；`settings.json` 去掉已删模块与环境变量。
- `repro/llm.py`：`ORFADC_LLM_MAX_CALLS` 改为创建策略时读取（原为导入时读取，运行中改环境变量无效）；默认值 200 不变。
- `repro/mcp_server.py`：`run_autonomous` 支持 S9s/S10s，预算改用 `bench.budget_for`（含 `ORFADC_BUDGET_SCALE`）。
- `repro/bench.py`：结果 JSON 的 `local_evidence` 改为仓库相对路径；模块说明列全子命令；去掉未用变量/导入。
- `schemas.py` 删去只被路线 B 使用的 `SimResult/Candidate/RunConfig`；`tools/cost_functions.fullchain_violations` 无调用者，删除。
- `requirements_repro.txt` 补 `scipy`（`pdk_fit` 需要）；`config/model_paths.yaml` 改为与 `pdk_v2.load_pdk_config` 一致的 `model_paths.example.yaml`。
- 脚本：Cadence 主机/端口改从 `remote_cadence.local.yaml` 读取（不再写死 IP）；虚拟机不可达时跳过 `cadence-check`；
  `run_all_windows` 防空目录；`run_job_queue` 支持 `-Queue`；`ablation_report_best_backoff.py` 去掉本机绝对路径。
- 其余为未用导入/变量清理（agents、mcp_server、pdk_fit、pdk_v2、测试）。

**文档修正：**
- README、CLAUDE.md、00_index 重写为清理后的结构；远程隔离/预算规则（原 docs/113–114）并入 CLAUDE.md 规则 2。
- 计数更正：docs/122 "6/8" → 5/8，docs/123 "7/8" → 6/8（S1–S5、S8 是 6 个规格）；docs/126 S6 1× 行误用了代理路径的 0.93。
- 过期状态：docs/127（PDK 只有 seed 0、Spectre 483/550、P2 时间）、docs/123（"正在进行"、"下一步"）、docs/115 §7、docs/117 阶段 7、
  docs/118 P8-v2、docs/120 待决事项、docs/119 §编号；基线路径统一为 `results/repro/2026-10-03`。
- `.claude/skills/cadence-backend-bridge` 改写为现状说明（v1 宏模型 + PDK 后端 + 迁移步骤）；其余 skill 的过期引用与策略列表修正。
- 新增 docs/128（IC618_rf 工艺盘点）、LEGACY.md、LEGACY_files.txt。

**已知问题（留给 v2，未在 v1.1 改动，以免改变已发表结果的生成方式）：**
1. `bench design` 的输出文件名只区分 Q 与预算倍数；不同 `ORFADC_LLM_MAX_CALLS`、`ORFADC_SPECTRE_MAX_PER_DESIGN`、
   `ORFADC_STAGE2_BACKOFF`、`ORFADC_REPORT_BEST` 的运行写到同一目录会互相覆盖；`llm-seeds` 会静默跳过带后缀的文件。v2 加 `agent_impl` 等后缀时一并解决。
2. Manager 提示词要求功率比 0.15–0.7，校验接受 0.1–0.8（`llm.py`）。
3. `--backend cadence` 不受 `ORFADC_SPECTRE_MAX_PER_DESIGN` 约束（只有 PDK 后端受约束）。
4. `pdk_fit.refit_table` / `add_large_signal` 没有命令行入口，docs/122 的拟合表无法用 CLI 直接重建；建议加 `bench pdk-refit`。
5. `write_summary` 在单独跑 table4/table5/fig10 时不带 Fig. 5 段；Fig. 8 写死 5 seed。
6. `repro/pdk_inventory.sh` 写死 Cadence 安装前缀 `/opt/eda/cadence`，换虚拟机（IC618_rf）前需确认。
7. 只被测试使用的库函数保留（psfascii_reader 的部分解析函数、remote_runner 的 OCEAN 入口、`pdk_v2.latest_table`、
   `twoport.coupled_resonator`、`DeviceOP.gm_over_id`、`memory` 模板常量、`llm.POLICIES`）。
8. docs/115–127 之间有内容重复（LLM 表、引擎误差、PDK 通过表），本次只修正矛盾，未合并。
9. docs/123 中 Spectre 累计的一步（≈215 + 55 应为 ≈270，文中为 ≈302）未能核实，保留原文。
