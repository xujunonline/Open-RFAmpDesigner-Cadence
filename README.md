# Open-RFAmpDesigner-Cadence

RFAmpDesigner（arXiv:2605.10093，*A Self-Evolving Multi-Agent LLM Framework for Automated RF Amplifier Design*）的方法级复现。
目标是复现论文的**流程与趋势**（多保真工具中间件、Manager/Searcher/Refiner、KB/EB 自进化、Table IV/V、Fig. 5/7/8/10），
不是作者 TSMC N65 后仿的数值。

- 版本：v1 = 标签 `v1-decision-points`（提交 e80dfd3）；v1.1 = 标签 `v1.1-clean`（docs/129）；
  **v2 = 分支 `v2-agentic`**（标签 `v2-agentic-alpha`）：LLM 驱动的 ReAct 三智能体（docs/131），以及迁移到 TSMC N65 PDK（docs/132、133）。
- 远程仓库：GitHub 私有仓库 `xujunonline/Open-RFAmpDesigner-Cadence`（含论文全文与 PDK 相关信息，**必须保持私有**）。

## 复现了什么（证据分级，详见 docs/125）

| 证据 | 内容 | 主要结论 |
|---|---|---|
| 代理（趋势级） | 开放 EKV 类器件 + 两端口噪声相关矩阵引擎 | Table IV-like：Ours 22/40，最佳基线 BO-vanilla 11/40；Fig. 5 多保真省时 −99 %；Fig. 10 自进化 18/18 |
| Spectre 宏模型 | 同一网表在 Spectre 上交叉验证引擎 | 增益/S11/NF 逐点一致（只验证引擎） |
| 示意 PDK | TSMC 40 nm LP RF 器件 + 理想无源 + HB，Stage 4 由 Spectre 判定 | 论文口径（1 h、5 seed）pass@1 **34/40**（论文 Ours 32/40）；S6、S7 0/5 |
| LLM 主干 | 订阅额度的 Claude / Codex（智能体实现 v1：Searcher 为程序，LLM 只在 Manager 选功率分配与 Refiner 选动作两处决策） | Table V 未复现：Codex 不封顶 S9s/S10s 违规 0.46/0.61，规则 0.22/0.28 |
| **v2 智能体（代理，趋势级）** | 三个智能体都由 LLM 以 ReAct 方式驱动（docs/131），Codex，与 v1 同口径（S9s/S10s、5 h、5 seed） | **6/10 通过**（v1 + Codex 0/10，v1 规则 0/10）；失败的 4 次 NF 只差 0.14–0.47 dB（docs/133 §3） |
| **N65 示意 PDK** | TSMC 65 nm LP RF（CRN65LP v1.7）器件 + 理想无源 + HB，原理图级，Stage 4 由 Spectre 判定 | 论文口径（1 h、5 seed）pass@1：**v1 规则 24/40**，**v2 + Codex 21/40**（差在 S5）；与 crn40lp 34/40 的差距全在 S3（50 GHz 下器件受限）（docs/132、133） |

以上均**不是**论文 N65 后仿或硅结果，不填论文 Table IV/V/VI 的"实测"位置。

## 快速开始（无需 Cadence）

```bash
python -m pip install -r config/requirements_repro.txt      # Python ≥ 3.11.4
export PYTHONPATH=src                                       # PowerShell: $env:PYTHONPATH="$PWD\src"
python -m pytest tests -q                                   # 离线回归
python -m orfadc.repro.bench smoke --out results/repro/smoke
python -m orfadc.repro.bench replot --out results/repro/2026-10-03   # 从原始档重建表图
```

完整命令、LLM 主干与 Cadence/PDK 后端的用法见 `CLAUDE.md` 与 `docs/117_step_by_step_runbook.md`。

## 目录

- `src/orfadc/repro/`：引擎、Table I 工具、智能体、LLM 策略、bench、MCP 服务器、Cadence/PDK 后端（`backend_cadence.py`、`pdk_v2.py`、`pdk3.py`、`pdk_fit.py`）。
- `src/orfadc/{schemas,config_loader}.py`、`src/orfadc/cadence/{psfascii_reader,remote_runner}.py`、`src/orfadc/tools/{cost_functions,mcr_lumped}.py`：复现依赖的少量公共模块。
- `config/`：Table II/III、依赖清单、远程与 PDK 配置模板（真实配置为 git 忽略的 `*.local.yaml`）。
- `tests/`：离线回归（含独立 MNA 解算器 `tests/fakes/mna_spectre.py`）。
- `scripts/`：作业队列与检查脚本（Windows `.cmd/.ps1`；macOS/Linux `run_job_queue.sh`、`run_job_queues_parallel.sh`、`setup_llm_cli_mac.sh`）。
- `.claude/`、`.mcp.json`：Claude Code 配置（skills、subagents、commands、hooks、MCP）。
- `references/paper/`：论文原文、中文翻译、插图与 arXiv 源文件。
- `docs/`：见 `docs/00_index.md`。

## 结果在哪里

- `results/repro/2026-10-03/`：代理基线（SUMMARY、tables、figures、raw）。
- `results/repro/pdk_pass_at1_20261002/`：示意 PDK pass@1 汇总（只含指标，不含 PDK 器件数据）。
- `results/repro/llm_live/`：LLM 主干运行与汇总；`results/repro/ablation_backoff_20261002/`：B21 消融。
- `results/repro/n65/`：N65 的 v1 冒烟与基线（N2、N3）及 Spectre 账本；`results/repro/v2_a3/`：v2 的 LLM 运行（冒烟、S9s/S10s、N65）。
- 含 PDK 器件参数的原始数据只放在 git 忽略的 `results/runs/`、`results/windows_checks/`。

## 边界与保密

- 本仓库不包含任何 TSMC、Cadence 或商业 PDK 文件；`config/*.example.yaml` 只是模板。
- 时间为等效 EDA 时间（成本模型），只做相对比较；Spectre 总量上限（crn40lp 约 1000，已用约 697；N65 另记 1500）与 40 次 LLM 封顶是资源保护，不是论文设置（docs/127、130）。
- 新虚拟机 IC618_rf 上为 TSMC 65 nm LP RF（CRN65LP v1.7），v2 的 N65 结果全部是原理图级、理想无源、无版图寄生（docs/128、132）。
- 路线 B（Virtuoso/OCEAN 实机链路、教学电路、远程恢复）的历史代码与文档已在 v1.1 删除，可从标签找回（docs/LEGACY.md）。
- 第三方参考见 `third_party_notes/README.md`。
