# 133 智能体实现 v2 的真实 LLM 结果（A3）

> docs/130 §3 A3 的记录。v2 = LLM 驱动的 ReAct Manager / Searcher / Refiner（docs/131）。
> 代理后端结果是**趋势级证据**（开放 EKV 类器件模型），不是 PDK/硅结果；所有结果带 `agent_impl=v2`、`not_silicon_result` 标签。

## 1. LLM 通道（macOS，2026-10-07）

| 通道 | 状态 | 说明 |
|---|---|---|
| `codex-mcp` | ✅ 可用 | 用 ChatGPT.app 自带的 codex 命令行（`codex-cli 0.159.0-alpha`，ChatGPT 账号已登录），通过 `ORFADC_CODEX_BIN` 指定，CODEX_HOME 用该应用自己的 `~/.codex`。`bench llm-check --policy codex-mcp`：ok，Refiner 决策合法，单次 15.6 s |
| `claude-cli` | ✅ 可用（Pro） | 用桌面 App 自带的 Claude Code 2.1.288。前两次 `claude auth login --claudeai` 返回 HTTP 403，原因是网络路径：命令行工具不认 macOS 系统代理，直连 Claude 授权接口时得到 403 `Request not allowed`，经本机代理（Aurora，127.0.0.1:29290）则正常。设 `HTTPS_PROXY` 后登录成功；`llm-check`：ok，单次 19.4 s |

两个命令行都链接到 `~/.local/bin/{claude,codex}`。`run_job_queue.sh` 在未设 `HTTPS_PROXY` 时会自动采用已开启的系统代理。v1（Windows）用的是同一条登录命令（npm 安装），所以 403 与登录方式无关，只与网络出口有关。

## 2. A3 第 1 步：S2 seed 0 冒烟（codex-mcp）

命令（代理后端，0 次 Spectre）：
```bash
ORFADC_LLM_MAX_CALLS=1000 ORFADC_CODEX_BIN=<ChatGPT.app 自带的 codex> \
  python -m orfadc.repro.bench design --spec S2 --seed 0 --policy codex-mcp --agent-impl v2 --out results/repro/v2_a3/smoke
```
原始档：`results/repro/v2_a3/smoke/design_S2_seed0_mode1_codex-mcp_v2_calls1000.json`、`codex_S2_seed0.log`。

| | v2 + codex-mcp（本次） | v2 + scripted（docs/131，离线神谕） | v1 rule（docs/131） |
|---|---|---|---|
| 结果 | ✅ 通过，`terminated_reason=spec_met` | ✅ `spec_met` | ✅ |
| 等效 EDA 时间 | 1523 s | 2036 s | 1901 s |
| 搜索 / 细化次数 | 2 / 3 | 3 / 3 | 3 / 3 |
| 试过的功率分配 | [0.4, 0.3, 0.3]、[0.4, 0.35, 0.25] | 3 个 | 3 个 |
| LLM 调用 | **55**（Manager 5、Searcher 12、Refiner 38） | 66（离线） | — |
| 非法动作 / 传输错误 / 回落规则 | 0 / 0 / 0 | — | — |
| LLM 时延合计 | 839 s（约 15 s/次） | — | — |
| token | 输入 977k（其中缓存 747k，76 %），输出 12k | — | — |

最终设计（代理后端）：带内最小增益 22.7 dB、纹波 2.1 dB、NF@fc 4.28 dB、带内最差 S11 −18.2 dB、IP1dB −22.8 dBm、28.4 mA，违例 0。

**claude-cli（同条件）**：✅ 通过，`spec_met`；调用 **39 次**（Manager 4、Searcher 13、Refiner 22），非法动作/错误/回落 0/0/0；
LLM 时延 367 s（约 9.4 s/次）；输入 171k token（这个通道不报告缓存），输出 16k；等效 EDA 时间 1014 s；搜索/细化 2/2，
功率分配 [0.4, 0.3, 0.3]、[0.33, 0.42, 0.25]。设计：增益 25.2 dB、纹波 0.58 dB、NF@fc 4.22 dB、S11 带内最差 −22.9 dB、IP1dB −23.1 dBm、27.0 mA。
原始档 `design_S2_seed0_mode1_claude-cli_v2_calls1000.json`、`claude_S2_seed0.log`。

读法与边界：
- 这一步只验证真实 LLM 能在 v2 协议下自主完成一次设计：55 次决策全部合法，没有回落到规则策略。单个 seed 不能用来比较 v2 与 v1 的优劣。
- 实测调用数（55）落在开始前估计的 60–150 区间下沿附近，时长约 14 min（估计 20–50 min）。
- 订阅额度不计费，不折算论文 Table VI 的美元成本。

## 3. S9s/S10s seed 0（codex-mcp，进行中）

- **S9s 第一次运行崩溃（作废，待重跑）**：约 9 min 后 `TypeError: float - None`。
  - 原因是一个 v2 缺陷：参数校验与提示词都允许 `gain_req_list` 里有 `null`（含义是"该级不约束"），
    但共享工具 `tools.band_planning` 的增益要求罚项对每一项都做减法。LLM 照规则发了 `null`，结果整次运行崩溃。
  - 修正：罚项抽成 `tools.gain_req_penalty`，跳过 `null` 项。v1 只传数字，行为不变。新增回归测试，全量 122 passed。
  - 崩溃日志保留在 `results/repro/v2_a3/s9s10s/codex_S9s_seed0.log`。
  - 包装脚本里的 `exit=$?` 取的是 `date` 的返回值，所以记成了 0；以后用单独的变量保存退出码。
- S10s 用的是修正前已经加载的代码，跑完即有效（这个缺陷只会让运行崩溃，不会悄悄改变结果）。
  **结果：codex S10s seed 0 同样崩溃**（约 2 h、294 次以上调用后，同一个 `float - None`），作废。
  日志 `codex_S10s_seed0_CRASHED_pre_fix.log`；04:47 用修正后的代码重跑。
  修正之后启动的运行都没有这个问题（例如 codex S9s seed 3 正常完成）。

**claude-cli（修正后的代码，seed 0）：S9s、S10s 都通过**

| 规格 | 结果 | LLM 调用（M/S/R） | 非法动作/错误 | LLM 时延 | 等效 EDA 时间（预算 18000 s） | 搜索/细化 | 最终设计 |
|---|---|---|---|---|---|---|---|
| S9s | ✅ `spec_met` | 66（6/29/31） | 0/0 | 631 s | 2236 s | 3/3 | 增益 24.3 dB、NF 4.50 dB、IP1dB −19.6 dBm、S11 −19.5 dB、27.5 mA |
| S10s | ✅ `spec_met` | 57（6/28/23） | 0/0 | 588 s | 1845 s | 3/3 | 增益 24.1 dB、NF 3.87 dB、IP1dB −20.7 dBm、S11 −20.7 dB、27.5 mA |

对照（同一代理后端、5 h 预算，`results/repro/2026-10-03` Table V-like 与 docs/127 §5.2）：
- v1 rule（"ours"）：S9s 0/5、S10s 0/5；
- GA subtool 1/5、2/5；BO subtool 1/5、3/5；
- v1 + Codex（不封顶）：10 次只有 1 次优于规则，没有通过。

读法：v2 + claude 在 seed 0 上两个规格都在 1/8 预算内通过，是 v1 各种设置从未达到的结果。但这只是**单个 seed**，要用 seed 1–4 确认后才能说 v2 优于 v1。
原始档：`results/repro/v2_a3/s9s10s/design_S{9,10}s_seed0_mode1_claude-cli_v2_calls1000.json`、`claude_S{9,10}s_seed0.log`。

**seed 1–4 用哪个 LLM（2026-10-07 用户决定）：只用 codex，与 v1 完全对齐。**
- v1 的 S9s/S10s 扩到 5 个 seed 时只用了 Codex（docs/119 §4.2–4.3），claude 只有 seed 0。
- 执行者原先按"第 2 步用 A、第 3 步用 B"的顺序，已在后台启动 claude 跑 seed 1–4，用户随后选择与 v1 对齐，该运行被停止：
  - claude S9s seed 1 在停止前已跑完：✅ `spec_met`，73 次调用（M/S/R 7/37/29），0 非法动作，等效 2265 s。
    保留为**补充数据**，不进 v1 对齐的对照表。
  - claude S10s seed 1 被中途停止，无结果（日志改名为 `claude_S10s_seed1_STOPPED_by_user.log`）。
- codex 的 seed 1–4 队列：`scripts/jobs/queue_a3_s9s10s_codex_seeds1-4.txt`（8 次运行）。实际在后台分两组并行运行（seed 1–2、seed 3–4）。

### 3.1 codex 5 个 seed 汇总（与 v1 对齐，2026-10-07 完成）

`bench llm-table --out results/repro/v2_a3/s9s10s`（`llm_table.md/.csv`）。viol = 报告设计的归一化残余违规（增益/纹波/IP1dB/S11/功耗每 3 dB 计 1，NF 每 1 dB 计 1），与 docs/119 §4.3 同一口径。

| 规格 | seed | 结果 | viol | LLM 调用 | 非法动作 | 等效时间 | 结束原因 |
|---|---|---|---|---|---|---|---|
| S9s | 0 | ❌ NF 差 0.16 dB | 0.16 | 529 | 2 | 17365 s | `finish`（Manager 判定结束） |
| S9s | 1 | ✅ | 0 | 588 | 0 | 16713 s | `spec_met` |
| S9s | 2 | ✅ | 0 | 198 | 0 | 5273 s | `spec_met` |
| S9s | 3 | ✅ | 0 | 90 | 0 | 2462 s | `spec_met` |
| S9s | 4 | ✅ | 0 | 175 | 0 | 4727 s | `spec_met` |
| S10s | 0 | ✅ | 0 | 450 | 1 | 14293 s | `spec_met` |
| S10s | 1 | ❌ NF 差 0.14 dB、IP1dB 差 0.29 dB | 0.23 | 519 | 1 | 16688 s | `finish` |
| S10s | 2 | ❌ NF 差 0.47 dB | 0.47 | 236 | 3 | 8749 s | `invalid_actions`（见下） |
| S10s | 3 | ✅ | 0 | 183 | 0 | 6259 s | `spec_met` |
| S10s | 4 | ❌ NF 差 0.37 dB | 0.37 | 523 | 0 | 16373 s | `finish` |

**与 v1 和基线对比（同一代理后端、5 h 预算、5 个 seed）**

| 方法 | S9s 通过 | S10s 通过 | S9s viol 均值 | S10s viol 均值 | 来源 |
|---|---|---|---|---|---|
| **v2 + codex** | **4/5** | **2/5** | **0.03** | **0.21** | 本节 |
| v1 + Codex（不封顶） | 0/5 | 0/5 | 0.46 | 0.61 | docs/119 §4.3 |
| v1 rule | 0/5 | 0/5 | 0.22 | 0.28 | docs/119 §4.3 |
| GA subtool / BO subtool | 1/5、1/5 | 2/5、3/5 | — | — | Table V-like（2026-10-03） |

读法与边界：
- 同一个 LLM（Codex）、同一口径下，v2 的 ReAct 三智能体从 v1 的 0/10 提高到 **6/10**，viol 均值在两个规格上都低于 v1 的规则策略。
  这是"智能体实现"的差异：v1 中 LLM 只在两个决策点出主意，Searcher 是程序；v2 中三个智能体都由 LLM 驱动。
- 失败的 4 次都只差一点 NF（0.14–0.47 dB），其中 3 次几乎用满 5 h 预算。
- **S10s seed 2 的结束原因**：Manager 连续 3 次提交已经搜索过的功率分配（`[0.3, 0.5, 0.2]`、`[0.3, 0.45, 0.25]` 两次），
  每次都收到 `already searched` 的错误观测仍然重复，按 docs/131 的规则（连续 3 次非法动作）终止，报告当时最好的设计。
  这是 LLM 的行为，不是程序错误。可改进之处：在观测里列出已试过的分配。
- 代价：codex 每次运行 90–588 次调用、每次调用输入约 18k token（v1 平均 65 次调用）；5 个 seed 合计 3491 次调用，不含修正前崩溃作废的两次（约 330 次）。
- 补充：claude-cli 在 S9s seed 0/1、S10s seed 0 上 3/3 通过，每次只用 57–73 次调用（不进 v1 对齐表）。
- 仍是代理后端的趋势级结果，不是 PDK/硅结果；不能填论文 Table V 的"实测"位置。

## 4. A3 第 2 步：N65 PDK 上的 v2 + codex（与 N3 的 v1 基线同口径）

条件：N65 PDK 后端（原理图级、理想无源、无版图寄生），1 h 等效预算，每设计 Spectre 不封顶（护栏 60），LLM 上限 1000；
标签 `agent_impl=v2`、`pdk=crn65lp`、`not_silicon_result`。用户在终端启动队列 `scripts/jobs/queue_a3_n65_v2_codex_s0.txt`（08:31–10:36）。
原始档 `results/repro/v2_a3/n65/seed0/`。

### 4.1 seed 0：4/8（v1 同 seed 也是 4/8，通过的规格相同）

| 规格 | v2 + codex | Spectre | LLM 调用 | 等效时间 | 失败情况 | v1 rule seed 0（docs/132 §5.1） |
|---|---|---|---|---|---|---|
| S1 | ✅ | 1 | 11 | 271 s | — | ✅ 376 s，1 次 Spectre |
| S2 | ✅ | 4 | 23 | 965 s | — | ✅ 603 s，2 次 |
| S3 | ❌ | 0 | 79 | 3225 s | 没有产生设计：搜索 8 次、细化 0 次，Searcher 一直找不到能满足 NF 的候选 | ❌ NF 差 3.16 dB，33 次 |
| S4 | ✅ | 1 | 14 | 552 s | — | ✅ 540 s，1 次 |
| S5 | ❌ | 24 | 108 | 3276 s | S11 差 4.42 dB、纹波差 0.31 dB | ❌ 纹波差 0.18 dB，36 次 |
| S6 | ❌ | 31 | 120 | 3363 s | S11 差 6.08 dB、纹波差 0.2 dB | ❌ S11 差 4.07 dB，30 次 |
| S7 | ❌ | 0 | 86 | 3032 s | 没有产生设计：搜索 12 次、细化 0 次 | ❌ NF 差 1.52 dB，15 次 |
| S8 | ✅ | 1 | 11 | 347 s | — | ✅ 1057 s，11 次 |
| 合计 | **4/8** | **62** | **452** | | | 4/8，129 次 |

读法与边界：
- 通过的规格与 v1 完全相同。v2 用的 Spectre 不到 v1 的一半（62 对 129），因为 S3/S7 根本没走到 Stage 4。
- **v2 的一个行为差异**：在器件受限的 S3/S7 上，v2 的 Manager 把预算全部花在换功率分配重新搜索上（S3 试了 10 个分配，S7 试了 12 个），
  从不进入细化，所以没有报告任何设计；v1 会细化并报告违例最小的设计。按 pass@1 计两者都是失败，但 v2 没有给出"最接近的设计"。
- 非法动作 3 次（S3 1 次、S7 2 次），都在重试后恢复；0 次传输错误。
- 单个 seed，不能下结论；seed 1–4 见 §4.2（待跑）。

## 5. 下一步

- 待用户确认：S9s/S10s seed 0（5 h 预算，codex-mcp），再到 seed 0–4。
- claude-cli 登录问题解决后，补 S2 冒烟与同一套 S9s/S10s。
- N65 PDK 上的 v2 评估（A3 第 2 步）在 N3 完成后进行。
