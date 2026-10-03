# 115 路线 A：与 Cadence 解耦的可运行复现（orfadc.repro）

> 结论先行：论文的**方法**（资源分配式多保真工具中间件 + Manager/Searcher/Refiner + KB/EB 自进化）
> 已在本仓库端到端可运行，并在开放代理仿真器上复现了论文的主要**趋势**。
> 代理仿真器不是 TSMC N65 PDK，所有数字都是 *surrogate / trend-level*，不得当作 PDK 或硅结果引用。
> 结果表见 §6（由 `python -m orfadc.repro.bench all --seeds 5` 生成，原始档在 `results/repro/2026-09-29/`）。

## 1. 为什么需要路线 A

`docs/16`、`docs/113–114` 表明实机链路长期停在远程 SSH/隔离与 PDK 物理资格门槛上，
方法层（Stage 3/4、基线、表图）没有任何可运行实现（见 `docs/116` B01/B02）。
路线 A 把"仿真器"抽象为 `tools.Backend` 协议：先用开放代理模型把方法跑通、测通，再按同一协议换成 Cadence。

## 2. 论文 → 代码映射

| 论文 | 代码 | 说明 |
|---|---|---|
| Fig. 3 三级 LNA | `repro/circuit.py::_chain` | 并联 Lpar + 串联 Lg 的 L 匹配 → 共源共栅（Ls 退化）→ MCR1 巴伦 → 中和差分 CS → MCR2 → 中和差分 CS → MCR3 → 1787 Ω‖62 fF |
| Sec. II-A 知识库 | `repro/device.py::knowledge_database` | cascode W 45–180 µm、diff W 45–117 µm（步长 9）、Vb 300–500 mV（步长 25 mV）；代理 EKV 类器件 |
| Table I Active sizing | `tools.active_sizing` | 功率比 → 各级电流 → 临界/非临界组各取最大/最小器件 → 4 个配置（不超预算） |
| Table I Impedance matching / Eq.(1) | `tools.impedance_matching` | PSO（8×8）优化 k,L1,L2,R1,R2,C1,C2,Ls（Table II 范围）；每个粒子两次仿真：无匹配取 Zin → Smith 圆图 L 匹配 → 带匹配求 NF/S11 |
| Table I Band planning / Eq.(2)(3) | `tools.band_planning` + `mcr_eq3.py` | SA 优化 MCR2/MCR3 的 k, ω0∈[ωL,ωH], Q0∈[0.1,8], C∈[C_par,200 fF]；Eq.(3) 低保真 + HF 残差校准（多保真）；二分法映射到物理 L/R/C |
| Table I Fullchain evaluation | `tools.fullchain_evaluation` | 带内 S21/S11/NF/NFmin 扫描 + fc 处 IP1dB + 功耗 → spec_check |
| Sec. II-B-4 回溯策略 | `agents.RulePolicy.refine_action` | NF→加 headroom 或要求 stage2 增益；IP1dB→按压缩级/机理重分配增益；增益/纹波→重规划；不可修→升级到 Stage 1 |
| Sec. II-C Mode 1 | `agents.RFAmpManager/Searcher/Refiner` | Searcher：4 配置 ×{无约束, 增益约束}；Manager：打分排序、每个功率分配取前 3、按瓶颈重分配电流 |
| Sec. II-C Mode 2、KB/EB | `repro/memory.py`、Manager `_preload_from_kb` | JSONL 持久化；按规格距离检索 top-k 预装队列；EB 给初始 headroom/关键增益/功率比 |
| ReAct / LLM 主干 | `repro/llm.py` + `repro/prompts/*.md` | `<think>…</think><tools>{JSON}</tools>`；Claude / OpenAI 兼容 / 离线 scripted；非法输出回退并计数 |
| Baselines (Sec. III-A-3) | `repro/baselines.py` | GA/BO-vanilla：18 维物理空间；GA/BO-subtool：14 维（工具综合关键级 + 8 个 MCR 变量） |
| Table IV/V、Fig. 5/7/8/10 | `repro/bench.py` | 见 §6 |
| MCP 工具中间件 | `repro/mcp_server.py`、`.mcp.json` | Claude Code 可直接担任 RFAmpManager |

## 3. 代理仿真器（"high-fidelity" 后端）

- **两端口 + 噪声相关矩阵**（`twoport.py`）：每个模块给出 ABCD 与 ABCD 形式噪声相关矩阵，按
  Hillbrand–Russer 级联；无源网络 `C_Y = Re(Y)`；由此得到 S21（定义为 2·V_load/V_s）、S11、NF、NFmin。
- **器件**（`device.py`）：EKV 插值 Id(W,Vgs)、θ 迁移率退化、λ=0.45 V⁻¹、Cgs/Cgd/Cdb 每微米值、
  Rg=90 Ω·µm/W；噪声 γ=1.1、δ=2γ、c=0.395j（van der Ziel）。W=100 µm, Vb=0.5 V 时 Id≈12 mA、fT≈120 GHz。
- **级**：stage1 为 CS（串联反馈 Ls）+ 0.45W 的 CG；stage2/3 为差分半电路，中和后残余 Cgd 12%；
  电感 Q=15（MCR）、Q=25（匹配）。
- **压缩**：每个器件取 gm 三阶压缩、电流削顶、电压摆幅三种极限；硬削顶在驱动为削顶电平
  **1.26 倍**时基波下降 1 dB（(2/π)(asin x + x√(1−x²)) = 0.891 的解）；各级按输入参考功率求和。
- **成本模型**（`tools.EQUIV_COST_S`）：关键级单点仿真 0.5 s、全链宽带 SP+noise+HB 12 s、Eq.(3) 计算 0.002 s；
  与论文一致按顺序执行统计（`ORFADC_PARALLEL=1` 可改为并行记账）。预算：S1–S8 3600 s，S9/S10 18000 s。

## 4. 与论文的已知偏差

1. 器件/无源为开放代理模型，绝对 NF/IP1dB 与论文 N65 后仿不同；只比较方法之间与规格之间的相对趋势。
2. 默认用规则策略替代 LLM 做 Mode 1/2 的决策；LLM 主干已用订阅额度实跑（Claude Pro `claude-cli`、ChatGPT `codex-mcp`，见 §6.2b 与 docs/119），seed 0 两条通道都跑了，Codex 另补 seed 1–4（docs/119 §4.2）；每次运行最多 40 次调用。
3. subtool 基线为 14 维（论文 16 维），因为我们的 Stage 2 工具吸收了两个变量。
4. ADO-LLM、AnalogCoder 基线需在线 LLM，未在离线表中运行。
5. Eq.(3) 采用补 `s` 的推导式并去掉单端等效下的 "/2"（误差量化见 §6.3）。

## 5. 复现命令

见 `docs/117_step_by_step_runbook.md`。全部表图：

```bash
PYTHONPATH=src python -m orfadc.repro.bench all --seeds 5 --out results/repro/2026-09-29
```

## 6. 结果（2026-09-29，5 seeds，2 CPU）

原始档：`results/repro/2026-09-29/raw/*.jsonl|json`；表：`tables/*.md|csv`；图：`figures/*.png`；汇总：`SUMMARY.md`。

**v1 封版复核（2026-10-03）：** 用当前代码在 Windows 宿主上重跑 `bench all --seeds 5`（作业 `20261003T023155_job`，约 3 h），结果放在 `results/repro/2026-10-03/`。
Table IV-like、Table V-like、Fig. 10 的原始档与 2026-09-29 **完全一致**；Fig. 5 只有 1e-14 量级的浮点尾差和 CPU 计时不同。因此本节数字对 v1 代码仍然有效。
核验：表格由 `bench replot` 从原始档重算；全部 22 个"ours"成功运行及所有基线成功运行的 metrics 都逐项满足对应 spec（0 例违规）。

### 6.1 Table IV-like（S1–S8，1 h 等效预算，5 seeds）

| Spec | GA-vanilla | BO-vanilla | GA-subtool | BO-subtool | **Ours (rule)** | 论文 Ours |
|---|---|---|---|---|---|---|
| S1 10 GHz | 0/5 | 0/5 | 0/5 | 1/5 (3506 s) | **5/5 (1833 s)** | 5/5 (655 s) |
| S2 30 GHz | 1/5 (3540 s) | 4/5 (774 s) | 0/5 | 2/5 (2984 s) | **5/5 (994 s)** | 5/5 (620 s) |
| S3 50 GHz | 0/5 | 1/5 (3384 s) | 0/5 | 0/5 | 0/5 | 3/5 (2307 s) |
| S4 10 % BW | 3/5 (2804 s) | 5/5 (1114 s) | 1/5 (2854 s) | 4/5 (1570 s) | **5/5 (1004 s)** | 5/5 (682 s) |
| S5 60 % BW | 0/5 | 1/5 (1080 s) | 0/5 | 0/5 | **4/5 (1932 s)** | 4/5 (904 s) |
| S6 80 % BW | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 2/5 (765 s) |
| S7 NF≤2.5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 3/5 (1401 s) |
| S8 15 mA | 0/5 | 0/5 | 0/5 | 0/5 | **3/5 (1903 s)** | 5/5 (760 s) |
| **合计** | 4/40 | 11/40 | 1/40 | 7/40 | **22/40** | 32/40 |

复现程度：**趋势一致**——在至少有一种方法成功的 6 个任务中，工具中间件 + 三智能体在 5 个上取得最高或并列最高的 pass@1（唯一例外 S3：BO-vanilla 1/5），
总成功数 22/40 为最佳基线（BO-vanilla 11/40）的 2 倍；难度排序（S1/S2/S4 易，S3/S6/S7 最难）与论文一致。
差异：绝对时间约为论文的 1.5–3 倍（等效成本模型不同）；S3/S6/S7 在代理模型上 0/5（论文 2–3/5），
其中 S7（NF≤2.5 dB）在代理器件上 8 000 次评估的 GA 也未找到可行点（最佳 NF 3.0 dB），S6/S3 为高频/超宽带下的增益–纹波–线性度三重约束。
论文中 BO-vanilla 在 S2 仅 1/5；本代理上 BO 在 30 GHz 窄/中带任务上较强（S2 4/5、S4 5/5），说明代理的可行域比 N65 后仿更"平滑"。

### 6.2 Table V-like（S9/S10 及代理缩放版 S9s/S10s，5 h 预算，消融）

| Spec | GA-subtool | BO-subtool | Ours | Ours w/o Refiner | Ours + EB |
|---|---|---|---|---|---|
| S9（IP1dB≥−15） | 0/5, viol 1.94 | 0/5, 1.64 | 0/5, 2.18 | 0/5, 2.48 | 0/5, 2.18 |
| S10（NF≤3.5, IP1dB≥−15） | 0/5, 2.23 | 0/5, 2.46 | 0/5, 3.23 | 0/5, 3.18 | 0/5, 3.23 |
| S9s（IP1dB≥−20） | 1/5, 0.37 | 1/5, 0.61 | 0/5, 0.83 | 0/5, 0.54 | 0/5, 0.83 |
| S10s（NF≤4, IP1dB≥−21） | 2/5, 0.23 | 3/5, 0.17 | 0/5, 0.58 | 0/5, 0.63 | 0/5, 0.58 |

复现程度：**未复现**。代理器件在 30 mA、25 dB 增益下的线性度前沿约 −19.7 dBm（NF 5 dB）/ −21.9 dBm（NF 3.6 dB），
论文的 −15 dBm 目标在此模型上不可行；缩放到前沿附近后，确定性规则策略也不如预算更长的 subtool GA/BO。
这正是论文把 S9/S10 的成功归因于 LLM 推理（Table V 各 backbone 5/5）的部分——下一步是 `docs/118` P7 的 LLM 主干实验。
#### 6.2b LLM 主干（订阅额度，seed 0，每次 ≤40 次调用；2026-10-01，Windows）

| Spec | rule | Claude（Pro，claude-cli） | ChatGPT（Codex，codex-mcp） |
|---|---|---|---|
| S9 | 0/1, viol 2.63 | 0/1, 2.36（12 次调用后主动停止） | 0/1, **1.99** |
| S10 | 0/1, 3.24 | 0/1, **2.83** | 0/1, 3.72 |
| S9s | 0/1, **0.27** | 0/1, 1.48 | 0/1, 0.96 |
| S10s | 0/1, 0.81 | 0/1, 1.37 | 0/1, **0.68** |

271 次模型决策全部合法（0 非法、0 错误）。单 seed 下三者互有胜负，**不构成** Table V 的复现结论；
需要 5 seed、更高调用上限，以及更强的器件前沿（v2 PDK）才可能让 S9/S10 变得可行。原始档：`results/repro/llm_live/windows_20261001/`。

**5 seed 更新（Codex，docs/119 §4.2）：**
- 四个规格 0/20 通过，规则策略同样为 0。
- 按"最佳评估"违规比较：
  - Codex 在 S10 上 5/5 个 seed 优于规则（2.57 对 3.13）。
  - S9 两者持平（1.80 对 1.78）。
  - S9s/S10s 规则更好（0.22 对 0.33，0.28 对 0.64）。
- 在 40 次调用上限下，**不**支持"LLM 主干显著优于基线"的 Table V 结论。
- 汇总：`results/repro/llm_live/codex_5seed_20261002/`。

**不封顶更新（Codex，docs/119 §4.3）：**
- 第一轮在 seed 3 用尽 ChatGPT 额度，额度恢复后补跑了 seed 3–4，S9s、S10s 各 5 个有效 seed。
- 按"最佳评估"违规均值：S9s 0.46（封顶 0.33，规则 0.22）；S10s 0.61（封顶 0.64，规则 0.28）。
- 10 次中 9 次 Codex 在预算用到 30–50 % 时主动停止，取消调用上限并没有换来更多搜索。
- 结论不变：**不**支持 Table V。汇总：`results/repro/llm_live/codex_uncapped_20261002/`。

"Ours + EB" 与 "Ours" 相同：KB/EB 由 S1–S8 预训练，按输出参考线性度的检索距离均 > 0.8，检索被正确地拒绝（避免用 −25 dBm 的设计去引导 −15 dBm 任务）。

### 6.3 Fig. 5-like（多保真频带规划、Eq.(3)）

- 多保真 SA：3 次全链仿真 + 约 2000 次 Eq.(3) 计算即满足 Eq.(2)；纯仿真 SA 用 362 次全链仿真。
  等效时间 38 s vs 4344 s（**−99 %**；论文 −88 %）。**趋势一致**。
- Eq.(3) 各级增益相对 HF 仿真的误差（60 个随机 MCR 点）：印刷版（含 /2）均值 −2.4 dB、标准差 9.8 dB；
  补 `s` + /2：−7.1 ± 2.0 dB（/2 带来的恒定 −6 dB）；补 `s`、单端等效（默认）：−1.2 ± 2.2 dB（rms 2.5 dB）。
  印刷版的大离散度正是分母漏 `s` 的后果；论文称单个 MCR 约 3 % 偏差，与修正式的量级相符。

### 6.4 Fig. 10-like（自进化：增益 20→45 dB，IP1dB = −(G+5) dBm，窄带 30 GHz，3 seeds）

| 方法 | 解决任务 | 累计等效时间 | 每任务平均（s） |
|---|---|---|---|
| Ours（Mode 2, KB/EB 累积） | 18/18 | **3348 s** | 1860, 297, 97, 93, 111, 891 |
| BO-vanilla | 16/18 | 5292 s | 2712, 512, 1088, 236, 352, 392 |
| GA-vanilla | 14/18 | 11620 s | 3600, 2648, 1756, 1112, 1180, 1324 |

复现程度：**趋势一致**。冷启动后记忆复用使每任务成本下降一个数量级，遇到 45 dB 新约束时出现探索峰
（论文所说"锯齿"）；累计成本比 BO 低 1.6×、比 GA 低 3.5×（论文报告 5.5× 采样效率）。

### 6.5 Fig. 7/8-like

`figures/fig7_like.png`（S1–S3、S4–S6 的 S21/S11，NF/NFmin），`figures/fig8_like.png`（S1/S2/S4 平均完成时间与极差）。

## 7. 下一步

1. LLM 主干（`--policy claude-cli|codex-mcp`，订阅额度）扩展到 5 seed，并在 S3、S6、S7 上与规则策略对比（`docs/118` P7）。
2. `CadenceBackend` v1 已在真实 Spectre 上验证引擎（docs/119 §4.1）；v2 用 PDK 器件与 OCEAN 知识库替换代理器件库（docs/120）。
3. 代理模型可调参数（`TechParams`、`Q_IND`）的敏感性分析，写入本文件。
