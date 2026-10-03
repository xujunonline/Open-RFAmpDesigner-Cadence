# Open-RFAmpDesigner-Cadence

基于 RFAmpDesigner 论文的 Cadence 版方法级复现工程。目标不是严格复现作者的 TSMC N65 数值结果，而是在可授权 Cadence/PDK 环境中复现其核心流程：

- 论文 Table I 的工具中间件接口；
- Table II/III 的变量范围和 LNA benchmark 规格；
- Stage 2/Stage 3 cost function；
- Python 调用 OCEAN/Spectre 的自动仿真闭环；
- Manager/Searcher/Refiner 多智能体调度框架；
- Table IV/V/VI-like 与 Fig. 7/8/9/10/11-like 的趋势级输出格式。

## 快速复现（无需 Cadence，2026-09-29 新增）

`src/orfadc/repro/` 提供与 Cadence 解耦的可运行复现：两端口噪声相关矩阵代理仿真器 + 论文 Table I 四个工具 +
Manager/Searcher/Refiner + KB/EB + GA/BO 基线 + Table IV/V、Fig.5/7/8/10-like 表图。结果为**趋势级**（surrogate），不是 PDK/硅结果。

```bash
python -m pip install -r config/requirements_repro.txt
export PYTHONPATH=src            # PowerShell: $env:PYTHONPATH="$PWD\src"
python -m pytest tests -q        # conftest 自动处理 basetemp
python -m orfadc.repro.bench smoke --out results/repro/smoke
python -m orfadc.repro.bench all --seeds 5 --out results/repro/latest
```

Claude Code 环境：`CLAUDE.md`、`.claude/`（settings、skills、subagents、commands、hooks）、`.mcp.json`（`rfamp` MCP 工具中间件）。
逐步手册 `docs/117_step_by_step_runbook.md`，提示词 `docs/118_claude_prompts.md`，审查 `docs/116_project_audit_2026-09-29.md`，结果 `docs/115_repro_surrogate_pipeline.md`。

## 当前边界

本仓库不包含任何 TSMC、Cadence 或商业 PDK 文件。`config/model_paths.yaml` 只提供本地路径占位符，真实路径必须由实验室授权环境配置，并且不应提交到公开仓库。

论文原文、中文翻译、论文插图和 arXiv 源文件统一保存在 `references/paper/`。从旧 Codex 对话任务迁移来的聊天记录和清单保存在 `docs/project_history/`，仅作为项目来源与决策追溯资料。

## 第一版 MVP

1. 使用 `config/specs_table_iii.yaml` 读取 10 个 LNA 规格。
2. 使用 `src/orfadc/tools/cost_functions.py` 复现论文公式 (1)(2)。
3. 使用 `src/orfadc/tools/*` 形成 Active sizing、Impedance matching、Band planning、Fullchain evaluation 的可调用接口。
4. 使用 `src/orfadc/cadence/*` 封装 OCEAN/Spectre 调用和 CSV/PSFASCII 结果解析。
5. 使用 `src/orfadc/agents/*` 提供 Manager/Searcher/Refiner 的确定性骨架，后续可接入 LLM。

## 快速检查

在没有 Cadence 的机器上也可以运行纯 Python 检查：

需要 Python 3.11+、PyYAML 和 pytest；教学结果 PNG 绘图另需 Pillow。在线 LLM 策略的 OpenAI SDK 是可选依赖，不参与离线测试。

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:ORFADC_RUN_LIVE_SSH_AUDIT = '0'
python -m pip install PyYAML pytest Pillow
python -m compileall src
python src\orfadc\experiments\run_spec.py --spec S1 --dry-run
$testRoot = "results/runs/pytest_offline_$(Get-Date -Format yyyyMMddTHHmmssfff)"
python -m pytest tests -q --basetemp=$testRoot
```

只收集项目 `tests/`；旧断线档的实时 SSH 审计默认跳过，须显式设置 `ORFADC_RUN_LIVE_SSH_AUDIT=1` 才会尝试联网。离线回归通过不等于该在线审计、Cadence 或物理 LNA 门禁通过；最新边界见 `docs/16_implementation_status.md`、`docs/113_stage10_incomplete_remote_quarantine.md` 与 `docs/114_stage10_remote_quarantine_fence.md`。

## 远程 Cadence 接口

OTA 项目中经过验证的 SSH、SCP、OCEAN 调用和 PSFASCII 解析能力已迁移为通用模块。配置和验证步骤见 `docs/ota_to_lna_migration_notes.md`；真实主机、用户、私钥和 Cadence 路径只能写入被 Git 忽略的 `config/remote_cadence.local.yaml`。

## 推荐阅读顺序

1. `docs/00_index.md`
2. `docs/open_rfampdesigner_cadence_full_plan.md`
3. `docs/open_rfampdesigner_cadence_design.md`
4. `config/specs_table_iii.yaml`
5. `src/orfadc/tools/cost_functions.py`
6. `src/orfadc/experiments/run_spec.py`
7. `references/paper/README.md`
8. `docs/project_history/README.md`

英文论文到工程的审查收尾见 `docs/audits/2026-09-26_audit_closure.md`，详细事实与问题见 `docs/audits/2026-09-25_paper_to_project_audit.md`，当前实施进度见 `docs/16_implementation_status.md`。审查工作已完成；项目实现仍有明确未关闭事项。

逐步自动实施请使用已按实测进度修订的 `docs/15_autonomous_completion_prompts.md`；`docs/10_detailed_prompts.md` 是历史提示词，不应直接作为当前起点。

2026-09-26 保持原 VM 配置完成 15 轮、约 16 分钟 SSH/Tools 检查和三次 OCEAN smoke，均通过；宿主可用内存最低约 2.66 GB。A09 仅在这次轻负载窗口内验收通过，长时/高负载任务仍需单独验证，见 `docs/18_ssh_recovery_from_ota.md`。

## 当前实机进度

- 被动 RF noise/NF 链路、公开教学 MOS1 单级/三级 OA、授权 PDK 诊断级 OA 与 DC/SP/noise/HB 均有 Spectre 原始档和只读审计；不是合格 LNA。详见 `docs/16_implementation_status.md`。
- 教学 Stage 2 已完成 random/PSO/SA/GA/BO 五 seed、每法四次，共 100 个真实 Spectre 点，并有逐层审计的比较 CSV 和诊断 PNG；详见 `docs/93_stage12_teaching_bo_five_method_multiseed.md`。BO 的可选环境见 `config/requirements_bo.txt`。
- 授权 PDK 器件的 CDF/PCell 参数传播、合法版图/DRC、可实现无源 Q/k/SRF、宽带匹配/稳定/增益/NF 和同候选大信号 fullchain 尚未同时通过。所有教学或失败诊断均 `not_lna_result=true`、`spec_pass=null`；不能填论文 Table IV/V 或 Fig. 7–11。
- 多智能体已有确定性 Manager/Searcher/Refiner 和受限可注入模型接口，但尚无获授权在线模型调用、合格 LNA 设计回合或论文级 self-evolution/消融结论。
