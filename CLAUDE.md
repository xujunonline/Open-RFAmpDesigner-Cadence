# CLAUDE.md — Open-RFAmpDesigner-Cadence

本仓库复现论文 *RFAmpDesigner: A Self-Evolving Multi-Agent LLM Framework for Automated RF Amplifier Design*
（arXiv:2605.10093，原文 `references/paper/`）。两条路线并存：

| 路线 | 目录 | 现状 | 能否无 Cadence 运行 |
|---|---|---|---|
| **A. 可运行复现（推荐起点）** | `src/orfadc/repro/` | 论文 Stage 1–4 工具、Eq.(1)(2)(3)、Manager/Searcher/Refiner、KB/EB、GA/BO 基线、Table IV/V、Fig.5/7/8/10 均可端到端运行 | ✅ 是（代理仿真器） |
| B. Cadence/PDK 实机链路 | `src/orfadc/cadence/`、`src/orfadc/experiments/`、`circuit/` | SSH/OCEAN/Spectre 原始档与审计齐全，但 PDK 级合格 LNA 与在线模型未闭环 | ❌ 需授权环境 |

路线 A 的仿真后端是 `SurrogateBackend`（两端口噪声相关矩阵级联 + 开放 EKV 类 65 nm 器件模型）。
它是**趋势级证据**，不是 PDK/硅结果；所有输出都带 `not_silicon_result` / `LABEL` 标记。
接 Cadence 只需实现 `orfadc.repro.tools.Backend` 协议（见 `.claude/skills/cadence-backend-bridge/SKILL.md`）。

## 常用命令（仓库根目录执行）

```bash
# Linux / macOS / Git-Bash
export PYTHONPATH=src
python -m pip install -r config/requirements_repro.txt
python -m pytest tests -q                              # 全量离线回归（conftest 自动设置 basetemp）
python -m pytest tests/test_repro_core.py -q           # 复现管线单测（~15 s）
python -m orfadc.repro.bench smoke --out results/repro/smoke
python -m orfadc.repro.bench design --spec S2 --seed 0 --policy rule
python -m orfadc.repro.bench all --seeds 5 --out results/repro/latest     # 全部表图（2 核约 1.5 h）
python -m orfadc.repro.bench replot --out results/repro/latest            # 只从 raw 重算表/图/SUMMARY
python -m orfadc.repro.mcp_server                      # MCP 服务器（通常由 .mcp.json 自动拉起）
python -m orfadc.repro.bench llm-check --policy claude-cli   # Claude Pro/Max 订阅（claude -p），不用 API key
python -m orfadc.repro.bench llm-check --policy codex-mcp    # ChatGPT 订阅（MCP → codex-bridge → codex exec）
python -m orfadc.repro.bench cadence-check --spec S2         # Spectre 宏模型 vs 两端口引擎交叉验证（需 Windows 宿主连 Cadence VM）
python -m orfadc.repro.bench design --spec S9 --policy claude-cli [--backend cadence|pdk]
python -m orfadc.repro.bench pdk-inventory | pdk-characterize [--vds 0.5] | pdk-characterize3 | pdk-check --spec S2   # Cadence v2（docs/120–123）
```

PowerShell：`$env:PYTHONPATH="$PWD\src"`，其余相同。

当前基线结果：`results/repro/2026-10-03/SUMMARY.md`（v1 封版时用当前代码重跑，与 `2026-09-29` 完全一致；解读见 `docs/115` §6）。等效时间按论文"顺序执行"记账；
`ORFADC_PARALLEL=1` 可改为并行记账（Searcher 扇出、PSO 粒子、GA 种群）。S9/S10 在代理模型上不可行，另提供前沿缩放版 S9s/S10s。

## 目录速览（路线 A）

- `repro/twoport.py` ABCD + 噪声相关矩阵（Hillbrand–Russer）；`repro/device.py` 代理器件与 Stage-1 知识库
- `repro/circuit.py` 图 3 三级 LNA、MCR 物理映射（二分法）、压缩点估计
- `repro/mcr_eq3.py` 论文 Eq.(3)（`corrected` = 补上 Y11 分母漏掉的 `s`；`printed` 保留原式）
- `repro/tools.py` Table I 四个工具 + `SimCounter`（等效 EDA 时间成本模型）
- `repro/agents.py` DesignSession / RulePolicy / RFAmpSearcher / RFAmpRefiner / RFAmpManager
- `repro/llm.py` ReAct 式 LLMPolicy（anthropic / openai 兼容 / scripted 离线）
- `repro/memory.py` KB/EB（JSONL，自进化）；`repro/baselines.py` GA/BO vanilla(18-D) 与 subtool(14-D)
- `repro/bench.py` 复现实验入口；`repro/mcp_server.py` MCP 工具中间件；`repro/prompts/*.md` 三个智能体提示词

## 规则（必须遵守）

1. **不伪造结果**：表/图只能来自 `results/` 下的原始运行档；代理结果必须标注"surrogate / trend-level"。
   不得把代理结果写进论文 Table IV/V/VI 的"实测"位置，也不得宣称 PDK/硅通过。
2. **不读、不打印、不提交** `config/remote_cadence.local.yaml`、私钥、`model_paths.local.yaml`；
   远程 Cadence 操作只在用户明确要求时进行，且遵守 `docs/113`、`docs/114` 的隔离/预算规则。
3. 改 `src/` 后先跑 `python -m pytest tests/test_repro_core.py -q`，提交前跑全量 `pytest tests -q`。
4. 论文勘误以代码与测试为准：Eq.(3) Y11 分母末项应为 `R_S ω0³ Q s`（`tests/test_repro_core.py` 用节点分析验证）；
   Table III 的 IP1dB −15 dBm 与正文 OP1dB 9 dBm 在 ~24 dB 增益下自洽（不是矛盾）。
5. 新增实验写一个 `docs/1xx_*.md` 记录：目的、命令、原始档路径、结论、边界；同步 `docs/00_index.md`。
6. 回答与文档默认使用中文；代码注释、标识符用英文。

## 智能体/技能

- MCP 服务器 `codex`（`.mcp.json`，codex-bridge）：`codex_ask`/`codex_status`，用 ChatGPT 订阅向 Codex 要第二意见；`codex_ask` 默认需确认。
- MCP 服务器 `rfamp`（`.mcp.json`）：`new_session → active_sizing → impedance_matching → band_planning → fullchain_evaluation`，
  另有 `query_memory`、`run_autonomous`、`export_design`、`session_status`。
- Skills：`rfamp-design-lna`（Claude 亲自当 RFAmpManager）、`rfamp-reproduce`（跑表图并核对）、
  `rfamp-paper-audit`（论文↔代码逐条核对）、`cadence-backend-bridge`（接入 Cadence 后端）。
- Subagents：`rfamp-searcher`、`rfamp-refiner`、`repro-verifier`。Slash commands：`/repro-smoke`、`/repro-all`、`/design-lna`。
- 详细提示词：`docs/118_claude_prompts.md`；逐步运行手册：`docs/117_step_by_step_runbook.md`；订阅 LLM 与 Cadence 后端：`docs/119_subscription_llm_and_cadence_backend.md`（§4.1 实测）、Cadence v2 计划：`docs/120_cadence_v2_plan.md`，结果：`docs/121`、`docs/122`（PDK 器件拟合、S1–S8）、`docs/123`（第一级三端口实测 Y、差分级实测 Y、第一级噪声校准；`ORFADC_PDK_Y3=0` / `ORFADC_PDK_Y2=0` / `ORFADC_PDK_NOISE1_SCALE=1` 关闭）。多 seed LLM 汇总：`bench llm-seeds --out <dir> --inputs <dir2,...>`。每设计 Spectre 上限：`ORFADC_SPECTRE_MAX_PER_DESIGN`。无源 Q 与预算研究（docs/126）：`ORFADC_Q_MATCH`（默认 25）、`ORFADC_Q_IND`（默认 15）、`ORFADC_BUDGET_SCALE`（默认 1）；总报告：`docs/125`；论文预算对齐与 PDK pass@1：`docs/127`。
- Windows 一键：`scripts/run_all_windows.cmd`（检查 + LLM 主干 + Spectre），`scripts/run_codex_followup.cmd`（只补 Codex），`scripts/run_job_queue.cmd`（执行 `scripts/jobs/queue.txt` 中的 bench 子命令）。
- PDK 数据（器件表、含 PDK 器件参数的设计 JSON）只放 git 忽略的 `results/runs/`、`results/windows_checks/`；`config/model_paths.local.yaml` 存 PDK include/section/器件名。
- 网表↔引擎的独立核对：`tests/fakes/mna_spectre.py`（MNA 解算器，已用真实 Spectre PSF `tests/data/spectre_s2/` 校验到 1e-12）。改 `backend_cadence.render_netlist` 或 `circuit.py` 后必须跑 `tests/test_repro_cadence_backend.py`。
