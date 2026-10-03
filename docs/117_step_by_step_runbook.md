# 117 逐步自主运行手册（路线 A：可运行复现；路线 B：接入 Cadence）

目标：任何一台装有 Python 3.10+ 的机器（Windows/Linux/macOS），不依赖 Cadence、PDK 或网络，
按步骤复现论文的方法级结果；再按同一接口把仿真后端切换为 Cadence Spectre。
每一步都给出**命令、预期输出、通过判据、失败处理**，可由人或 Claude Code 逐步自主执行。

---

## 阶段 0：环境

| 步骤 | 命令（仓库根目录） | 通过判据 |
|---|---|---|
| 0.1 | `python --version` | ≥ 3.10 |
| 0.2 | `python -m pip install -r config/requirements_repro.txt` | 无报错（`mcp` 可选） |
| 0.3 | Linux: `export PYTHONPATH=src`；PowerShell: `$env:PYTHONPATH="$PWD\src"` | — |
| 0.4 | `python -m compileall -q src` | 退出码 0 |

失败处理：没有网络时可离线安装 wheel；`mcp` 装不上不影响阶段 1–4，只影响 MCP 服务器。

## 阶段 1：回归测试

| 步骤 | 命令 | 通过判据 |
|---|---|---|
| 1.1 | `python -m pytest tests/test_repro_core.py -q` | `14 passed` |
| 1.2 | `python -m pytest tests -q` | 全部 passed（大量 `skipped` 是缺私有 Cadence 原始档，正常） |

`tests/conftest.py` 已自动设置 `--basetemp=results/runs/pytest_*` 与 `ORFADC_RUN_LIVE_SSH_AUDIT=0`。

## 阶段 2：单点冒烟（≈10 s）

```bash
python -m orfadc.repro.bench smoke --out results/repro/smoke
```

预期：打印 `"success": true`、S2 指标（最小带内增益 22–28 dB、纹波 ≤3 dB、NF@30 GHz ≤5 dB、
IP1dB ≥ −25 dBm、功耗 ≤30 mA）。`results/repro/smoke/smoke_S2_trace.json` 是完整智能体轨迹
（manager/searcher/refiner 的 plan → tool → decide → evaluate）。

## 阶段 3：分步手动走一遍论文工作流（理解用）

```bash
python -m orfadc.repro.bench design --spec S1 --seed 0 --policy rule --out results/repro/manual
```

或在 Python 中逐个调用 Table I 工具：

```python
from pathlib import Path
from orfadc.config_loader import load_specs
from orfadc.repro import tools as T
spec = {s.id: s for s in load_specs(Path("config/specs_table_iii.yaml"))}["S2"]
ctx = T.ToolContext(spec)
act = T.active_sizing([0.4, 0.3, 0.3], spec.power_ma)          # Stage 1
cfg = act["active_params_dict_list"][0]
s2 = T.impedance_matching(ctx, cfg, gain_require_db=17)       # Stage 2 (PSO + L-match, Eq.1)
s3 = T.band_planning(ctx, cfg, s2)                             # Stage 3 (SA + Eq.3 + calibration, Eq.2)
fc = T.fullchain_evaluation(ctx, s3["_design"])                # Stage 4
print(fc["sim_results_dict"], fc["spec_check"], ctx.counter.to_dict())
```

## 阶段 4：复现论文表图

| 步骤 | 命令 | 产物 | 对应论文 |
|---|---|---|---|
| 4.1 | `python -m orfadc.repro.bench fig5 --out results/repro/latest` | `figures/fig5_like.png`、`raw/fig5.json` | Fig. 5a/5b、Eq.(3) |
| 4.2 | `python -m orfadc.repro.bench table4 --seeds 5 --out results/repro/latest` | `tables/table4_like.{md,csv}`、`figures/fig7_like.png`、`fig8_like.png` | Table IV、Fig. 7、Fig. 8 |
| 4.3 | `python -m orfadc.repro.bench table5 --seeds 5 --out results/repro/latest` | `tables/table5_like.*` | Table V（规则策略下的消融） |
| 4.4 | `python -m orfadc.repro.bench fig10 --seeds 3 --out results/repro/latest` | `figures/fig10_like.png`、`raw/fig10.json` | Fig. 10（自进化） |
| 4.5 | `python -m orfadc.repro.bench all --seeds 5 --out results/repro/<日期>` | 以上全部 + `SUMMARY.md` | — |

耗时参考（2 核）：fig5 < 1 min；table4 ≈ 35 min；table5 ≈ 40 min；fig10 ≈ 10 min。已有原始档时 `bench replot` 秒级重建表图。
基线结果：`results/repro/2026-10-03/`（v1 封版时用当前代码重跑；旧版 `results/repro/2026-09-29/` 保留作历史对照），解读见 `docs/115` §6。
`--workers N` 控制并行进程数。

通过判据：`SUMMARY.md` 中每个数字都能由 `raw/*.jsonl` 重算（用 `repro-verifier` 子智能体或
`docs/118` 的核验提示词）；成功运行的 metrics 必须满足对应 spec。

## 阶段 5：LLM 主干（可选，对应 Table V/VI 的 backbone 实验）

**推荐：订阅额度，无需 API key**（详见 `docs/119`）：先 `claude auth login --claudeai` / `codex login`，再
`python -m orfadc.repro.bench llm-check --policy claude-cli|codex-mcp`，通过后 `bench design --spec S9 --policy claude-cli`。
`ORFADC_LLM_MAX_CALLS` 限制每次运行的调用数；额度用尽会自动熔断回退规则策略。**论文口径不封顶**：设 `ORFADC_LLM_MAX_CALLS=1000`，只受 5 h 等效预算约束（docs/127）；40 次封顶只是额度保护。Windows 一键联调：`scripts\windows_llm_cadence_check.ps1`。

以下为 API key 方式（可选）：

```bash
# Claude
export ANTHROPIC_API_KEY=...; export ORFADC_LLM_MODEL=claude-sonnet-4-5
python -m orfadc.repro.bench design --spec S9 --policy anthropic --out results/repro/llm
# OpenAI 兼容（DeepSeek、Qwen、vLLM 等）
export OPENAI_API_KEY=...; export OPENAI_BASE_URL=https://api.deepseek.com/v1; export ORFADC_LLM_MODEL=deepseek-chat
python -m orfadc.repro.bench design --spec S9 --policy openai --out results/repro/llm
```

输出含 `llm_usage`（调用次数、prompt/completion tokens、回退次数、延迟）与 `llm_log`。
无效输出自动回退到规则策略并计数，不会污染设计。离线等价物：`--policy scripted`。

## 阶段 6：在 Claude Code 中自主运行

1. 在仓库根目录启动 Claude Code；`/mcp` 应显示 `rfamp` 已连接（首次会询问是否信任 `.mcp.json`）。
2. `/repro-smoke` → 冒烟；`/repro-all 5` → 全量复现 + 核验 + 写文档；
   `/design-lna S5` 或 `/design-lna "fc=28GHz fbw=25% I=30mA G=24dB NF<4.5 IP1dB>-22"` → Claude 亲自担任 RFAmpManager。
3. 长任务提示词见 `docs/118_claude_prompts.md` §1（总控）。

## 阶段 7：切换到 Cadence（路线 B 汇合点）

**v1 已实现**（`repro/backend_cadence.py`，见 `docs/119`）：`bench cadence-check --spec S2` 用 Spectre 宏模型交叉验证两端口引擎；
`bench design --backend cadence` 让 Stage 4 全链评估走 Spectre。必须在能 SSH 到 Cadence 虚拟机的 Windows 宿主上运行。
以下为 v2（PDK 器件）步骤：

1. 按 `.claude/skills/cadence-backend-bridge/SKILL.md` 实现 `CadenceBackend`（同一 `simulate()` 返回结构）。
2. 用 OCEAN 扫描替换 `device.knowledge_database()`（论文 Sec. II-A 网格）。
3. 先 Stage 2 关键级单点 → 再 Stage 4 全链 → 与代理趋势对比 → 标定 `EQUIV_COST_S` 为实测秒数。
4. 远程规则：`docs/113`、`docs/114` 的隔离/预算/不重派发约束保持有效；live SSH 需用户明确授权。

### 7.1 论文口径的 PDK 运行（docs/122–127）

| 目的 | 命令 / 开关 | 说明 |
|---|---|---|
| PDK 器件表征 | `bench pdk-characterize`、`pdk-characterize3`、`pdk-characterize-casc` | 结果放 git 忽略的 `results/runs/` |
| 单设计（Spectre 判定） | `bench design --spec S5 --seed 1 --policy rule --backend pdk` | 默认报告违规最小候选（`ORFADC_REPORT_BEST=1`） |
| 每设计 Spectre 护栏 | `ORFADC_SPECTRE_MAX_PER_DESIGN=60` | 论文无此上限；1 h 预算下实测单设计 ≤ 38 次 |
| 无源 Q 敏感度 | `ORFADC_Q_MATCH`（默认 25）、`ORFADC_Q_IND`（默认 15） | 非默认值会给输出文件名加 `_qm*_qi*` 后缀 |
| 加大预算 | `ORFADC_BUDGET_SCALE`（默认 1） | 非 1 时文件名加 `_b*x`；超出论文口径，须单独标注 |
| 批量（Windows） | 编辑 `scripts/jobs/queue.txt`，双击 `scripts/run_job_queue.cmd` | 支持 `set ORFADC_*=` 行；日志在 `results\windows_checks\<ts>_job\` |

论文口径汇总：S1–S8 每规格 5 seed、1 h 等效预算、规则策略 → pass@1（docs/127 §5）；S9s/S10s 5 seed、5 h、LLM 不封顶（docs/119 §4.3）。
远程 Spectre 总量：用户批准的上限见 docs/127（当前约 1000）。

## 常见问题

| 现象 | 原因/处理 |
|---|---|
| `ModuleNotFoundError: orfadc` | 未设置 `PYTHONPATH=src` |
| `pytest` 9 个失败，提示 `results/runs root` | 旧版无 `tests/conftest.py`；更新后直接运行即可 |
| MCP 未连接 | `python src/orfadc/repro/mcp_server.py` 手动运行看报错；多为缺 `mcp` 包 |
| 表格某列全 `0/5` | 在代理模型上该方法确实在预算内失败；看 `raw/*.jsonl` 中 `violations`/`bottleneck` |
| 想更难/更易 | 调 `repro/device.py: TechParams`、`repro/circuit.py: Q_IND/Q_MATCH`，并在文档记录 |
