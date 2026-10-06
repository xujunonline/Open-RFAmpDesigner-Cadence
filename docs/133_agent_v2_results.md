# 133 智能体实现 v2 的真实 LLM 结果（A3）

> docs/130 §3 A3 的记录。v2 = LLM 驱动的 ReAct Manager / Searcher / Refiner（docs/131）。
> 代理后端结果是**趋势级证据**（开放 EKV 类器件模型），不是 PDK/硅结果；所有结果带 `agent_impl=v2`、`not_silicon_result` 标签。

## 1. LLM 通道（macOS，2026-10-07）

| 通道 | 状态 | 说明 |
|---|---|---|
| `codex-mcp` | ✅ 可用 | 用 ChatGPT.app 自带的 codex 命令行（`codex-cli 0.159.0-alpha`，ChatGPT 账号已登录），通过 `ORFADC_CODEX_BIN` 指定，CODEX_HOME 用该应用自己的 `~/.codex`。`bench llm-check --policy codex-mcp`：ok，Refiner 决策合法，单次 15.6 s |
| `claude-cli` | ❌ 未登录 | 用桌面 App 自带的 Claude Code 2.1.288 执行 `claude auth login --claudeai`，两次都在令牌交换时返回 HTTP 403（第二次在用户粘贴授权码之前就失败）。疑似网络出口/代理或账号权限问题，待用户排查；claude-cli 一组暂缓 |

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

读法与边界：
- 这一步只验证真实 LLM 能在 v2 协议下自主完成一次设计：55 次决策全部合法，没有回落到规则策略。单个 seed 不能用来比较 v2 与 v1 的优劣。
- 实测调用数（55）落在开始前估计的 60–150 区间下沿附近，时长约 14 min（估计 20–50 min）。
- 订阅额度不计费，不折算论文 Table VI 的美元成本。

## 3. 下一步

- 待用户确认：S9s/S10s seed 0（5 h 预算，codex-mcp），再到 seed 0–4。
- claude-cli 登录问题解决后，补 S2 冒烟与同一套 S9s/S10s。
- N65 PDK 上的 v2 评估（A3 第 2 步）在 N3 完成后进行。
