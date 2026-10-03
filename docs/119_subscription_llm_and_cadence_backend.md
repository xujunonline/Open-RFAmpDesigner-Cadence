# 119 订阅额度 LLM 主干（Claude Pro / ChatGPT）与 Cadence 后端接入

日期：2026-09-29。本文件记录方案、实现、调试证据与运行方法；测试结论在 §5 持续更新。

## 1. 方案总览

| 通道 | 调用链 | 额度来源 | 代码 |
|---|---|---|---|
| `--policy claude-cli` | LLMPolicy → `claude -p --output-format json`（Claude Code 无头模式） | Claude Pro/Max 订阅（`claude auth login --claudeai`） | `repro/llm_cli.py::ClaudeCLITransport` |
| `--policy codex-mcp` | LLMPolicy → **MCP(stdio)** → `codex-bridge` 服务器 → `codex exec --json` | ChatGPT 订阅（`codex login`） | `repro/llm_cli.py::CodexMCPTransport`、`repro/codex_mcp_server.py` |
| Claude Code 交互 | Claude Code 通过 `.mcp.json` 的 `rfamp`（设计工具）+ `codex`（ChatGPT 第二意见）两个 MCP 服务器 | 两个订阅 | `.mcp.json`、`.claude/settings.json` |
| `--backend cadence` | Stage 2/3 内环用代理引擎，Stage 4 全链评估走远程 Spectre（论文多保真分工） | Cadence 许可证 | `repro/backend_cadence.py::HybridBackend` |

要点与约束：

- **不用 API key。** 两个 CLI 子进程都会去掉 `ANTHROPIC_API_KEY/OPENAI_API_KEY`，保证走订阅；`claude -p` 不加 `--bare`（`--bare` 只认 API key）。
- **Codex 自带的 `codex mcp-server` 已在 0.154 移除**（上游 PR #42993），因此提供 `codex-bridge`：一个 FastMCP 服务器，工具 `codex_ask`/`codex_status`，内部调用只读、临时、跳过 git 检查的 `codex exec`。
- **额度保护：** `ORFADC_LLM_MAX_CALLS`（默认 200）上限；连续 3 次传输错误（额度用尽/未登录/断网）自动熔断，回退规则策略继续跑，`llm_usage.disabled_reason` 记录原因。
- **Windows：** npm 的 `claude.cmd`/`codex.cmd` 垫片会被解析为 `node <cli.js>` 直接执行，避开 cmd.exe 对空参数、中文路径的二次解析；系统提示词走 `--system-prompt-file`，用户消息走 stdin。
- **费用口径：** 订阅不按次计费；`notional_cost_usd` 仅为 CLI 报告的标价估算，不能填论文 Table VI 的美元成本。

## 2. Cadence 后端 v1（Spectre 宏模型）

`render_netlist()` 把 `circuit._chain` 的每个模块写成 Spectre 理想元件：有损电感、`mutual_inductor` 耦合谐振器、
50 Ω 输入 port、RL port + CL；晶体管用与 Stage-1 知识库**同一个** `DeviceOP` 的小信号宏模型
（vccs gm、无噪 gds、Cgs/Cgd/Cdb、有噪 Rg），并用"短路噪声电阻 + 电流镜 + 电容微分器"实现
van der Ziel 沟道噪声、感应栅噪声及其 0.395j 相关。分析：`sp`（S 参数 + 二端口噪声，290 K）和 `ac`（内部节点传函，
用于压缩点估计）。经 `RemoteRunner` SSH/SCP 执行，每次仿真在 `results/runs/repro_cadence/<run>/simNNNNN/` 留存
netlist、PSF 原始档与 metrics。

它的意义是**用商用仿真器独立复核 Python 两端口引擎**（S21/S11/NF/NFmin/节点传函），并把"SSH → Spectre → 解析 → 智能体"
整条链路跑通；它**不是** PDK 晶体管级结果（器件非线性与版图寄生不在范围内），输出一律 `not_lna_result=true`。
v2 计划：`device_card` 钩子换成 PDK 器件实例，并用 OCEAN 扫描重建 Stage-1 知识库（见 skill `cadence-backend-bridge`）。

`bench cadence-check` 的判据：同一设计在 Spectre 与引擎之间，增益 ≤0.2 dB、S11 ≤1 dB、NF ≤0.2 dB、NFmin ≤0.3 dB、IP1dB 估计 ≤0.5 dB。

## 3. 离线验证（已完成）

- `tests/test_repro_llm_cli.py`（8 项）：假 `claude`/`codex` 可执行文件，验证 JSON/JSONL 解析、API key 剥离、
  MCP 桥端到端（列工具 + 调用）、额度错误 → TransportError、熔断后规则策略仍能解 S2。
- `tests/test_repro_cadence_backend.py`（3 项）：网表格式（实例名唯一、端口、分析语句、纯 ASCII）；
  假远程 runner 以 PSFASCII 格式回写引擎结果，验证上传/运行/下载/解析/归一化与引擎逐点一致；HybridBackend 把 Stage 4 路由到 Cadence。
- 全量回归：733 passed, 382 skipped（2026-10-01 增加真实 Spectre 夹具与 MNA 独立解算器后，`tests/test_repro_cadence_backend.py` 为 7 项）。

## 4. 在线验证

| 项目 | 环境 | 结果 |
|---|---|---|
| `claude -p` 实参与 JSON 结构 | 云端工作区真实 Claude Code 2.1.284 | ✅ `llm-check`：ping 返回 OK；Refiner 决策由模型给出且通过校验（将 stage2 增益 9.5→5.5 dB、stage3 提到 ~16 dB 以解决 stage3 电流削顶），单次约 1.5 万 prompt token（其中约 1.36 万为 CLI 固定上下文） |
| S9 seed 0，`--policy claude-cli`（40 次调用上限） | 云端真实 Claude Code | 40 次决策全部合法解析（Refiner 35、Manager 5）；1 次被模型安全分类器误拦（已加"换 opus 重试一次"）；结果未过：IP1dB −17.6 dBm（规则策略最好 −16.0）、NF 7.1 dB；约 61 万 prompt token（CLI 固定上下文占大头） |
| S10 seed 0，`--policy claude-cli`（40 次） | 云端真实 Claude Code | 40 次决策；3 次安全分类器误拦；未过：IP1dB −16.3 dBm、NF 9.0 dB（要求 ≤3.5）——LLM 优先追线性度而牺牲噪声；S9/S10 在代理器件上本就不可行（GA 2 万次前沿 −19.7 dBm），此结果只说明链路可用 |
| Windows 第 1 轮（2026-10-01 14:32） | 你的 Windows | Claude：`claude auth status` = Pro、ping OK；Refiner 决策被 Opus 的 `reasoning_extraction` 安全分类器拦截 → 根因是提示词要求输出 `<think>` 推理，已改为一句话 `<rationale>`，云端 Sonnet/Opus 复测均通过。Codex：0.159.2 已用 ChatGPT 登录（`.codex-cli`），但 `mcp` 包因 `requirements_repro.txt` 含非 ASCII 字符在 GBK 下安装失败 → 已改为纯 ASCII 并在脚本里加 `PYTHONUTF8=1` 与依赖自检。Cadence：SSH 192.168.44.128:22 连接超时（虚拟机未开机或 IP 变化），脚本已加端口预检提示。日志改为 UTF-8。 |
| Windows 第 2 轮（2026-10-01 15:14，`run_all_windows`） | 你的 Windows（Claude Code 2.1.285 Pro；codex-cli 0.159.2） | Claude：`llm-check` ok，Refiner 决策由模型给出并通过校验（`<rationale>` 格式不再被拦）。Codex：脚本装到了 **mcp 2.x**（FastMCP 改名为 MCPServer）→ 桥接服务器启动即退出；已把依赖钉为 `mcp>=1.2,<2` 并加清晰报错，跟进脚本 `run_codex_followup` 装回 mcp 1.30 后 `llm-check --policy codex-mcp` **ok**（ping 20 s；Refiner 决策合法，约 1.6 万 prompt token 其中 1.25 万缓存）。 |
| Spectre 宏模型 cross-check（S2） | Windows → 192.168.44.128，Spectre 25.1.0 | SSH/上传/Spectre/下载/解析全链路打通（每次 ~38 s，其中许可证 ~1.7 s）。第 1 次运行发现两处问题并修复：①频率网格含重复带边点，Spectre 自动去重 → 解析报"网格不一致"；现按 12 位有效数字去重仿真、再映射回请求网格。②实测差异：中心频点增益 −0.44 dB、NF +0.26 dB、S11 −22.7 vs −39.6 dB。用独立 MNA 解算器（`tests/fakes/mna_spectre.py`，与引擎零共享代码）复算真实网表，S/NF/NFmin/节点电压与 Spectre **相对误差 <1e-12**；逐节点对比定位到唯一差异：引擎把源极电感加在 CS 管 Y 矩阵公共端，等效把第一级 **Cdb 接到源极**，网表按物理接地。网表默认改为与引擎同拓扑（`physical_cdb=False`），复算差异 <1e-9 dB；物理接法作为 `sensitivity_physical_cdb` 一并报告（见 docs/120 §4）。真实 PSF 已存为 `tests/data/spectre_s2/` 回归夹具。 |
| 第 2 轮 Spectre 复跑与 `design --spec S2 --backend cadence` | 同上 | ✅ `cadence-check` **agree=true**：3 次 Spectre（24.6 s），关键级与全链的增益/S11/NF/NFmin 与引擎最大差 ≤5e-10 dB，IP1dB 估计差 0.31/0.19 dB（≤0.5）。`design --spec S2 --backend cadence`：Stage 4 的 11 次全链评估全部由 Spectre 给出，最终 **通过 S2**（增益 25.3–27.3 dB、NF 4.14 dB、S11 ≤ −23.8 dB、IP1dB −22.4 dBm、28.3 mA），2 min 墙钟。详见 §4.1。 |
| LLM 主干 S9/S10/S9s/S10s × {rule, claude-cli, codex-mcp} | 你的 Windows | ✅ 12 次设计运行全部跑完，见 §4.1 |

### 4.1 Windows 第 2 轮结果（2026-10-01，seed 0，`ORFADC_LLM_MAX_CALLS=40`）

原始档：`results/repro/llm_live/windows_20261001/`（设计 JSON 含 `llm_log` 每次模型回复；`llm_table.md` 由 `bench llm-table` 生成），
Windows 侧完整日志在 `results\windows_checks\20261001T151401_all\`。仿真器为代理引擎（S2 行 Stage 4 为 Spectre），结论均为趋势级。

| spec | 策略 | 通过 | 残余违规 Σ | IP1dB (dBm) | NF (dB) | 最小增益 (dB) | LLM 调用 | 非法/失败 | 封顶后规则决策 | prompt tok | 模型时延 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S9 | rule | N | 2.63 | −16.3 | 6.98 | 22.1 | – | – | – | – | – |
| S9 | Claude（Pro） | N | 2.36 | −18.3 | 6.25 | 23.5 | 12 | 0 | 0 | 26.7k | 209 |
| S9 | ChatGPT/Codex | N | **1.99** | −15.9 | 6.70 | 22.7 | 40 | 0 | 89 | 633k | 872 |
| S10 | rule | N | 3.24 | −22.7 | 4.18 | 24.0 | – | – | – | – | – |
| S10 | Claude（Pro） | N | **2.83** | −21.5 | 4.14 | 23.2 | 19 | 0 | 0 | 36.1k | 287 |
| S10 | ChatGPT/Codex | N | 3.72 | −21.2 | 5.17 | 22.9 | 40 | 0 | 51 | 633k | 894 |
| S9s | rule | N | **0.27** | −20.3 | 5.16 | 24.3 | – | – | – | – | – |
| S9s | Claude（Pro） | N | 1.48 | −23.0 | 5.48 | 25.6 | 40 | 0 | 0 | 91.0k | 747 |
| S9s | ChatGPT/Codex | N | 0.96 | −22.9 | 4.88 | 25.5 | 40 | 0 | 0 | 632k | 801 |
| S10s | rule | N | 0.81 | −21.3 | 4.71 | 23.7 | – | – | – | – | – |
| S10s | Claude（Pro） | N | 1.37 | −21.1 | 5.32 | 23.4 | 40 | 0 | 79 | 88.3k | 734 |
| S10s | ChatGPT/Codex | N | **0.68** | −21.3 | 4.58 | 25.2 | 40 | 0 | 71 | 633k | 815 |

读法与结论：

- **两条订阅通道都可用于整段设计循环。** 共 271 次模型决策（Claude 111、Codex 160），**0 次非法输出、0 次传输错误、0 次安全拦截**（`<rationale>` 改法生效）；
  早先表里的大"fallbacks"数是封顶 40 次后由规则策略接手的决策，现已拆成 `rule-after-cap` 单独计数（`llm.py::Usage.rule_after_disable`）。
- **单 seed 不足以排名。** 残余违规（越小越接近规格）LLM 在 S9（Codex）、S10（Claude）、S10s（Codex）上优于规则策略，在 S9s 上规则最好；
  四个规格在代理器件上均未通过（S9/S10 已知不可行，前沿约 −19.7 dBm）。要形成 Table V 式结论需 5 seed 且不封顶或更高上限。
- **行为差异。** Claude 在 S9 上由 Manager 主动 `stop`（12 次调用后判定不可行而停止），S10 用 19 次；Codex 每次都用满 40 次。
  Codex 的 Refiner 偏好 `rerun_stage2`（55–68%）且从不判 `fail`；Claude 更多 `rerun_stage3`，并会对无望的候选判 `fail`（共 22 次）。
- **成本口径。** 订阅不计费；Claude Code 每次约 1.9–2.3k prompt token（Windows 本机，固定上下文小于云端），时延 15–19 s/次；
  `codex exec` 每次约 15.8k prompt token（其中约 77% 命中缓存），时延约 22 s/次。不能折算论文 Table VI 的美元成本。

### 4.2 Codex 5 seed（2026-10-01/02，seed 0–4，`ORFADC_LLM_MAX_CALLS=40`，仅 ChatGPT/Codex）

**条件：**
- 按用户要求，扩到 5 seed 时只用 Codex，Claude 只有 seed 0。
- 代理仿真器，趋势级。
- 原始档：
  - seed 1–4：Windows 作业 `results\windows_checks\20261001T191008_job\`（32 次设计，约 5.6 h）。
  - seed 0：`results/repro/llm_live/windows_20261001/`。
- 汇总：`results/repro/llm_live/codex_5seed_20261002/llm_seeds.{md,json}`，命令为
  `bench llm-seeds --out <作业目录> --inputs results/repro/llm_live/windows_20261001`。

**两种口径：**
- "报告设计"：运行结束时 Manager 报告的设计，即旧逻辑下每个 refine 循环的最后一次评估。
- "最佳评估"：整次运行所有全链评估里违规最小的一次。
- 两条主干的报告逻辑相同。但"报告设计"一栏受 B20 影响（docs/123 §9），所以以"最佳评估"做主比较。

| spec | 策略 | 通过 | 报告设计 违规 均值 / 中位 | **最佳评估 违规 均值 / 中位** | 最佳评估 Codex 优于 rule 的 seed 数 | LLM 调用/次 | prompt+completion tok/次 | 封顶后规则决策（合计） |
|---|---|---|---|---|---|---|---|---|
| S9 | rule | 0/5 | 2.18 / 2.16 | **1.78 / 1.73** | – | – | – | – |
| S9 | Codex | 0/5 | 2.33 / 2.08（3/5 有报告设计） | 1.80 / 1.83 | 2/5 | 39.4 | 633k | 253 |
| S10 | rule | 0/5 | 3.23 / 3.24 | 3.13 / 3.21 | – | – | – | – |
| S10 | Codex | 0/5 | 4.34 / 3.72 | **2.57 / 2.57** | **5/5** | 38.6 | 620k | 207 |
| S9s | rule | 0/5 | 0.83 / 0.93 | **0.22 / 0.22** | – | – | – | – |
| S9s | Codex | 0/5 | 1.37 / 1.49 | 0.33 / 0.27 | 1/5 | 40.0 | 644k | 434 |
| S10s | rule | 0/5 | 0.58 / 0.71 | **0.28 / 0.28** | – | – | – | – |
| S10s | Codex | 0/5 | 1.26 / 1.19 | 0.64 / 0.66 | 0/5 | 40.0 | 643k | 396 |

**读法与结论：**

- **20 次 Codex 运行全部未通过。** 规则策略也一样。S9/S10 在代理器件上不可行，前沿约 −19.7 dBm；S9s/S10s 是前沿缩放版。
- **S10 上 Codex 稳定优于规则**：5/5 个 seed 的最佳评估违规更小，均值 2.57 对 3.13。
  - 但"报告设计"反而更差（4.34 对 3.23）：Codex 后期常以 `rerun_stage2` 结束循环，最后一次评估不是最好的。这正是 B20 的影响。
- **S9 两者持平**（最佳评估 1.80 对 1.78）。
  - Codex 在 seed 1、2 中所有 refine 都以 Stage 2 不可行结束，没有报告设计。
  - 已修：`ORFADC_REPORT_BEST=1` 时这类循环也返回已评估的最好候选。
- **S9s/S10s（可行性更高的缩放版）规则策略更好。**
  - 40 次调用的上限在 2.5–3 h 等效预算里只覆盖前段决策，封顶后由规则接手。
  - Codex 前段偏好 `rerun_stage2`、扩大 NF 余量，会把预算花在 Stage 2 上。
- **可靠性：**
  - 20 次运行共 790 次 Codex 调用。
  - 3 次调用失败（S9 seed 4、S10s seed 2、S10s seed 4 各一次），每次都由规则策略兜底一步（即 3 次 fallbacks），未中断运行。
  - 没有非法输出。
- **成本：**
  - 每次运行约 0.62–0.64 M token，其中约 77 % 命中缓存。
  - 订阅额度，不计费；不折算论文 Table VI 的美元成本。
- **结论：**
  - 在本代理环境与 40 次调用上限下，**不能**复现论文"LLM 主干显著优于基线"的 Table V 结论。
  - 只在最难的 S10 上看到稳定的正向差异。
  - 更高的调用上限或不封顶、以及 PDK 器件前沿，是下一步检验的条件。

### 4.3 Codex 不封顶（2026-10-02）

**设置：**
- `ORFADC_LLM_MAX_CALLS=1000`，每次运行实际受 5 h 等效预算约束。
- 范围：S9s/S10s × seed 0–4。
- 作业：`results\windows_checks\20261002T095407_job\`。
- 汇总：`results/repro/llm_live/codex_uncapped_20261002/runs.json`。

**有效性：**
- 第一轮作业 `20261002T095407_job`：第 7–10 个运行时 ChatGPT 订阅额度用尽（"You've hit your usage limit"），
  S9s seed 3 在第 39 次调用后、S10s seed 3 与 S9s/S10s seed 4 从第一次起由规则策略兜底，这 4 个运行**作废**。
- 补跑作业 `20261002T134538_job`（额度恢复后）：S9s/S10s seed 3–4 重跑，4 个运行全部有效（0 错误、0 回退）。
- 因此 S9s、S10s 各有 **5 个有效 seed**。

**结果**（最佳评估违规，越小越好；同一 seed 对比；agent v1）：

| spec | seed | Codex 不封顶 | Codex 40 次封顶 | rule | 不封顶调用次数 / 用掉的等效时间 |
|---|---|---|---|---|---|
| S9s | 0 | 0.77 | 0.65 | **0.27** | 55 / 7283 s |
| S9s | 1 | 0.61 | 0.27 | **0.22** | 45 / 5636 s |
| S9s | 2 | **0.18** | 0.18 | 0.20 | 63 / 7784 s |
| S9s | 3 | 0.41 | 0.23 | **0.19** | 62 / 8024 s |
| S9s | 4 | 0.33 | 0.33 | **0.23** | 60 / 7996 s |
| S10s | 0 | 0.50 | 0.68 | **0.25** | 63 / 8892 s |
| S10s | 1 | 0.58 | 0.62 | **0.24** | 132 / 18000 s |
| S10s | 2 | 0.32 | 0.81 | **0.29** | 65 / 8929 s |
| S10s | 3 | 0.81 | 0.66 | **0.35** | 54 / 7958 s |
| S10s | 4 | 0.82 | 0.43 | **0.28** | 52 / 7689 s |
| **均值** | | S9s 0.46、S10s 0.61 | S9s 0.33、S10s 0.64 | **S9s 0.22、S10s 0.28** | 平均 65 次 |

**结论：**
- 去掉 40 次上限后，Codex 在 S9s 上更差（0.46 对 0.33），在 S10s 上基本持平（0.61 对 0.64）。两个规格上都明显不如规则策略。
- 10 次里只有 1 次（S9s seed 2）优于规则。
- 主要原因：Codex 的 Manager 常在预算只用了 30–50 % 时就判定"不可行"并停止（10 次里 9 次）；规则策略总是用满 5 h 预算。
- 0/10 通过。在订阅额度条件下，"LLM 主干显著优于基线"（Table V）**未复现**。
- 每次运行约 0.83–1.0 M token（约 78 % 命中缓存），订阅额度不计费。
- 以上均为 agent v1（Searcher 为程序，LLM 只在 Manager 选功率分配、Refiner 选动作两处决策）。更贴近论文的 v2 见后续文档。

Cadence（Spectre 25.1，宏模型 v1）：

- `cadence_check_S2.json`：关键级（单频点）与全链（60 个唯一频点）两种工况，Spectre 与两端口引擎在增益/S11/NF/NFmin 上逐点一致到 1e-9 dB 量级，
  IP1dB 估计差 0.2–0.3 dB（引擎第一级 vgs 用 `Ig/(ωCgs)` 近似）。这独立证明了引擎的 ABCD/噪声相关矩阵级联与 Spectre 的二端口噪声分析一致。
- 物理接法敏感度（第一级 Cdb 接地）：中心频点增益 26.9 vs 27.3 dB、NF 4.43 vs 4.14 dB，全带 S11 最差 −18.2 dB——设计仍满足 S2；
  这是"引擎拓扑近似"带来的量级，v2 换 PDK 器件后消失（docs/120）。
- `design --spec S2 --backend cadence`：多保真分工按论文执行（Stage 2/3 在引擎上 2801 次等效 HF 仿真，Stage 4 共 11 次 Spectre），最终设计由 Spectre 判定通过。

## 5. 运行方法

一次性登录（在你自己的 PowerShell 里，浏览器完成授权）：

```powershell
npm i -g @anthropic-ai/claude-code ; claude auth login --claudeai
npm i -g @openai/codex ; codex login
```

检查与联调（日志写到 `results\windows_checks\<时间>\`）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows_llm_cadence_check.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows_llm_cadence_check.ps1 -RunS9 -S9Calls 40   # 再跑 S9 各 1 个 seed
```

单独命令：

```powershell
$env:PYTHONPATH="$PWD\src"
python -m orfadc.repro.bench llm-check --policy claude-cli
python -m orfadc.repro.bench llm-check --policy codex-mcp
python -m orfadc.repro.bench cadence-check --spec S2
python -m orfadc.repro.bench design --spec S9 --policy claude-cli          # ORFADC_LLM_MAX_CALLS 控制额度
python -m orfadc.repro.bench design --spec S2 --backend cadence            # Stage 4 走 Spectre
python -m orfadc.repro.bench llm-table --out <含 design_*.json 的目录>      # 汇总表（区分非法回退与封顶后规则决策）
```

一键脚本（双击即可，日志写到 `results\windows_checks\<时间>_all\`，`progress.txt` 看进度，结束写 `DONE.txt`）：

- `scripts\run_all_windows.cmd`：环境/订阅/Cadence 检查 → {rule, claude-cli, codex-mcp} × {S9, S10, S9s, S10s} → `llm_table` → `cadence-check` + `design --spec S2 --backend cadence`（虚拟机可达时）。
- `scripts\run_codex_followup.cmd`：只补 Codex（重装钉住版本的依赖、检查 codex-mcp、补跑 4 个 Codex 设计、重生成汇总表），写入最新的 `*_all` 目录。

依赖注意：`mcp` 须为 1.x（`mcp>=1.2,<2`）。mcp 2.x 把 FastMCP 改名为 MCPServer，两个 MCP 服务器会直接退出并提示重装。
