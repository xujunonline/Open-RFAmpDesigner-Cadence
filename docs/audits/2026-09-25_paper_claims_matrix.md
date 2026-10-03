# 英文论文事实与工程映射

审查原件：`references/paper/RFAmpDesigner.pdf`，14 页，arXiv:2605.10093v1。页码是 PDF 页码。PDF 文本抽取、中文翻译与 arXiv `main.tex` 仅作辅助；表格 III 和 Fig. 7 已查看 PDF 页图。此表描述原文与仓库的关系，不表示代码已经实现论文实验。

| 原文位置 | 英文论文事实或定义 | 本工程对应 | 核对结论 |
| --- | --- | --- | --- |
| p.1-2, Abstract/Intro | 目标是 RF amplifier 参数 sizing；LLM 给概念级资源分配，工具负责数值化与仿真。 | `README.md`、`docs/01_paper_theory.md` | 方向一致；完整电路未实现。 |
| p.3, Fig. 3 | 目标电路三阶段；设计向量 `X1=[W1,W2,W3,VGS1,VGS2,VGS3]`，三个七参数 `X2,i`，`X3=[Lpar,Lg,Ls]`，共 30 维。 | `docs/open_rfampdesigner_cadence_full_plan.md`、`config/variable_ranges_table_ii.yaml` | 论文结构已描述；无本工程三阶段 schematic。 |
| p.4, Sec. II-A | 第一级单端 cascode；后级差分共源并有中和电容；作者用 N65 PDK、PCell、Calibre DRC/LVS/PEX 与 post-layout netlist 表征。 | `circuit/ocean/`、`config/model_paths.yaml` | 工艺及布局资产不公开；本工程仅有理想二端口网表。 |
| p.4, Table I | Active sizing 输入 `power_ratio_list`，输出包含 W、bias、gm、Id、输入/输出阻抗的候选列表。 | `tools/active_sizing.py` | 电流分配和有限 lookup 选择已编码；无实测 PDK lookup。 |
| p.4, Table I | Impedance matching 输入有源参数、可选 NF headroom 和 gain requirement；输出关键级无源参数和仿真结果。 | `tools/impedance_matching.py` | 目前只可对外部提供的数值计算未验证 cost；无真实匹配仿真。 |
| p.4, Table I | Band planning 输入有源参数、gain list、可选 gain requirement list；输出剩余级无源参数和低保真 gain。 | `tools/band_planning.py` | 有成本接口，无 MCR 数学模型与校准。 |
| p.4, Table I | Fullchain 输入完整有源/无源字典，返回小信号及大信号真实仿真结果。 | `tools/fullchain_eval.py` | 真实路径明确为 `not_implemented`，不会报告 pass。 |
| p.5, Table II | Stage 2：`k 0.1-0.7; L1/L2 100-1000 pH; R1/R2 100-1000 ohm; C1/C2 0-50 fF; Ls 0-150 pH`。 | `config/variable_ranges_table_ii.yaml`、`tests/test_paper_tables.py` | 数值、单位一致。 |
| p.5, Table II | Stage 3：`k 0.1-0.8; omega0 [omegaL,omegaH] GHz; Q0 0.1-8; C [C2,200] fF`。 | 同上 | 一致；`C2` 是符号下界，不能当数字直接优化。 |
| p.5, Eq. (1) | `NFv=max(0,NFsim-(NFuser-0.2))`；`S11v=max(0,S11sim+20)`；`cost=1000(NFv+S11v)`。取中心频率并使用真实关键级仿真。 | `tools/cost_functions.py` | 公式正确；可选 `nf_headroom_db` 是本工程扩展。非有限数已拒绝；真实 Stage 2 未实现。 |
| p.5, Sec. II-B(2) | 先仿真前两级无输入匹配网络得输入阻抗，再用 L 型网络初算 `Lpar/Lg`，然后含匹配网络仿真 NF/S11；PSO 优化。 | `tools/impedance_matching.py`、`circuit/ocean/run_sparam.ocn` | 全部关键仿真与 PSO 尚缺。 |
| p.6, Eq. (2) | `gainv=max(0, abs(gainuser-min(gaincal))-3)`；`ripplev=max(0,max(gaincal)-min(gaincal)-3)`，成本为二者各乘 1000。 | `tools/cost_functions.py` | 代码吻合；`gaincal` 仍非真实 MCR 响应。 |
| p.6, Eq. (3) | 给出对称 MCR 的 `Y11(s)`、`Z21(s)`、`I11(s)` 和 `V(s)=I11(s)Z21(s)/2`。 | `docs/open_rfampdesigner_cadence_full_plan.md` | 仅方案，未有对应数值实现；不得说已复现公式 (3)。 |
| p.6, Sec. II-B(3) | Stage 3 用 SA 搜索每级 MCR 的 `k,omega0,Q0,C`，理论响应经少量仿真残差校准；Fig. 5 的 88% 加速是作者实验。 | `tools/band_planning.py` | SA、校准和 Cadence 对照均未实现。 |
| p.6, Sec. II-B(4) | Fullchain 包含小信号、S 参数和 HB；噪声/线性度失败回溯不同阶段。 | `tools/fullchain_eval.py`、`agents/refiner.py` | 骨架有失败规则，真实 fullchain 未实现。 |
| p.7-8, Sec. II-C | Manager 有候选优先队列；Searcher 提供新的关键级候选；Refiner 根据反馈细化；KB 为事实，EB 为衍生经验；两种模式为 Search 和 Retrieve-and-Refine。 | `agents/`、`docs/agent_system/` | 角色文档充分，实际队列、检索和闭环尚缺。 |
| p.8, Table III | S1-S10 共十项规格：频率 10/30/50 GHz、BW 10%-80%、电流 15/30 mA、gain 20/25 dB、NF 2.5/3.5/5 dB、表列 IP1dB -25/-20/-15 dBm。 | `config/specs_table_iii.yaml`、`tests/test_paper_tables.py` | 十行数值与 PDF 逐格一致。 |
| p.8, Sec. III-A(2) | 负载 `1787 ohm || 62 fF`；正文又称 S9 需要 `OP1dB=9 dBm`，而 Table III 表头是 `IP1dB` 且 S9=-15 dBm。 | `schemas.Spec.ip1db_min_dbm` | **论文内部口径不一致**。本工程保留 Table III 的输入压缩点字段；不得把其阈值转写成 9 dBm OP1dB，输出压缩点须单独计算。 |
| p.8-9, Sec. III-A | 三 agent 用 Python，顺序推理；Cadence Spectre/OCEAN；Stage 2 PSO/Stage 3 SA 取自 scikit-opt。 | `src/orfadc/` | 当前只有 Python 骨架和少量真实 `sp` 结果；无论文优化器实验。 |
| p.9, Sec. III-A/ Table IV | S1-S8：五个独立 seed、统一仿真预算、1 h timeout；固定初始功率比 `[0.4,0.3,0.3]`；报告 pass@1 和可行解平均耗时。 | `config/sweep_settings.yaml`、`docs/06_experiments.md` | 配置有 5 seeds/3600 s，未实际跑此比较。 |
| p.10, Table V | S9/S10 timeout 5 h，比较工具增强 GA/BO、LLM backbone 和消融，报告成功数/5、耗时、prompt/completion token。 | `src/orfadc/baselines/`、`docs/06_experiments.md` | 无本项目结果；不能使用论文原值填入 like 表。 |
| p.9-11, Fig. 7-9 | Fig. 7 是作者 S 参数/NF/压缩曲线；Fig. 8 时间；Fig. 9 Search/Refine 次数。 | `src/orfadc/plots/` | 绘图模块均占位。Fig. 7 图内标 S21，图注却写 S22，属于原文内部不一致；项目绘图须按实际列名。 |
| p.11, Fig. 10-11 | 自进化实验围绕 S4 派生任务，gain 20-45 dB；Fig. 10 仿真成本，Fig. 11 FoM 随成本变化，5.5x 是作者趋势结论。 | `docs/06_experiments.md`、`src/orfadc/plots/` | 项目尚无跨任务结果，不得引用作者倍数为自有结果。 |
| p.12, Table VI | 依模型比较有效延迟与美元成本，注释说明按 pass@1 比率调整；价格/延迟属于论文运行环境。 | `docs/06_experiments.md` | 无本地 LLM 调用或价格证据。 |

## 对文档和代码的约束

1. `S11 <= -20 dB` 来自论文 Stage 2 局部匹配成本；Table III 没有单独列全链 S11 规格。`fullchain_violations` 的默认 `-10 dB` 是本项目暂定门槛，必须在真实任务配置中显式声明。
2. `20log10|S21|` 是指定端口参考条件下的正向散射参数，不能无条件替代电压增益、transducer gain 或可用功率增益。
3. 本项目现有真实 Cadence 数值只来自被动理想二端口 `sp`，与论文三阶段 N65 LNA 结果不在同一证据层级。
