# 132 N65（IC618_rf）接入记录

> docs/130 B 线（N0–N3）的执行记录。执行机器：Intel MacBook（x86_64，macOS 26.5），虚拟机 IC618_rf 在本机 VMware Fusion 上运行（docs/134）。
> 本文只写结论与指标，**不写 PDK 器件参数、PDK 路径细节、密码或私钥**。N65 Spectre 账本：`results/repro/n65/spectre_ledger.csv`。

## 1. 离线准备（0 次 Spectre）

| 项 | 内容 | 测试 |
|---|---|---|
| `scripts/run_job_queue.sh` | `run_job_queue.ps1` 的 bash 版本，队列格式相同（`#` 注释、`set ORFADC_*=值`、每行一个 bench 子命令），日志同样写到 `results/windows_checks/<ts>_job/`（`progress.txt`、`NN_<cmd>.log`、`DONE.txt`）；兼容 CRLF；参数不做通配展开；失败只记录、不重派 | `tests/test_n65_tooling.py` |
| `pdk_inventory.sh` 可配置 | `ORFADC_PDK_ROOTS`（替换默认搜索根）、`PDK_EXTRA_ROOTS`（追加）、`ORFADC_CDSLIB_FILES`（额外 cds.lib）、`ORFADC_CDS_PREFIXES`（Cadence 安装前缀，其库不算 PDK；默认 `/opt/eda/cadence`）、`ORFADC_INV_SKIP_HOME`（默认 1）；输出新增 `##ROOTS`、`##CDS_PREFIXES` 两行 | 同上（用伪造的 CentOS 目录树在本机实跑脚本） |
| `bench pdk-inventory` 读配置 | 从 `config/remote_cadence.local.yaml` 可选的 `inventory:` 块（见 `config/remote_cadence.example.yaml`）生成上述环境变量，路径须为绝对路径、不含空格与 `..` | 同上 |

- 未设置这些变量时，搜索根与跳过规则同原脚本（crn40lp 行为不变）。唯一的变化是：LIBDIR 段现在也读取 `$HOME/*/*/cds.lib` 和额外配置的 cds.lib（原来只读前两层）。这只多列出库目录，不改动任何文件。
- 后台批量运行示例：`nohup scripts/run_job_queue.sh jobs/<队列>.txt >/dev/null 2>&1 &`，然后看 `progress.txt`。

## 2. N0 虚拟机与登录（完成，2026-10-07，0 次 Spectre）

- 虚拟机 IC618_rf 在 VMware Fusion 运行，网络为 NAT（vmnet8）。客体 IP 由 VMware Tools 报告，DHCP 租约与网卡 MAC 一致。
- 首次从 Claude Code 连接时 `No route to host`（ARP 不完整）。用户放行 macOS「本地网络」权限后连通。
- 专用密钥 `~/.ssh/ic618_rf`（ed25519，无口令）在 Mac 上生成；`ssh-copy-id` 由用户在终端里执行，密码由用户输入。
  主机 ED25519 指纹在首次连接时由用户确认。本地配置 `config/remote_cadence.local.yaml`（git 忽略）也由用户填写。
- **登录用户为 `IC`**：IC618_rf 上没有 docs/130 原定的 `userone` 用户（用户确认），所以必须改。`IC` 不是 root，PDK 就在它的家目录下。
- 验证（密钥登录，`BatchMode=yes`）：`echo ok` 正常；CentOS 7.9；
  非登录 shell 与登录 shell 都能找到 `spectre`（SPECTRE181，`spectre -W` 为 18.1.0.077）、`virtuoso`、`ocean`（IC618），都在 `/opt/eda/cadence` 下。
  因此 `remote_runner` 不需要额外的环境前缀；`pdk_inventory.sh` 的默认 Cadence 前缀 `/opt/eda/cadence` 也适用。
- 盘点注意：PDK 在登录用户的 `$HOME` 下，而盘点脚本默认跳过 `$HOME` 下的 cds.lib 库，需要在本地配置的 `inventory:` 块里设 `skip_home: false`。
- 安全：虚拟机密码弱，且曾在对话中出现，建议用户用 `passwd` 修改。执行者没有使用这个密码。

## 3. N1 盘点与表征（完成，2026-10-07，Spectre 75 次，累计 75/1500，预分配 ≤150）

### 3.1 盘点与器件选择（0 次）
- `ORFADC_INV_SKIP_HOME=0 bench pdk-inventory`：7 个 PDK 目录、70 个模型文件、60 个 nmos 候选。原始结果在 git 忽略的 `results/runs/pdk_inventory/`。
- 虚拟机上有 TSMC 65 nm LP（CRN65LP）的两套 Spectre 模型：v1.5（3.3 V IO）与 v1.7（2.5 V IO，与 docs/128 的 v1.7a 一致），另有 SMIC 等其他工艺。
  选 **v1.7**，`toplevel.scs` 的 `tt_lib` 角，前置 `pre_simu` 段（全局模型标志）。
- RF 管 `nmos_rf` 与 crn40lp 一样是 4 端口 `(d g s b)`。差异有两处：
  - **没有 `multi` 参数**：用 Spectre 子电路隐含的 `m`；
  - 模型分档为 `lr` 60–240 nm、`wr` 0.6–6 µm。
- 取值：`lr=60n`（N65 节点）、`wr=2.0 µm`（与 crn40lp 相同，在分档内）、VDD 1.2 V（N65 核心电压）。nr 2–64 全部通过校验。
- 写配置：新增 `bench pdk-config`，从盘点结果选出 toplevel/section/器件，写入 git 忽略的 `config/model_paths.local.yaml`，
  控制台不打印路径。执行者没有直接编辑这个文件（项目权限规则禁止）。

### 3.2 代码的参数化（crn40lp 行为不变，补测试）
| 改动 | crn40lp 默认 | N65 |
|---|---|---|
| `pdk_v2._inst` 倍数参数 `mult_param` | `multi` | `m` |
| `pdk_v2._header` 前置段 `pre_sections` | 无 | `[pre_simu]` |
| `pdk3.char3_netlist` 的 cs3 漏压 `vds_cs` | 0.5 V | 0.6 V（= VDD/2，与低 Vds 表一致） |
| 偏置网格 `vb_grid`（配置中已有的键） | 0.30–0.50 V | 0.375–0.675 V，步长 0.025 V（13 点） |
| `bench pdk-characterize --widths` | 全部宽度 | 用于单宽度探测 |
| `bench pdk-refit`（新） | — | docs/122 的拟合与大信号 1 dB 点，写 `<ts>_fit/`（0 次 Spectre） |

- **偏置网格的依据**：先做一次单宽度探测（W≈90 µm，7 次 Spectre）。
  - crn40lp 的网格 0.30–0.50 V 在 N65 上只覆盖 Id 0.14–3.0 mA、fT 15–63 GHz，太靠近亚阈区。
  - 代理模型（Vth 0.32 V）在原网格上对应 0.58–11 mA；N65 上同样的电流范围约为 Vgs 0.375–0.675 V。
- **修正一个 v1 遗留缺陷**：`pdk3.MODES` 含 `cs2`（数据来自 `twoport_rows`），而 `characterize3` 遍历 `MODES`，
  构建 `cs2` 网表时抛 `ValueError`（docs/123 的 12 次运行早于 `cs2` 加入）。现在只遍历 `CHAR3_MODES = (cs3, cg3)`。
  首次运行在报错前已完成 12 次 Spectre，这 12 次记账但结果不用（移到 `results/runs/pdk_char3_aborted/`）。

### 3.3 表征结果（原理图级、无版图寄生；器件参数不在本文）
| 步骤 | Spectre | 结果 |
|---|---|---|
| 探测 `pdk-characterize --widths 90` | 7 | nr 2–64 有效；挪到 `results/runs/pdk_char_probe/`，不参与建表 |
| `pdk-characterize --freqs 15,25,35,45,60`（Vds 1.2 V） | 22 | 16 宽度 × 13 偏置 = 208 行，0 失败 |
| `pdk-characterize --vds 0.6` | 16 | 208 行，0 失败 |
| `pdk-characterize3`（中止，见上） | 12 | 不用 |
| `pdk-characterize3` | 12 | 156 行（6 宽度 × 13 偏置 × 2 模式），0 失败 |
| `pdk-characterize-casc` | 6 | 78 行，0 失败 |
| `pdk-refit` | 0 | 两张表的拟合残差 RMS：中位数 0.047 / 0.049，最大 0.081 / 0.103（只有低 Vds 表 Vgs = 0.375 V 一列略超 0.1） |

- 全量 pytest 121 passed。v1 冻结：`replot` 的 Table IV 与 2026-10-03 一致（CSV 只差 Windows 的 CRLF 行尾，Markdown 逐字节一致）。
- 远程用时：每次 Spectre 约 2–3 s，N1 全部约 4 min。

### 3.4 边界
- 器件表按 Vds 选取最新、行数最多的一张，**不区分 PDK**。本机只有 N65 的表（crn40lp 的表留在 Windows），
  所以不会混用；若以后在同一台机器上切换 PDK，需要先把另一工艺的 `results/runs/pdk_char*` 移走。
- 第一级噪声标定 `NOISE1_SCALE = 1.2` 是在 crn40lp 上标定的；N65 是否适用，由 N2 的 `pdk-check` 检验。

## 4. N2 冒烟（完成，2026-10-07，Spectre 73 次，累计 148/1500，预分配 ≤120）

条件：N65 器件表（拟合版，加三端口 Y、差分级 Y2、共源共栅噪声）+ 理想无源（Q 默认值）+ HB，原理图级、无版图寄生；
agent v1 rule 策略；1 h 等效预算；**每设计 Spectre 上限 14**（受限条件，不是论文口径；为了不超出 N2 的 120 次预分配）。
标签 `agent_impl=v1`、`pdk=crn65lp`、`not_silicon_result`。原始档：`results/repro/n65/n2/`（设计 JSON、队列与进度；不含 PDK 路径）。

**引擎与 Spectre 核对（`pdk-check --spec S2`，2 次）**：同一设计在 Spectre 中通过（违例 0）。

| | 增益@fc | NF@fc | S11@fc | IP1dB |
|---|---|---|---|---|
| 引擎 | 28.63 dB | 4.92 dB | −27.3 dB | −19.0 dBm |
| Spectre | 29.14 dB | 4.56 dB | −39.7 dB | −20.4 dBm（HB） |

引擎的 NF 偏悲观 0.36 dB（`NOISE1_SCALE = 1.2` 在 crn40lp 上标定），S11 在 fc 附近都很深，差值不影响判定。

**S1–S8 seed 0（71 次）：4/8 通过**

| 规格 | N65（上限 14） | Spectre | 失败项 / 原因 | crn40lp seed 0（docs/127 §5.1） |
|---|---|---|---|---|
| S1 | ✅ | 1 | — | ✅ |
| S2 | ✅ | 2 | — | ✅ |
| S3 | ❌ | 14 | NF 违例 3.16 dB（NF@fc 8.16 dB）；NF 余量耗尽 | ✅ |
| S4 | ✅ | 1 | — | ✅ |
| S5 | ❌ | 14（达上限） | 纹波只差 0.18 dB；细化预算耗尽 | ✅ |
| S6 | ❌ | 14（达上限） | S11 差 4.07 dB、纹波差 1.89 dB、NF 差 0.2 dB | ❌ |
| S7 | ❌ | 14（达上限） | NF 差 1.52 dB | ❌ |
| S8 | ✅ | 11 | — | ✅ |

读法与边界：
- 这是受限条件下的冒烟，**不**作 pass@1 结论。三个失败设计在 14 次上限处停下，S5 只差 0.18 dB，不封顶时可能通过；N3 按论文口径不封顶（护栏 60）重跑 seed 0–4。
- S3 在 crn40lp 上通过，在 N65 上 NF 差得多（8.16 dB）。诊断见下（0 次 Spectre，用 N1 已存的 45/60 GHz 表征数据）。

**S3 诊断（fc = 50 GHz，带宽 20 %，NF ≤ 5 dB）：器件受限，不是工具或偏置网格问题。**
- S3 的 5 次细化、3 个候选在 Stage 4 的 NF 违例都是 3–5 dB（NF 8–10 dB），不是个别设计没搜到。最终设计三级都已用到网格上限 0.675 V。
- N65 RF nmos（Vds 1.2 V）在网格上限处 fT ≈ 110–120 GHz，fc/fT ≈ 0.43。
  单管 NFmin：45 GHz 为 2.1–2.9 dB，60 GHz 为 2.7–3.7 dB（W = 45–180 µm）。这还没算 Q = 25 的输入匹配损耗、共栅管噪声和后级噪声。
- 偏置从 0.6 V 提到 0.675 V，NFmin 只改善约 0.15 dB；把网格再向上扩，估计只能再得 0.1–0.2 dB，补不了 3 dB 的差距。
- 结论：S3 在本工艺/理想无源条件下接近器件极限，N3 照常按论文口径跑（不针对 S3 改网格）。论文（同为 N65）S3 为 3/5，平均用时最长（2307 s），也说明这是较难的规格。
- S6/S7 在两种工艺上都失败，与 docs/126 的结论一致（理想无源 Q 与宽带 S11/NF 的冲突）。

## 5. N3 v1 基线（进行中）

条件：与 N2 相同，但按论文口径**不封顶**（每设计护栏 60，没有触发）；agent v1 rule，1 h 等效预算，`pdk=crn65lp`，原理图级、无版图寄生。
按 seed 分批，用户在终端自己启动队列（自动模式分类器不允许执行者在后台启动批量远程仿真）。

### 5.1 seed 0（2026-10-07，Spectre 129 次，累计 277/1500；N3 已用 129/550）
原始档：`results/repro/n65/n3/seed0/`（队列：`scripts/jobs/queue_n65_n3.txt`）。

| 规格 | 结果 | Spectre | 等效时间 | 失败项 |
|---|---|---|---|---|
| S1 | ✅ | 1 | 376 s | — |
| S2 | ✅ | 2 | 603 s | — |
| S3 | ❌ | 33 | 3603 s | NF 差 3.16 dB（器件受限，§4） |
| S4 | ✅ | 1 | 540 s | — |
| S5 | ❌ | 36 | 3600 s | 纹波差 0.18 dB |
| S6 | ❌ | 30 | 3610 s | S11 差 4.07 dB、纹波差 1.89 dB、NF 差 0.2 dB |
| S7 | ❌ | 15 | 3600 s | NF 差 1.52 dB |
| S8 | ✅ | 11 | 1057 s | — |

- **4/8**，与 N2（封顶 14）完全相同：失败的四个设计把 1 h 预算用完，最终报告的设计与 N2 相同。说明 N2 的 14 次上限没有改变 seed 0 的结论。
- 按每个 seed 约 130 次估算：seed 1–3 约 390 次（N3 合计约 516，在 550 以内，队列 `scripts/jobs/queue_n65_n3_s123.txt`）；
  seed 4 会超出 N3 预分配，需单独确认（可用 N1/N2 节余 122 次与机动 130 次）。

**误操作重跑（不用于结果）**：用户两次误把 seed 0 队列又跑了一遍，共 184 次 Spectre，账本记为 `N3-dup`。
- 第 2 次完整跑完（129 次）：每个设计的 Spectre 次数与第 1 次完全相同，说明运行可以复现。
- 第 3 次在 S5 时终端退出（55 次）。之后查过虚拟机，没有残留的 Spectre 进程。
- 用户确认属于误操作，并同意 N3 超出 550 的预分配（含 seed 4）。

### 5.2 seed 1–3（2026-10-07，Spectre 280 次，累计 741/1500；N3 有效运行 409 次，另有重跑 184 次）
原始档：`results/repro/n65/n3/seed1-3/`（队列：`scripts/jobs/queue_n65_n3_s123.txt`）。每个 seed 都是 **5/8**；60 次护栏没有触发（单设计最多 34 次）。

| 规格 | seed 1 | seed 2 | seed 3 | Spectre（s1/s2/s3） | 失败项 |
|---|---|---|---|---|---|
| S1 | ✅ | ✅ | ✅ | 2 / 2 / 1 | — |
| S2 | ✅ | ✅ | ✅ | 1 / 1 / 8 | — |
| S3 | ❌ | ❌ | ❌ | 34 / 25 / 24 | NF 差 2.5–4.0 dB（器件受限，§4），并有增益或纹波违例 |
| S4 | ✅ | ✅ | ✅ | 1 / 1 / 6 | — |
| S5 | ✅ | ✅ | ✅ | 7 / 4 / 16 | — |
| S6 | ❌ | ❌ | ❌ | 28 / 31 / 31 | S11 差 3.7–7.7 dB，纹波差 1.8–2.3 dB |
| S7 | ❌ | ❌ | ❌ | 15 / 16 / 16 | NF 差 1.5–1.8 dB |
| S8 | ✅ | ✅ | ✅ | 2 / 1 / 7 | — |
| 合计 | 5/8 | 5/8 | 5/8 | 90 / 81 / 109 | |

**seed 0–3 合计 19/32**：S1、S2、S4、S8 4/4，S5 3/4，S3、S6、S7 0/4。

### 5.3 seed 4 与 N3 汇总（2026-10-07，seed 4 用 Spectre 96 次，累计 837/1500）
seed 4：**5/8**（S1/S2/S4/S5/S8 通过；S3 NF 差 1.94 dB，S6 S11 差 5.43 dB，S7 NF 差 1.5 dB）。原始档 `results/repro/n65/n3/seed4/`。

**N65 v1 基线 pass@1（论文 Table IV 口径：rule、1 h、5 seed、每设计不封顶）= 24/40**

| 规格 | N65 seed 0–4 | **N65 合计** | crn40lp（docs/127 §5.1） | 论文 Ours | N65 通过者平均等效时间 | 论文平均时间（墙钟） | N65 Spectre（N3） |
|---|---|---|---|---|---|---|---|
| S1 | ✅✅✅✅✅ | **5/5** | 5/5 | 5/5 | 383 s | 655 s | 7 |
| S2 | ✅✅✅✅✅ | **5/5** | 5/5 | 5/5 | 664 s | 620 s | 13 |
| S3 | ❌❌❌❌❌ | **0/5** | 5/5 | 3/5 | – | 2307 s | 144 |
| S4 | ✅✅✅✅✅ | **5/5** | 5/5 | 5/5 | 615 s | 682 s | 11 |
| S5 | ❌✅✅✅✅ | **4/5** | 4/5 | 4/5 | 1114 s | 904 s | 73 |
| S6 | ❌❌❌❌❌ | **0/5** | 0/5 | 2/5 | – | 765 s | 151 |
| S7 | ❌❌❌❌❌ | **0/5** | 0/5 | 3/5 | – | 1401 s | 79 |
| S8 | ✅✅✅✅✅ | **5/5** | 5/5 | 5/5 | 801 s | 760 s | 27 |
| **合计** | | **24/40** | **29/40** | **32/40** | | | **505** |

读法与边界：
- N65 与 crn40lp 的差距（24 对 34）**全部来自 S3**（0/5 对 5/5）。§4 的诊断：50 GHz 下 N65 RF 管 fT ≈ 110–120 GHz，NF 受器件限制。其余 7 个规格两种工艺逐项相同。
- S6、S7 在两种工艺上都是 0/5（论文 2/5、3/5）。原因与 docs/126 一致：理想无源 Q（匹配电感 Q = 25）和宽带 S11/NF 的冲突，不是搜索预算问题。
  可选的后续：用 PDK 螺旋电感替代理想匹配电感，复查 S7。虚拟机上有 EMX65 电感库，需另行确认 Spectre 次数。
- 各规格结果在 5 个 seed 之间很稳定（同一规格只有 S5 seed 0 例外，纹波只差 0.18 dB），60 次护栏一次也没有触发（单设计最多 36 次）。
- 本表是 v1（规则策略）在 N65 上的基线，A3 第 2 步的 v2 + LLM 在同一工艺、同一口径下与它比较。
  它是原理图级、无版图寄生的结果，**不能**填论文 Table IV 的"实测"位置；论文的时间是墙钟时间，本仓库是等效 EDA 时间，只能比较相对大小。
- Spectre：N3 有效运行 505 次（在 550 预分配以内）；另有误操作重跑 184 次（不用于结果）。N65 累计 837/1500。
