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

## 4. 下一步

- 待用户确认：S9s/S10s seed 0（5 h 预算，codex-mcp），再到 seed 0–4。
- claude-cli 登录问题解决后，补 S2 冒烟与同一套 S9s/S10s。
- N65 PDK 上的 v2 评估（A3 第 2 步）在 N3 完成后进行。
