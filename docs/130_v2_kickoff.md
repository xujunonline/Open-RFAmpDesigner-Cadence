# 130 v2 启动任务说明（第 2 版：v2 智能体 + N65 工艺，在 Claude Code 中执行）

> **用法**：Windows 终端 `cd F:\Open-RFAmpDesigner-Cadence` → `claude` → 输入：
> **`按 docs/130_v2_kickoff.md 执行：先做阶段 0，然后 A 线与 B 线按文中顺序推进，每个阶段结束时汇报，在标"需确认"处停下等我回复。`**
> 之后所有改动仓库的任务都在 Claude Code 中实施。

---

## 0. 背景

- 本仓库复现 RFAmpDesigner（arXiv:2605.10093，原文 `references/paper/`）。规则以 `CLAUDE.md` 为准，本文件只在其上增加约束。
- 已发布（GitHub 私有仓库 `xujunonline/Open-RFAmpDesigner-Cadence`）：`v1-decision-points`（e80dfd3）、`v1.1-clean`（4feb7a0，main，88 个测试通过，docs/129）。
- **智能体实现 v1**（`repro/agents.py` + `repro/llm.py`）：Searcher 是程序，LLM 只在 Manager 选功率分配（`LLMPolicy.next_split`）与 Refiner 选动作
  （`LLMPolicy.refine_action`）两处决策，失败时回落 `RulePolicy`。Codex 不封顶 S9s/S10s 违规 0.46/0.61，不如规则 0.22/0.28（docs/127 §5.2）。
- **智能体实现 v2（A 线）**：按论文，Manager / Searcher / Refiner 都是 LLM 驱动的 ReAct 智能体（Thought → Action → Observation），
  工具为 Table I 四个工具 + KB/EB 查询。
- **N65 工艺（B 线）**：v1 的 PDK 结果用旧虚拟机 `RedHat_9_7_A_and_D_10T` 上的 TSMC 40 nm LP RF（crn40lp）。新虚拟机 `F:\IC618_rf`
  （CentOS 7、IC 6.1.8）磁盘扫描为 **TSMC 65 nm LP RF（CRN65LP v1.7a，论文同节点）**，RF 管同名 `nmos_rf`，另有螺旋电感模型（docs/128）。
  v2 的 PDK 评估改在 N65 上做；crn40lp 结果作为 v1 历史记录保留，旧虚拟机保留不删。
- **为什么要 v1 基线**：若直接比较"v2 + N65"与"v1 + crn40lp"，差异分不清来自智能体还是工艺。所以 N65 上先用 v1（规则策略）跑基线，再在同一工艺上比较 v1 与 v2。
- 命名注意：`pdk_v2.py` / docs/120 的 "Cadence v2" 指 PDK 后端，与"智能体实现 v2"无关，不要改名。

## 1. 硬性约束

1. `CLAUDE.md` 全部规则照常适用：不伪造结果；不读、不打印、不提交 `config/remote_cadence.local.yaml`、`config/model_paths.local.yaml`、私钥。
2. **凭据**：执行者不得接收、输入或保存任何密码；不在文档、提交、日志、命令行中出现密码。SSH 只用密钥登录，密钥由用户在阶段 N0 自己配置。
3. **Spectre 账本（N65 独立记账）**：用户批准 N65 上限 **1500 次**，与 crn40lp 旧账（约 697/1000）分开。
   - 账本文件 `results/repro/n65/spectre_ledger.csv`（提交；列：时间、阶段、命令、spec、seed、Spectre 次数、累计、提交哈希；只记次数，不含 PDK 数据）。
   - 预分配：N1 接入与表征 ≤150；N2 冒烟 ≤120；N3 v1 基线 5 seed ≤550；A3 v2 PDK 评估 ≤550；机动 ≈130。
   - 每个用 Spectre 的阶段开始前报告预计次数并**等待确认**；每设计设 `ORFADC_SPECTRE_MAX_PER_DESIGN`；超出预分配或累计将超 1500 时停下。
   - 结果不确定（连接中断、无返回）时不自动重派，先查远程状态再汇报。
4. **v1 行为冻结**：默认（未设 `ORFADC_AGENT_IMPL` 或为 `v1`）且使用代理后端时，输出与 v1.1 一致：全量 pytest 通过；`bench replot --out <临时目录>`
   与 `results/repro/2026-10-03` 的 Table IV/V 逐字节一致（生成时间行除外）；`bench design --spec S2 --seed 0 --policy rule` 的 JSON 一致（新增标签字段除外）。
   crn40lp 的 PDK 结果文件不改动。
5. v2 代码放新模块（`repro/agents_v2.py`、`repro/prompts/v2/*.md`）；N65 适配只做参数化（读 `model_paths.local.yaml`），不删除 crn40lp 路径。共享层只做加法式改动。
6. **花额度的动作先问**：真实 LLM 运行先报预计调用次数和时长并等确认；离线开发只用 `scripted`。
7. git：全部在分支 `v2-agentic` 上；每阶段一个提交（结尾加会话署名）；推送、打标签需用户确认；永不强推。
8. 结果标注 `agent_impl`（v1/v2）、`pdk`（crn40lp/crn65lp）与 `not_silicon_result`；N65 结果另注"原理图级、无版图寄生"。
   新文档从 `docs/131` 起编号并同步 `docs/00_index.md`。

## 2. 阶段 0：环境与分支（无需确认）

- 检查：`git status`（只应有本文件、`docs/00_index.md`、`CLAUDE.md` 的改动）、`git describe --tags` = `v1.1-clean`、Python ≥ 3.11、
  `pip install -r config/requirements_repro.txt`、`claude --version`、`codex --version`（缺失只记录）。
- 检查 `.claude/settings.json` 的 hook 在 Windows 上能运行（`guard_bash.py`）；不能运行则修正并在汇报中说明。
- `git switch -c v2-agentic`；建 `results/repro/n65/spectre_ledger.csv`（表头）；提交 "v2: kickoff (docs/130), N65 spectre ledger"。
- 全量 pytest（预期 88 passed）与 `bench smoke`，记录耗时。

## 3. A 线：v2 智能体（不用虚拟机）

### A1 修 docs/129 §3 的问题 1–3（无需确认；须满足约束 4）
1. 输出文件名冲突：默认设置文件名不变；`agent_impl=v2`、`--backend pdk` 下的 `pdk` 名称、或 `ORFADC_LLM_MAX_CALLS` / `ORFADC_SPECTRE_MAX_PER_DESIGN` /
   `ORFADC_STAGE2_BACKOFF` / `ORFADC_REPORT_BEST` / `ORFADC_BUDGET_SCALE` 非默认时追加稳定后缀（如 `_v2`、`_n65`、`_calls1000`）；
   `llm-seeds` / `llm-table` 接受后缀并分组，不再静默跳过；补测试。
2. 功率比范围：v1 校验 0.1–0.8 不动；v2 的提示词与校验统一（0.15–0.7，常量），补测试。
3. `--backend cadence` 也遵守 `ORFADC_SPECTRE_MAX_PER_DESIGN`（未设时不变）；fake 后端测试。
- 提交 "v2: fix output naming, split range, cadence spectre guard"。

### A2 v2 ReAct 智能体（离线，无需确认）
- 先写 `docs/131_agent_v2_design.md`：与论文逐条对应（职责、工具、观测、停止条件、记忆读写、预算记账），再写代码。
- 要点：
  - ReAct 循环：每步一个 JSON 动作（工具 + 参数，或 `finish`），执行后回填裁剪后的观测与剩余预算；非法动作返回错误观测让 LLM 重试（计次）；
    连续失败或超限时**终止并写 `terminated_reason`**，不偷偷换成规则策略。
  - Manager 把 Searcher / Refiner 当子智能体工具调用；Searcher 自主调用 `active_sizing` / `impedance_matching`；Refiner 自主调用 `band_planning` / `fullchain_evaluation`。
  - 预算：等效 EDA 时间沿用 `SimCounter` 与 `bench.budget_for`（S1–S8 1 h，S9/S10 5 h）；LLM 上限 `ORFADC_LLM_MAX_CALLS`；先到先停。
  - KB/EB：沿用 `memory.py`，记录带 `agent_impl` 与 `pdk`；v1/v2 与 crn40lp/N65 的记忆目录分开。
  - 开关：`ORFADC_AGENT_IMPL=v2` 或 `bench design --agent-impl v2`；MCP `run_autonomous` 同名参数。trace 记录每步动作、观测摘要、token。
- 离线验证：v2 的 `ScriptedTransport` 脚本覆盖正常完成、非法动作、超预算、LLM 中断；S2 端到端跑通。
- 提交 "v2: ReAct agents (offline, scripted)"。

### A3 真实 LLM 运行（**需确认**）
1. 代理后端：S2 seed 0 冒烟 → S9s/S10s seed 0 → seed 0–4（论文口径 5 h、`ORFADC_LLM_MAX_CALLS=1000`）；claude-cli 与 codex-mcp 各一套。
   与 v1（docs/127 §5.2）、规则策略同表，写 `docs/133_agent_v2_results.md`。
2. N65 PDK（在 N3 完成后）：S1–S8 × 5 seed、1 h、v2 + 选定 LLM，与 N3 的 v1 基线同表对比（≤550 次 Spectre）。

## 4. B 线：N65 接入与 v1 基线（与 A 线并行；全部用 Spectre 的步骤**需确认**）

### N0 虚拟机与登录（用户操作为主）
- 用户：在 VMware 打开 `F:\IC618_rf\IC618_rf.vmx` 开机；在虚拟机里查 IP（`ip addr`）。
- 执行者在 Windows 上生成专用密钥（如 `ssh-keygen -t ed25519 -f %USERPROFILE%\.ssh\ic618_rf -N ""`，若已有则跳过），然后**请用户自己**运行
  `type %USERPROFILE%\.ssh\ic618_rf.pub | ssh userone@<IP> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"`
  （这一步由用户输入 userone 的密码；执行者不接触密码）。登录用户为 `userone`，不用 root。
- 用户按 `config/remote_cadence.example.yaml` 更新本地 `config/remote_cadence.local.yaml`（host、user=userone、identity_file）。
  建议旧虚拟机的配置另存一份（如 `remote_cadence.crn40lp.local.yaml`，同样被 git 忽略）。
- 执行者验证：`ssh -i ... userone@<IP> "echo ok; which spectre virtuoso; spectre -W"`（需确认；0 次仿真）。若 `spectre` 不在 PATH，
  查 Cadence 环境脚本（如 `~/.cshrc`、`~/.bashrc`、`/home/IC/*`），把需要的 source 命令作为 `remote_runner` 的可配置前缀，不写死。
- 安全建议（告知用户）：虚拟机只用 NAT/仅主机网络；root 与 userone 的弱密码建议改掉或关闭 root 的 SSH 登录。

### N1 盘点与表征（**需确认**，≤150 次）
- 先改 `repro/pdk_inventory.sh`：Cadence 安装前缀与 PDK 搜索根可配置（新机 PDK 在 `/home/IC/Desktop/tsmc/...`，旧脚本跳过 `$HOME` 与 `/opt/eda/cadence`），补测试。
- `bench pdk-inventory`（0 次）：确认 CRN65LP 的 `toplevel.scs`、section（如 `top_tt`）、`nmos_rf` 端口数与参数（`lr/wr/nr/multi`）、VDD（1.2 V）、可用螺旋电感；
  结果写入 `config/model_paths.local.yaml`（用户可见，执行者写入后**不在对话中打印路径细节**）。
- 若 `nmos_rf` 端口数或参数名与 crn40lp 不同，在 `pdk_v2` / `pdk3` 中参数化（由配置决定），crn40lp 行为不变，补测试。
- `pdk-characterize`、`pdk-characterize3`、`pdk-characterize-casc`；拟合（`pdk_fit`；若 A1 后有 `bench pdk-refit` 则用之）。器件表放 git 忽略的 `results/runs/`。
- 写 `docs/132_n65_bringup.md`（只写结论与指标，不写 PDK 器件参数），记账，提交。

### N2 冒烟（**需确认**，≤120 次）
- `bench pdk-check --spec S2`，然后 S1–S8 seed 0（v1 规则策略、1 h、`--backend pdk`），与 crn40lp 的 docs/127 §5.1 对照。失败先分析原因，不盲目重跑。

### N3 v1 基线（**需确认**，≤550 次）
- **时机**：N2 冒烟通过后立即做，与 A2 并行；必须在 A3 第 2 步之前完成。
- 内容：S1–S8 × 5 seed，v1 规则策略，论文口径 1 h，`ORFADC_AGENT_IMPL=v1`，记录代码提交哈希。用 `scripts/run_job_queue.cmd -Queue <n65 队列>` 后台跑，长任务分批。
- 汇总：N65 pass@1 表（与论文 Ours 32/40、crn40lp 34/40 同表），写入 `docs/132` §结果，记账，提交。
- 可选：用 PDK 螺旋电感替代理想匹配电感，复查 S7（docs/126 的瓶颈），单独记账并标注。

## 5. 收尾（**需确认**）
- 更新 README、CLAUDE.md（v1/v2、crn40lp/N65 说明与命令）；用户确认后打标签 `v2-agentic-alpha`，推送分支与标签（不强推）。

## 6. 汇报格式
中文：做了什么、改了哪些文件、测试与比对结果（数字）、本阶段与累计 Spectre 次数（N65 账本）、LLM 调用次数、未解决问题、下一阶段是否需确认。
不把代理结果写成 PDK/硅结果；不在汇报中出现密码、私钥或 PDK 器件参数。
