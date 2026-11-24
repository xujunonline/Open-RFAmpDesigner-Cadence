# 十一月环境验收记录

本文件按发生顺序收录两次验收。第 1 节至原交接记录末尾对应云端 Linux。最后一节记录同日原 Mac 的实际接通结果。

日期：2026-11-23（Asia/Shanghai）。用户要求：接通原 Mac 环境，把当前可运行的部分跑一遍，权限集中处理。

## 1. 实际完成情况

**当前 Linux 工作环境的离线复现管线已完成一次全面功能运行；原 Mac / IC618_rf 仍未接通，真实 LLM 也没有取得模型响应。** 本轮未修改 `src/`，保留 11 月 19 日的 S5 独立提示开关；源码基准 HEAD 为 `f198922b9d912d2498088d0a6f0218c1462df8e1`，工作分支 `work/s5-offline-diagnosis-20261119`。各运行记录包含实际源码 SHA256，而非仅以 HEAD 代表未提交改动。

完成 147 项离线回归、v1 完整 benchmark、v2 scripted 规格矩阵及扩展、KB/EB 预载检查、MCP 注册、Codex 登录与在线链路诊断。正式设计尝试共 **106 次**：v1 all 86 次 + 独立 S2 smoke 1 次 + v2 验证 19 次；不含单测内部设计调用和 Fig.5 子工具评估。所有新电路结果均为 **surrogate / trend-level**。新增 Spectre 仿真为 **0**；没有成功的真实 LLM 生成响应。

“能执行完流程”和“电路满足所有规格”分别记录；失败设计保留 exit 3、违规量和实际停止原因。

## 2. 运行环境与连接边界

| 项目 | 本轮实际观察 |
|---|---|
| 执行系统 | Linux x86_64；不是用户 Mac |
| Mac 文件挂载 | `/Users`、`/Volumes`、`/Applications` 均不存在 |
| 本机控制能力 | 当前工具中没有原 Mac 的终端/文件系统连接；插件检索也未返回可用的对应能力 |
| 原 VM 配置 | 当前工作副本不存在 `config/remote_cadence.local.yaml`、`config/model_paths.local.yaml`；只检查存在性，未读取私密内容 |
| Codex CLI | `0.172.0-alpha.2`，登录状态显示 ChatGPT 已登录 |
| Claude CLI | 当前 PATH 未找到 |
| API 传输 | `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 均未配置；只检查是否存在，未切换 API 计费 |
| Python 与依赖 | Python 3.12.14；numpy 2.3.5；scipy 1.17.0；PyYAML 6.0.3；matplotlib 3.10.8；mcp 1.29.0；pytest 9.2.0 |

没有凭历史 DHCP 地址去连接某个私网主机，也没有新建或替换 VM。原 Mac 路径仍是历史定位证据，待现场核实：项目 `/Users/jason/Documents/Open-RFAmpDesigner-Cadence`，VM `/Users/jason/Desktop/IC618_rf/IC618_rf.vmx`。

## 3. 离线软件与接口验证

| 检查 | 结果 |
|---|---|
| 全量 `pytest tests -q` | **147 passed**，81.14 秒，2 条既有依赖警告 |
| benchmark 前核心检查 | 14 passed，17.36 秒 |
| RFamp MCP | 10 个工具注册成功，包含 Stage 1–4、会话、导出、记忆与自动设计 |
| Codex bridge MCP | `codex_ask`、`codex_status` 注册成功 |
| fake CLI → MCP → transport | 全量测试通过；不等于真实服务连通 |
| S2 v1 smoke | 电气指标通过，1901.15 等效秒；该次模型 CPU 计时约 3.97 秒 |

命令与原始记录：`results/runs/environment_20261123/validation/verification.json`、`pytest_full.log`；`offline_bench/core_tests.log`、`smoke/smoke_S2.json`。两条警告仍来自 anyio 的 pytest API 兼容及 pydantic_settings 类型注解，没有测试失败。

## 4. v1 全套表图、优化器和自进化

执行命令：

```bash
PYTHONPATH=src MPLBACKEND=Agg OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -u -m orfadc.repro.bench all --seeds 1 --workers 4 \
  --out results/runs/environment_20261123/offline_bench
```

保持原等效 EDA 预算、Q_MATCH=25、Q_IND=15、顺序记账、v1 规则与 surrogate 后端；完整命令设置见 `offline_bench/run_status.json`。`all` 命令不切换为 v2。本轮 **exit 0，墙钟 362.99 秒**，覆盖：

- Table IV：S1–S8 × 5 方法，共 40 次设计。
- Table V：S9/S10/S9s/S10s × 5 方法，共 20 次设计，含无 Refiner 与带 EB 分支；另有 8 次隔离记忆库预训练。
- Fig.10：六个增益任务 × 3 方法，共 18 次设计。
- Fig.5 多保真与纯仿真对比、Eq.3 两种形式；Fig.7/8 从新数据出图。

### Table IV：单 seed 的全部指标通过数

| 方法 | 通过数 |
|---|---:|
| v1 ours | **5/8** |
| GA vanilla | 1/8 |
| BO vanilla | 2/8 |
| GA subtool | 1/8 |
| BO subtool | 0/8 |

v1 通过 S1、S2、S4、S5、S8；S3 剩余 NF/IP1dB 违规，S6 有多项折中，S7 仍有 NF/纹波/IP1dB 违规。原始记录在 `offline_bench/raw/table4_runs.jsonl`。

### Table V：原难规格与缩放规格分开

| 规格 | GA subtool | BO subtool | v1 ours | 无 Refiner | 带 EB |
|---|---|---|---|---|---|
| S9 | 未过 | 未过 | 未过 | 未过 | 未过 |
| S10 | 未过 | 未过 | 未过 | 未过 | 未过 |
| S9s | 通过 | 未过 | 未过 | 未过 | 未过 |
| S10s | 通过 | 通过 | 未过 | 未过 | 未过 |

每格一个 seed。缩放任务通过不能记为原 S9/S10 通过；所有流程完成不表示全部电路达标。

### 自进化与多保真

Fig.10 的六任务中，v1 + KB/EB **6/6**、GA **5/6**、BO **6/6**；累计等效时间分别为 3392.53、14916、5628 秒。Fig.5 多保真与纯仿真的等效成本为 38.264 与 4344 秒，成本模型下降约 99.119%。这些不是 Mac 墙钟加速或 PDK/硅结果，也不是论文 88% 数值的精确复现。

### 旧离线基线恢复核对

与 `results/repro/2026-10-03/raw/` 对应 seed0 对照，Table IV 的 40 次和 Table V 的 20 次通过/失败及非 CPU 仿真记账全部一致；指标最大绝对差分别约 1.49×10⁻¹¹、7.11×10⁻¹⁵。Fig.10 的三组逐任务记录完全一致。

另执行 `bench replot`，exit 0、1.17 秒，重画前后原始文件与表格 SHA256 不变。它只重建其支持的 Table IV、Fig.7/8 和 SUMMARY，未重新模拟 Table V 或 Fig.5/10。完整证据：`offline_bench/execution_summary.json`。

## 5. v2 scripted 全规格与实际记忆预载

mode1 固定 seed0、默认 rev1、s11bt=0；S1–S8 的等效预算 3600 秒，其他四项 18000 秒。scripted 只是本地规则 oracle，没有真实 LLM 推理。

| 规格 | 默认 200 次 scripted 护栏下结果 | 实际停止原因 | 调用数 | 等效 EDA 秒 |
|---|---|---|---:|---:|
| S1 | 通过 | spec_met | 74 | 1712.79 |
| S2 | 通过 | spec_met | 66 | 2035.79 |
| S3 | 未过 | eda_budget | 114 | 3600.65 |
| S4 | 通过 | spec_met | 76 | 2315.19 |
| S5 | 未过 | eda_budget | 112 | 3600.16 |
| S6 | 未过 | eda_budget | 117 | 3600.04 |
| S7 | 未过 | eda_budget | 115 | 3600.38 |
| S8 | 通过 | spec_met | 64 | 2134.92 |
| S9 | 未过 | llm_call_cap | 200 | 5920.67 |
| S10 | 未过 | llm_call_cap | 200 | 6738.65 |
| S9s | 未过 | llm_call_cap | 200 | 5544.46 |
| S10s | 未过 | llm_call_cap | 200 | 6552.85 |

12 次全部生成结果，0 错误、0 非法动作，合计 4/12 电气通过。末四项没有用满 18000 等效秒。

仅对这四项的具体限制做一次扩展：提高 scripted 护栏到 1000，其余设置保持，输出独立的 `validation/v2_matrix_extended`，保留默认记录。

| 规格 | 扩展结果 | 调用数 | 等效 EDA 秒 | 实际停止原因 |
|---|---|---:|---:|---|
| S9 | 未过 | 477 | 14023.34 | Manager max_steps=60 |
| S10 | 未过 | 396 | 12999.97 | Manager max_steps=60 |
| S9s | 未过 | 565 | 16329.66 | Manager max_steps=60 |
| S10s | 未过 | 530 | 15399.62 | Manager max_steps=60 |

四项前 200 条 role+response 都与默认基线一致；确实延续原 scripted 轨迹。扩展后触及 Manager 步数限制，仍不能宣称完整五小时搜索后证明不可行。本轮没有继续改变其它护栏。

### S5 新提示隔离检查

默认与 s11bt=1 各跑一次 S5，设计、指标、数值记账完全一致，符合“只改真实 LLM 提示”的实现。两次均因纹波超限 2.8129 dB、IP1dB 差 0.8628 dB 未过；S11 已达到 −10.5302 dB。这是 surrogate 的失败情况，不能当作历史 N65 的同一个 S11 瓶颈，也不能评价真实 LLM 对新提示的响应。

### Mode2 实际写入与预载

S2 mode2 seed0→seed1 使用独立新记忆目录，两次均通过。第一次 67 次 scripted 调用、2035.79 等效秒；第二次出现 1 次 `kb_preload`、0 次 Searcher，仅 4 次 scripted 调用、88.50 等效秒。最终 KB、EB 各 4 条。证明该例中的存储/检索/预载流程可用，不外推一般性能收益。

完整记录：`validation/verification.json`、`validation/v2_matrix/matrix_verification.json`、`validation/v2_matrix_extended/extended_verification.json`。

## 6. 真实 LLM 连接：登录有效，但执行未成功

先执行项目的 `bench llm-check --policy codex-mcp`。它尝试 ping 和一次 Refiner 决策。两次都在 CLI 初始化阶段失败：

```text
failed to initialize in-process app-server client: Read-only file system (os error 30)
```

该命令真实 exit 4、`ok=false`、`from_llm=false`。其中记录的 `rerun_stage3` 是 v1 的规则回退，**不能算作模型已回答**。

只读的 `codex doctor --json` 确认认证已配置、Responses WebSocket 握手成功；运行时状态目录处于只读挂载。按 CLI 的公开配置项把 sqlite/log 路径指向本任务可写目录后，再做一次独立探测，仍以相同初始化错误退出，输出回答文件为空。没有修改认证文件、全局权限策略或项目 transport 来隐藏失败。

因此目前的结论是“当前嵌套 CLI 运行环境不可用”，不是账号未登录，也没有证据说模型额度用尽。当前未启动真实 LLM 设计批次。Claude 因程序缺失也没有运行。诊断摘要在 `results/repro/environment_20261123/connectivity_summary.json`；原始错误在 `results/runs/environment_20261123/connectivity/llm_check_codex-mcp.json`。

## 7. 接入原 Mac：一次性需要的现场能力

当前缺的是 **原 Mac 的命令执行入口**。提高云端 Linux 权限不会建立该入口；不要求把本地密钥、认证文件、私有配置或 VM 磁盘上传。

在原 Mac 的本地 Codex / 终端中执行时，统一处理实际缺少的权限：

1. 读写目标项目及独立结果目录，访问 Desktop 下原 IC618_rf 文件夹。
2. 使用 VMware Fusion / vmrun，必要时启动已确认的原 VM。
3. 运行本地执行器的本地网络访问，以 SSH 到所选 VM。
4. 本地使用已有 SSH 身份、Spectre 许可证、N65 配置/缓存及已登录 CLI。

不笼统索取完整磁盘访问或管理员密码。需要网页登录、验证码或 SSH 主机身份确认时，由用户在本机完成。实际 hook/审批若阻挡，应说明其来源并集中处理，不绕过或停用规则。

### 已准备的本机接入包

`rfamp_mac_handoff_20261123.zip` 包含启动器、完整任务说明和已验收的接手/S5 补丁。解压到 Downloads 后运行：

```bash
bash ~/Downloads/rfamp_mac_handoff_20261123/start_mac_environment_20261123.sh
```

启动器只在 Darwin 执行；检查目标仓库、Codex CLI 和包内文件；补丁可干净应用时应用，已存在时跳过，冲突时保留全部现场文件交给本地 agent 合并；随后使用既有认证和审批设置启动本地 Codex 任务。未禁用沙盒、hooks 或审批。启动器已通过 Bash 语法检查，并在当前 Linux 验证会立即以 exit 2 拒绝运行；**尚未在用户 Mac 实测**。

若项目目录已移动，可将实际路径作为启动器第一个参数；未找到原目录时不创建同名空项目。

### 原机首次真实试跑的具体包络（尚未执行）

| 步骤 | 新增 Spectre |
|---|---:|
| 核对 VM 动态 IP、SSH 只读 probe、工具版本 | 0 |
| S2 `cadence-check` 宏模型交叉核对 | 固定 3 |
| N65 S5 seed0，v2 + s11bt | 最多 60 |
| **首批总包络** | **最多 63** |

S5 设计 LLM 护栏 1000 次；另有 Codex 连通检查通常两次请求，失败尝试/传输重试单独记账。这是新批次，不扣用封版账本“剩余 156 次”。`cadence-check` 的固定三次来自代码路径，其直接调用不经过 `ToolContext` 的每设计护栏；后续 design 路径才执行该护栏。

使用 vmrun 当前返回地址，不盲用历史私网 IP；VM 用户为 IC。N65 运行前核对配置及器件/Y3 缓存来源和工艺角，`--backend pdk` 和结果 `labels.pdk` 都不能单独保证缓存身份。连接中断或状态不明时先查远端结果，不自动重派。完整现场说明在 `scripts/mac_environment_handoff_20261123.txt`。

## 8. 交付与重算

本轮机器总表：`results/repro/environment_20261123/environment_summary.json`。

原始日志、单 seed 设计、表图、记忆样例与 SHA256 记录打包为 `rfamp_execution_20261123.zip`，排除 pytest 临时目录、CLI 运行时数据库和认证信息。所有报告中的性能数字只来自本轮真实生成的原始文件。

后续真实 N65 成功率仍须在原 Mac 接入后验证；本轮的离线通过和历史基线一致性可以支持继续开发，不能代替该现场验收。

## 同日原 Mac 首次验收

在原 Intel Mac 上确认历史仓库及正在运行的 IC618_rf。使用现有 SSH 与 CLI 登录，确认 Spectre 18.1.0.077、N65 缓存与真实模型响应。S2 宏模型与 Python 两端口引擎核对通过，三次 Spectre 均成功。中心增益 27.3260 dB、中心 NF 4.1440 dB，三次 Spectre 墙钟合计 8.4 秒。

S5 使用 N65 标称后端、seed0 和 S11 回退提示。最佳方案 D017 的最低增益为 21.8976 dB，比下限低 0.1024 dB。最差 S11 为 −10.9956 dB，其余五项均通过。此批 19 次 Spectre 包含 S2 的 3 次与 S5 的 16 次。成功设计 LLM 请求 87 次，另有 2 次连通检查成功、4 次超时与 3 次模型名错误。后续续调另见 [145 号工作日志](145_s5_verified_run_2026-11-23.md)。

本机可按仓库相对路径核对宏模型记录 `results/runs/environment_20261123/mac_cadence_check`、S5 任务 `results/windows_checks/20261123T143737_job` 和原始仿真 `results/runs/repro_cadence_pdk/20261123T143738_550b60`。
