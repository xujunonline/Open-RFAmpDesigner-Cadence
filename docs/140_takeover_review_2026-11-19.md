# 140 接手准备与 Mac 运行核查（2026-11-19）

## 1. 审查对象、结论与本次工作范围

本次已完成论文与当前仓库的对照阅读、关键代码检查、离线回归、两条 S2 冒烟，以及存量实验数据重算。项目具备继续维护的代码与证据基础；下一步应先确认用户这台 Mac 的现有工作区和 Cadence 环境，再确定新的开发或实验目标。

| 项目 | 本次核实值 |
|---|---|
| 仓库 | `xujunonline/Open-RFAmpDesigner-Cadence` |
| 审查分支 | `main` |
| 源快照 HEAD | `f198922b9d912d2498088d0a6f0218c1462df8e1` |
| HEAD 内容 | 合并 PR #10：v2 实验报告与 crn40lp 通过数更正 |
| 已封版版本 | `v2.0`，2026-10-12；封版提交 `175b06e` |
| 论文 | 用户上传的 `RFAmpDesigner.pdf` 与 `references/paper/RFAmpDesigner.pdf` 字节一致 |
| 论文 SHA-256 | `5adf4e360ed5d340829f12e5b96ab56f25f364407f1bdbe2b15fb829f8fa7803` |
| 实际审阅环境 | 独立的 Linux x86_64 工作区；**不是用户的 Mac** |
| 本次真实 LLM / Spectre 调用 | 0 / 0 |
| 仓库修改 | 本文及 `docs/00_index.md` 索引；未修改 `src/`、已提交实验结果或私密配置 |

当前资料优先级为：`CLAUDE.md` 的封版状态、`docs/135_v2_reproduction_report.md`、`docs/139_experiment_report.md`、对应原始结果。`docs/134_macbook_handoff.md` 是 2026-10-06 开始迁移时的历史记录，后续有补注；其中“A3 未开始”“N0 未完成”“N65 预算 1500”、旧用户名和旧分支续接提示词均不能当作当前待办。当前 v2 已在 **macOS Intel** 上完成，A3、N0–N3 及补充实验均已收尾。[仓库依据：`CLAUDE.md` 第 11–15 行；docs/135 §5。]

README 将仓库标为私有。本文及后续开发继续按现有私有项目管理；本次没有提交、推送、发布或修改远程权限。

## 2. 论文方法与实现的对应关系

论文的核心任务是按给定频率、带宽、电流、增益、噪声和线性度约束自动设计三级射频低噪声放大器。实现将任务分成四个工具，由 Manager 协调 Searcher 与 Refiner，结合解析模型、数值优化和高保真校验；KB/EB 保存成功设计与经验，用于后续任务检索和初始化。

| 论文概念 | 当前实现入口 | 接手时要理解的行为 |
|---|---|---|
| 规格与变量范围，Table II/III | `config/specs_table_iii.yaml`、`config/variable_ranges_table_ii.yaml`、`schemas.py` | `power_ma` 表示电流预算；不要直接当 mW |
| Stage 1：尺寸与偏置 | `repro/tools.py::active_sizing`；`device.py::knowledge_database` | 按功率/电流分配选器件工作点和极端尺寸配置 |
| Stage 2：关键级匹配 | `repro/tools.py::impedance_matching`；`optim.py::pso` | 对噪声、输入匹配及可选增益要求做 PSO 搜索 |
| Stage 3：全链带宽与增益规划 | `repro/tools.py::band_planning`；`optim.py::simulated_annealing` | 优化第二、三级 MCR 参数，用高保真锚点修正解析增益模型 |
| Stage 4：全链判定 | `repro/tools.py::fullchain_evaluation`、`spec_check` | 汇总增益、纹波、S11、NF、IP1dB、电流并判定通过 |
| Eq. (1)/(2) 代价函数 | `tools/cost_functions.py::stage2_cost`、`stage3_cost` | 保留约束违反量；最终通过条件仍由 `spec_check` 决定 |
| Eq. (3) MCR 解析式 | `repro/mcr_eq3.py::eq3_voltage`；`circuit.py::map_mcr` | 默认 `corrected` 形式；项目按节点分析补足原式 Y11 分母缺失的 `s`，有独立测试支持 |
| Manager / Searcher / Refiner | `repro/agents_v2.py` 中同名 Agent 类 | v2 三者均由多轮 ReAct 驱动；Searcher/Refiner 每次新建会话 |
| KB / EB 自进化 | `repro/memory.py::MemoryStore` | JSONL 记录、相似规格检索、经验初始化；没有模型权重训练或微调 |
| GA / BO 对照 | `repro/baselines.py`、`optim.py` | 与项目的规格、成本模型和预算一起比较 |
| 实验、统计、图表 | `repro/bench.py`、`repro/figs_v2.py`、`scripts/report/` | 原始结果与派生报告分开，保持智能体版本和证据等级 |

上述 `repro/`、`tools/`、`schemas.py` 均相对于 `src/orfadc/`。更详细的论文映射见 docs/115、116、131、137。

### 2.1 v1、v2 与 scripted 的区别

- **v1**：程序控制主要流程；LLM 仅在功率分配和细化动作两个决策点参与。`bench.py::agent_impl` 默认仍为 v1。
- **v2**：Manager、Searcher、Refiner 自主选择工具和结束时机；连续错误或预算到达后终止，不改用规则策略继续。入口为 `agents_v2.py::run_design_v2`。
- **scripted**：用本地规则神谕模拟合法 LLM 回复，以验证 v2 协议、工具和记账。其 `llm_usage.calls` 是模拟传输调用次数，不能作为真实 LLM 能力或费用证据。

`bench smoke` 调用的是 v1；验证 v2 必须显式运行 `design --agent-impl v2 --policy scripted`，或在具体实验中选择真实 LLM 策略。`--agent-impl v2 --policy rule` 会报错。[代码依据：`bench.py` 第 72、470、964、982 行；`agents_v2.py::ScriptedReActTransport`；docs/131。]

### 2.2 三种仿真后端的证据等级

| `--backend` | 内循环与最终校验 | 证据边界 |
|---|---|---|
| `surrogate` | 本地开放 EKV 类器件与两端口噪声相关矩阵引擎 | 方法与趋势；不代表 PDK、版图后仿或硅结果 |
| `cadence` | 本地引擎优化，Stage 4 用 Spectre 解同一宏模型网表 | 交叉验证引擎与网表翻译；器件仍是代理模型 |
| `pdk` | 本地引擎使用 PDK 表征数据，Stage 4 用 Spectre RF MOS 与 HB | 当前为原理图级、理想无源、无版图寄生 |

`ORFADC_SPECTRE_ANCHORS=1` 可把 Stage 2 带内扫描和 Stage 3 校准锚点也交给 Spectre，但 PSO 内循环仍使用引擎。[代码依据：`backend_cadence.py::HybridBackend`；`tools.py::ToolContext.sim`；`pdk_v2.py::PdkCadenceBackend`。]

项目的等效 EDA 时间来自 `tools.py::EQUIV_COST_S`：关键级 0.5 s、全链 12 s、解析计算 0.002 s；S1–S8 默认 3600 s、S9/S10 默认 18000 s 等效预算。它与实际运行耗时、LLM 延迟和真实 Spectre 次数是不同指标，比较和作图时必须分列。

## 3. 已有成果与本次重算

本次运行 `scripts/report/make_report_tables.py`，把派生报告写入新的接手验收目录，没有覆盖 `results/report/`。读取并汇总了 174 份设计结果；N65 账本 143 行求和为 3144，与最后累计值一致。

| 实验 | 主要结果 | 证据等级及解释 |
|---|---|---|
| v1 Table IV-like | Ours 22/40；最佳基线 BO 11/40 | 代理，趋势级；见既有基线原始档与 docs/135 |
| crn40lp，v1 规则 | **29/40** | PDK 原理图级；旧 34/40 为加法错误，已在当前源快照更正 |
| N65 S1–S8，v1 规则 | **24/40** | PDK 原理图级，5 seed |
| N65 S1–S8，v2 + Codex | **21/40** | 同上；与 v1 双侧 Fisher 检验 p = 0.6525，不能据此宣称显著优劣 |
| S9s/S10s，v2 + Codex | **6/10**；v1 + Codex 0/10 | 代理缩放任务；不是论文原始 S9/S10 |
| N65 原始 S9/S10 | v1/v2 均为 S9 4/5、S10 0/5；v2 加跑 S10 后为 0/9 | 真实 PDK 原理图条件下，S10 尚未复现 |
| v2 自进化 | **18/18** | 代理，3 seed × 6 个任务；单个 seed 的六任务序列累计等效时间均值约 1292 s，18 个任务合计 3874.9 s；不能把 1292 s 写成全部 18 次总和 |
| N65 Spectre 总账 | **3144/3300** | 资源账本包含作废消耗；封版约定剩余次数不再使用 |

已有报告记载 v2 自进化成本相对 GA 低约 9.0 倍；这是当前代理模型及等效成本口径的趋势，不能直接换算成这台 Mac 的实际加速倍数。论文结果、原理图 PDK 结果、代理结果仍分别陈述。

本次重算文件位于 `results/runs/takeover_20261119/report/`，包括 `runs.csv`、`pass_totals.csv`、`pass_by_spec.csv`、`comparisons_fisher.csv`、`spectre_ledger_by_stage.csv`、`summary.json`。它们是现有证据的重算，没有新做 174 次设计或新调用 3144 次 Spectre。

## 4. 本次离线验收的实际记录

### 4.1 环境与测试

| 项目 | 此次 Linux 环境实测 |
|---|---|
| Python | 3.12.14 |
| NumPy / SciPy | 2.3.5 / 1.17.0 |
| PyYAML / Matplotlib | 6.0.3 / 3.10.8 |
| MCP / pytest | 1.29.0 / 9.2.0 |
| 环境组成 | 使用环境已有科学计算库，在独立 venv 中安装 pytest 做验证 |
| 全量离线回归 | **141 passed, 2 warnings in 69.48s，退出码 0** |

两个警告为依赖兼容提示：anyio 的 pytest 插件使用将于 pytest 10 删除的 `CallSpec2` 别名，以及 pydantic_settings 对 FastMCP `lifespan` 的未解析前向引用。没有测试断言失败。69.48 s 是这次 Linux 环境耗时；上述版本组合也只在此环境通过，**尚未在用户 Mac 上验收**。

### 4.2 S2 冒烟

| 指标 | v1 规则 + surrogate | v2 scripted + surrogate |
|---|---:|---:|
| `success` | true | true |
| 带内最小增益 / dB | 25.2704 | 25.6764 |
| 带内纹波 / dB | 2.0740 | 0.7164 |
| 中心频率 NF / dB | 4.1440 | 3.7954 |
| IP1dB / dBm | -22.5625 | -24.4661 |
| 电流 / mA | 28.3446 | 28.5795 |
| 等效 EDA 时间 / s | 1901.15 | 2035.79 |
| v2 终止原因 | 不适用 | `spec_met` |
| 真实 LLM 调用 | 0 | 0 |

v2 完成 66 次本地模拟传输调用：Manager 6、Searcher 30、Refiner 30；非法动作 0、传输错误 0。这两个冒烟的目的为运行完整性验收，不用于比较 v1 与真实 LLM v2 的研究效果。

原始文件：

- `results/runs/takeover_20261119/verification_summary.json`：本次源码、平台、依赖、测试、冒烟及零真实外部调用的汇总。
- `results/runs/takeover_20261119/smoke_v1/smoke_S2.json`
- `results/runs/takeover_20261119/smoke_v1/smoke_S2_trace.json`
- `results/runs/takeover_20261119/smoke_v2/design_S2_seed0_mode1_scripted_v2.json`

## 5. 在 Mac 上运行的安排

现有主控程序是 Python 科学计算、CLI/MCP 和 SSH/SCP，不依赖 CUDA 或 GPU 训练。README 要求 Python ≥3.11.4；依赖清单是 `config/requirements_repro.txt`。仓库已有 macOS/Linux 队列脚本，当前任务首先是恢复和验收环境。

| Mac 条件 | 可在 Mac 执行 | Spectre / PDK 的安排 |
|---|---|---|
| Intel Mac | Python、离线引擎、真实 LLM CLI、MCP、报告生成 | 检查原 x86_64 Linux VM 是否可启动；或通过 SSH 接已有 x86 Linux 主机 |
| Apple Silicon Mac | 同样的主控功能；需验证原生 Python 依赖与 CLI | 原 x86_64 `IC618_rf` VM 不能直接放进 Apple Silicon Fusion 运行；优先连接已有 x86 Linux 仿真主机 |

Broadcom 的官方 Fusion 说明确认 Apple Silicon 主机只支持 ARM64 客体，不支持 x86 操作系统。Cadence 的具体平台支持必须按产品与版本核实；Spectre 24.1 有专门 ARM 包，并不等于提供 macOS 原生 Spectre。当前旧 VM 与 PDK 路线无需为了 Mac 主控而迁到 ARM。[官方来源见 §8。]

此次尚未确认用户 Mac 的 CPU、macOS 版本、仓库路径、Python/CLI 状态、VM 状态、SSH 连通性或 PDK 缓存。因此本文中的“通过”仅指 §4 的 Linux 离线检查。

### 5.1 恢复项目需要的本地材料

用户应在自己的机器上恢复或确认以下材料，接手者只记录“存在/缺失/已核对”，不索取私钥、密码或凭据正文：

- 本地仓库及未提交改动；先保留现场，再对齐本次源快照。
- 按已有模板配置的 `config/remote_cadence.local.yaml` 和 `config/model_paths.local.yaml`。
- 有效 SSH 登录方式、可用的 Cadence/Spectre 环境和相应 PDK。
- 与目标工艺一致的完整表征缓存，包括器件表、Y3/Y2、噪声校准及需要的原始 PSF。
- 若继续自进化实验，需明确使用哪份 KB/EB，避免混入其他工艺、智能体版本或已用于评价任务的记忆。

这些材料多数被 Git 忽略，单独 clone 仓库不能恢复 PDK 实验环境。尤其 `pdk3.py::latest_multifreq_char` 会根据原始表征子目录读取实测两端口数据，仅拷一份 `device_table.json` 不一定足够。

## 6. 接手优先风险与可执行处理

以下代码位置均相对于本文源快照；本次只记录，没有修改实现。

| 优先级 | 已核实的问题 | 具体依据 | 下一步处理 |
|---|---|---|---|
| P0：恢复 PDK 前 | **表征数据可能跨工艺混用**：自动选表没有工艺身份筛选 | `pdk_v2.py::_tables` 第 716 行起，只按 Vds、拟合、行数、时间选表；`install_table` 第 773 行起按当前配置贴名称；`pdk3.py::install_y3` 第 196 行起自动选最新表 | 本次恢复只放一致的 N65 数据；后续增加显式表征 manifest 和 PDK/工艺角/配置指纹校验 |
| P0：新远程实验前 | **总 Spectre 预算没有代码全局原子守卫** | `spectre_ledger.csv` 为记录；源码中未消费该总账；`tools.py::ToolContext.sim` 第 114 行起只执行每设计限制 | 新实验先定次数预算、记账范围与并行数；不能仅设置每设计上限就认为总额受控 |
| P0：迁移时 | **旧 VM 网络脚本写死旧 MAC/IP 并重启网络** | `scripts/pin_vm_ip_mac.sh` 第 9–19 行 | 先核对本台 VM、网段和 Fusion 配置；历史脚本不能当通用初始化命令 |
| P1：验收入口 | **默认 v1 与 LLM 默认 200 次上限容易误用** | `bench.py::agent_impl` 第 72 行；`LLM_MAX_CALLS_DEFAULT` 第 69 行；docs/131 §6 | 在每条实验命令显式写实现、策略、后端、记忆路径及额度；封版实验的 1000 次设置不自动继承 |
| P1：可重复性 | **依赖和实际模型版本没有完整锁定** | `config/requirements_repro.txt` 多为下限；`llm_cli.py` 默认模型来自环境或 CLI 默认值；Mac 安装脚本下载 latest | Mac 离线通过后记录实际版本；真实实验固定并记录 CLI、模型、提示词修订、Git SHA 和环境摘要 |
| P1：桌面接入 | **MCP 使用裸 `python`，受桌面 PATH 影响** | `.mcp.json` 第 5、15 行；docs/134 §3 | 核对 MCP 实际使用的解释器；为本机配置正确 venv，先做协议连接检查 |
| P1：批量验收 | **队列结束不代表所有设计成功** | `run_job_queue.sh` 第 77–82 行记录错误后继续并写 DONE；并行脚本只统计 runner 失败 | 按设计 JSON 的 `success`、`terminated_reason` 与进程日志逐项汇总 |

固定 CLI 版本还不足以固定模型：`llm_cli.py` 第 242 行在未设置 `ORFADC_CODEX_MODEL` 时使用 `model=None`，第 166–177 行只有指定模型才向 Codex 传入 `-m`。新实验记录应包含实际生效的模型 ID、提示词版本与 `ORFADC_*` 开关，而不仅是命令行程序版本。

另需保持研究判断边界：N65 S5 的 v2 宽带匹配退步是已有具体问题，可先从历史轨迹和候选评估定位；现有数据未证明“增加预算即可解决”。S3/S6/S7/S10 的限制则与器件、噪声、匹配或无源条件有关，不能只归因于智能体推理不足。[docs/135 §4；docs/139 §9。]

## 7. 后续接管顺序与离线命令

### 7.1 接管顺序

1. 确认用户 Mac 上已有仓库的绝对路径、CPU 架构、Git 分支/HEAD/未提交改动。将本文源快照与本机状态对照，保留用户本地工作。
2. 确认 Python ≥3.11.4，建立或核对项目 venv；执行下面离线验收，在新的输出目录保存记录。
3. 确认实际 LLM CLI 路径、版本、模型选择和登录状态；若新任务需要真实 LLM，再定义一个小规模试运行及调用上限。
4. 用户在本机恢复私密配置与匹配工艺的完整缓存；核对原 Linux VM/主机与表征数据身份。开始 PDK 实验前解决 §6 的数据选择与预算问题。
5. 为新工作指定一个具体目标，例如定位 N65 S5 的宽带匹配退步、增加工艺身份校验、验证一项新的 Refiner 策略；冻结对照与评价口径后再准备实验队列。

准备接手的阶段已经可以完成离线步骤。真正调用远程 Cadence/Spectre 或启动批量真实 LLM，需要用户指定新的实验任务与资源预算：`CLAUDE.md` 第 12、62–65 行规定旧 N65 账本剩余次数不再使用，远程操作需事先明确次数与护栏。旧封版批准不当作新实验额度。

### 7.2 在已确认的 Mac 仓库根目录执行

先核对解释器版本；若已有 `.venv`，检查后复用。缺失时再建立并安装依赖：

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r config/requirements_repro.txt
```

以下验收命令不需要真实 LLM 或 Cadence。每次生成新的时间戳目录，避免覆盖旧基线：

```bash
export PYTHONPATH="$PWD/src"
takeover_out="results/runs/takeover_$(date +%Y%m%dT%H%M%S)"
mkdir -p "$takeover_out"

.venv/bin/python -m pytest tests -q \
  --basetemp "$takeover_out/pytest"

.venv/bin/python -m orfadc.repro.bench smoke \
  --out "$takeover_out/smoke_v1"

.venv/bin/python -m orfadc.repro.bench design \
  --spec S2 --seed 0 \
  --agent-impl v2 --policy scripted --backend surrogate \
  --out "$takeover_out/smoke_v2"

.venv/bin/python scripts/report/make_report_tables.py \
  --out "$takeover_out/report"
```

运行前应核对是否保留了旧的 `ORFADC_*` 实验环境变量；预算、无源 Q、提示词修订和记忆设置都会改变结果。验收判据为：全量回归无失败、两条 S2 的 `success=true`、v2 无非法动作/传输错误、重算账本一致。以本机实际测试记录作为后续 Mac 环境基线。

本次记录只把代码阅读、已有成果核对与离线验收推进到可接手状态；用户 Mac 的运行验收、真实 LLM 通道和远程 PDK 链路仍需在对应环境完成。

## 8. 参考与证据入口

### 仓库与论文

- `references/paper/RFAmpDesigner.pdf`：与用户上传论文相同，SHA-256 见 §1。
- `README.md`、`CLAUDE.md`：复现边界、封版状态、资源与私密配置规则。
- `docs/131_agent_v2_design.md`：v1/v2 差异、论文对应、离线 scripted 的解释。
- `docs/134_macbook_handoff.md`：历史 Mac 迁移与故障记录，须结合最新状态阅读。
- `docs/135_v2_reproduction_report.md`、`docs/139_experiment_report.md`：结论、未复现项、统计与资源口径。
- `results/repro/`：已提交原始实验档；`results/repro/n65/spectre_ledger.csv`：N65 总账。
- `results/runs/takeover_20261119/`：本次离线冒烟与重算证据，属于 Git 忽略的本地验收目录。

### 官方平台资料（本次由主审实际打开核对）

1. [Cadence Computing Platform Support Roadmap 2024–2027](https://www.cadence.com/en_US/home/support/computing-platform-support/support-road-map-2024x-2027x.html)：平台支持以具体产品、版本为准；该路线图未列 macOS。
2. [Cadence Spectre 24.1 Release](https://community.cadence.com/cadence_blogs_8/b/cic/posts/spectre-24-1-release-is-now-available)：24.1 的 ARM 专用包不等于 macOS 原生支持，也不自动解决旧 x86 VM/PDK 的迁移。
3. [Broadcom：Compatibility considerations for Arm guest operating systems in Fusion VMs on Apple silicon](https://knowledge.broadcom.com/external/article/315602/compatibility-considerations-for-arm-guest.html)：Apple Silicon Fusion 的 ARM64 客体与 x86 客体限制。
