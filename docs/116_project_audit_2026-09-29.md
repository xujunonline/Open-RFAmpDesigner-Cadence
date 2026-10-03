# 116 项目全面审查与修正（2026-09-29）

范围：英文原文 `references/paper/RFAmpDesigner.pdf`（14 页）全文、`README.md`、`docs/` 全部 114 份文档的结构与最新状态（重点 00/15/16/113/114 与 audits）、`src/orfadc` 全部模块、`tests/` 154 个测试文件、`config/`、`circuit/`。
方法：离线全量回归实跑、论文公式数值推导复核、逐模块阅读核心工具与智能体代码。

## 1. 结论摘要

1. **论文主流程从未端到端跑通。** Stage 1–4 工具中只有 Stage 1（lookup 骨架）和代价函数 (1)(2) 可用；
   `tools/band_planning.py`（536 B）只对传入增益打分，`tools/fullchain_eval.py` 固定返回 `backend_unavailable`；
   `baselines/*.py`（65–235 B）、`plots/plot_fig*_like.py`（41–81 B）均为空壳。因此 Table IV/V/VI、
   Fig. 7–11 的任何一项都无法生成。
2. **工程重心偏离论文。** 最近 40 余份文档（docs/59–114）和约 60 个 `experiments/*` 脚本集中在远程 SSH
   断线恢复、pending 隔离栅栏、Virtuoso GUI 表单点击（Xvfb/Mutter 焦点）等基础设施问题，属于论文未涉及的
   工程保障；它们必要但阻塞了方法本身的复现（`docs/16` 结论仍为"全项目 partial，不能填 Table IV/V/VI"）。
3. **缺少与 Cadence 解耦的仿真后端抽象。** 所有智能体/工具都假定 Spectre 在线，远端不可用时整个方法层停摆。
4. **论文勘误**（数值验证，见 §3）：Eq.(3) 的 Y11 分母漏掉 `s`；"/2" 为差分半电路约定。
5. **审计台账 A08 应改判**：Table III 的 IP1dB ≥ −15 dBm 与正文"OP1dB 9 dBm"在 ~24 dB 增益下自洽
   （−15 + 25 − 1 ≈ 9），并非两种互斥口径。
6. **测试脆弱性**：9 个测试（`test_run_teaching_oa.py`）要求 `tmp_path` 位于 `results/runs/` 下，
   直接 `pytest tests` 会失败；原 README 靠手工 `--basetemp` 规避。

## 2. 问题台账（本轮新增 B 系列）

| ID | 级别 | 发现 | 修正 | 验证 |
|---|---|---|---|---|
| B01 | P0 | 论文方法层无可运行实现（Stage 3/4、基线、表图） | 新增 `src/orfadc/repro/`：四个工具、三智能体、KB/EB、GA/BO 基线、`bench` 表图入口 | `tests/test_repro_core.py` 14 项；`bench all` 实跑 |
| B02 | P0 | 无仿真后端抽象，远端故障即全停 | `tools.Backend` 协议 + `SurrogateBackend`；Cadence 后端按同一协议接入（skill `cadence-backend-bridge`） | 协议单测、MCP 端到端 |
| B03 | P1 | Eq.(3) 原式 Y11 分母末项 `R_S ω0³ Q` 量纲错误 | `repro/mcr_eq3.py` 默认 `corrected`（`R_S ω0³ Q s`），保留 `printed` | 与节点分析 `tools/mcr_lumped.py` 相对误差 < 1e-9（3 组参数×3 频点） |
| B04 | P1 | Eq.(3) "/2" 在单端等效中造成 ≈ −6 dB 系统偏差 | `half=False` 为默认，并在 Fig.5 实验中量化三种形式误差 | `raw/fig5.json: eq3_stage_gain_error_vs_hf` |
| B05 | P1 | Stage 2 代价只有 Eq.(1)，可行后 PSO 停在 NF 边界，留给后级的 NF 余量为零 | 在不改变 Eq.(1) 可行域的前提下增加 NF 余量与增益的次级 tie-breaker；`Gain_require` 改为 ±1 dB 目标（论文"constrain gain"） | Refiner 回溯次数下降（见 docs/115） |
| B06 | P1 | Refiner 把"关键级增益"与"到 stage2 栅极增益"混用，导致 gain_req_list 双计 stage2 | 以 HF 实测分级增益 `[g_to_g2, g2, g3]` 为分配基准 | S1/S5 由失败转为可解 |
| B07 | P1 | Stage 2 在增益约束下不可行时 Refiner 继续空转 | 论文"infeasible → terminate early"：返回 `stage2_infeasible` 交 Manager 升级到 Stage 1 | `agents.RFAmpRefiner.refine` |
| B08 | P2 | 9 个测试依赖手工 `--basetemp` | 新增 `tests/conftest.py` 自动把 basetemp 设在 `results/runs/pytest_*` | `pytest tests -q` 直接 708 passed |
| B09 | P2 | A08 误判为歧义 | 本文件 §1-5 给出换算；建议台账状态改为 `resolved` | — |
| B10 | P2 | `docs/10`、`docs/15` 提示词以远程实机为唯一路径，无离线自主路线 | 新增 `docs/117`（逐步手册）、`docs/118`（提示词）、`CLAUDE.md`、`.claude/` | — |
| B11 | P1 | （2026-10-01 实测）引擎把源极电感加在 CS 管 Y 矩阵公共端，等效将第一级 Cdb 接到源极而非地；与物理接法差：S2 中心增益 0.44 dB、NF 0.26 dB | Spectre 网表默认按引擎拓扑（交叉验证逐点一致），物理接法作为 `sensitivity_physical_cdb` 报告；v2 换 PDK 器件后消失（docs/120） | `tests/test_repro_cadence_backend.py` |
| B12 | P1 | 频带网格含重复带边点，Spectre 自动去重 → 解析"网格不一致" | 按 12 位有效数字去重仿真，再映射回请求网格 | 同上 |
| B13 | P1 | Windows 上 pip 装到 mcp 2.x（FastMCP 改名），两个 MCP 服务器启动即退出 | `requirements_repro.txt` 钉 `mcp>=1.2,<2`，服务器给出重装提示 | `tests/test_repro_llm_cli.py` |
| B15 | P1 | （v2 实测）单张 Vds=VDD 器件表 + CG 宽度比 0.45 使 PDK 第一级在 1.1 V 下欠偏置，引擎与 Spectre 增益差 13 dB | 级联器件改用低 Vds 表、CG 宽度比 1.0；Stage 4 功耗改用 Spectre 实测支路电流 | `tests/test_repro_pdk_v2.py` |
| B16 | P2 | 引擎噪声（γ 模型）比 PDK 悲观约 1.7 dB，压缩估计比 HB 悲观 8–10 dB，输入匹配偏差大 | 已修（docs/122）：两频点 Y/噪声拟合、大信号 1 dB 点、完整交叉耦合半电路；窄带一致，宽带仍有 2–3 dB 增益误差 | `tests/test_repro_pdk_fit.py` |
| B17 | P2 | 代理引擎把交叉耦合中和只建成 0.12 Cgd 的残余电容，漏掉每个栅/漏节点上 1.88 Cgd 的负载（物理半电路） | PDK 路径已改为完整模型；代理路径保持原方程以免改变已发表的趋势结果，标注为已知简化 | `test_cross_coupled_neutralisation_capacitances` |
| B18 | P2 | 第一级用接地源二端口表征，看不到源极接 Ls（CS）或抬高到 VDD−Vgs（CG）时的体效应和源侧寄生，导致宽带 S11/增益误差 1–3 dB（docs/123） | 第一级改用在路偏置下的三端口实测 Y（`pdk3`），经 Kron 归约接入引擎 | `test_measured_y3_of_the_model_reproduces_the_model_stage1`、`test_y3table_interpolation_and_range` |
| B19 | P2 | `pdk_v2._tables` 按"行数多、时间新"选表，新做的原始表会顶替已拟合的表 | 改为已拟合的表优先 | 由 docs/123 §5 的 device_source 发现 |
| B20 | P3 | 失败运行报告最后一次评估，而不是违规最小的候选；refine 循环以 Stage 2 不可行结束时没有报告设计；Manager 比较时用未归一化的违规和 | `ORFADC_REPORT_BEST=1`（PDK 路径默认打开）时改为报告归一化违规最小的候选 | `tests/test_repro_report_best.py` |
| B21 | — | （尝试，未采用）Stage 2 不可行时回退到中点再试 | `ORFADC_STAGE2_BACKOFF=1`，默认关闭；5 seed 消融中各规格持平或变差（docs/124 §1.3），保留论文的提前终止 | `results/repro/ablation_backoff_20261002/` |
| B14 | P2 | LLM `fallbacks` 把封顶后的规则决策也算作回退，夸大了"模型输出不合格" | 新增 `rule_after_disable` 计数，`llm-table` 对旧档自动重算 | 同上 |

## 3. Eq.(3) 推导复核

对称耦合并联 RLC（每侧 R、L、C，耦合 k，`ω0² = 1/LC`，`Q = ω0 R C`）节点方程：

`Y = [[G+sC+Γ, −kΓ], [−kΓ, G+sC+Γ]]`，`Γ = 1/(sL(1−k²))`。

输入导纳 `Y11 = det(Y)/(G+sC+Γ)`，化简得分子与论文完全一致，分母为

`(1−k²) R ω0 Q s³ + (1−k²) R ω0² s² + R ω0³ Q s`。

论文印刷版末项缺 `s`（分子 4 次、分母应为 3 次）。转移阻抗 `Z21 = kΓ/det(Y)` 与论文一致
（R = √(R_S R_2)）。`tests/test_repro_core.py::test_eq3_corrected_y11_z21_match_nodal_model` 固化该结论。

## 4. 保留与不改动的部分

- 远程 Cadence、隔离栅栏、GUI 探针等模块全部保留，未改一行逻辑；其测试仍全部通过。
- 路线 B 的"未获 PDK 合格结果前不得填表"的纪律继续有效；路线 A 的所有输出都显式标注 surrogate。
