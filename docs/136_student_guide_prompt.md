# 136 提示词：为微电子专业本科生生成《项目设计方案与仿真过程学习指南》

> 用途：在本仓库根目录打开 Claude Code，把下方"提示词正文"整段粘贴给它，它会阅读代码与文档，
> 生成 `docs/137_student_guide.md`。
> 读者画像、章节结构、证据规则和自检清单都已写在提示词里，可按需删改。

---

## 提示词正文

````text
你是一名射频集成电路设计方向的研究生助教，同时熟悉 Python 与 EDA 仿真流程。
请为本仓库 Open-RFAmpDesigner-Cadence 写一份教学型技术文档，让一名刚上大三的微电子专业本科生读完后能够：
(1) 说清这个项目要解决什么问题、整体如何运作；
(2) 看懂三级宽带 LNA 的设计方案和每一步仿真在算什么；
(3) 能自己在本机跑通离线流程，并读懂输出结果；
(4) 知道哪些结论可信、可信到什么程度。

# 读者画像（按这个水平写）
- 已学：电路分析、模拟电子技术、半导体器件物理（MOSFET 平方律、小信号模型 gm/gds/Cgs/Cgd）、信号与系统、基础 Python。
- 可能没学或只学过皮毛：射频电路（S 参数、史密斯圆图、阻抗匹配、噪声系数 NF、IP1dB）、两端口网络与噪声相关矩阵、
  多目标优化（PSO、GA、BO）、LLM 智能体（ReAct）、Cadence Spectre 的 SP/Noise/HB 分析、PDK 是什么。
- 因此：每个新概念第一次出现时，先给直观解释，再给公式，最后给本项目中的代码位置；不要跳步，不要假设读者已懂射频术语。

# 必读材料（按顺序阅读，写作时以它们为准）
1. 项目总览：CLAUDE.md、README.md、docs/00_index.md
2. 论文：references/paper/RFAmpDesigner_中文翻译.md（必要时对照 references/paper/RFAmpDesigner.pdf）
3. 复现流水线与总报告：docs/115_repro_surrogate_pipeline.md、docs/125_final_reproduction_report.md、docs/135_v2_reproduction_report.md
4. 仿真内核：src/orfadc/repro/twoport.py、device.py、circuit.py、mcr_eq3.py
5. 四个工具与成本模型：src/orfadc/repro/tools.py、optim.py
6. 智能体：src/orfadc/repro/agents.py（v1）、agents_v2.py 与 docs/131_agent_v2_design.md（v2）、prompts/ 下的提示词、memory.py
7. 基线算法：src/orfadc/repro/baselines.py
8. Cadence/Spectre 后端：src/orfadc/repro/backend_cadence.py、pdk_v2.py、pdk3.py、pdk_fit.py、pdk_spiral.py，
   以及 docs/120–123、docs/132_n65_bringup.md
9. 实验结果：docs/127、docs/133_agent_v2_results.md，以及 results/repro/ 下对应的原始 JSON
10. 测试（用来确认公式与实现是否一致）：tests/test_repro_core.py、tests/test_repro_cadence_backend.py、tests/fakes/mna_spectre.py

# 硬性规则
1. 不编造。所有数字（通过率、指标、仿真次数、时间）都必须来自上述文档或 results/ 下的原始文件，并注明出处路径。
   找不到出处就写"未找到出处"，不要估计。
2. 讲到实现时，给出"文件:行号"形式的代码出处（例如 src/orfadc/repro/twoport.py:42），并只摘录理解所需的最短代码片段。
3. 严格区分三类证据，并在每个结果旁标注：
   - 代理（surrogate，趋势级）：开放的 EKV 类器件模型加两端口引擎；
   - PDK 原理图级：TSMC 器件、理想无源、无版图寄生，Stage 4 由 Spectre 判定；
   - 论文原文数据。
   不得把代理或 PDK 结果说成硅结果或后仿结果。
4. 保密：不读取、不引用 config/*.local.yaml；不写出任何 PDK 模型文件路径、器件模型参数或从 PDK 表征得到的器件表数值。
   PDK 部分只讲流程和方法，可以引用 docs 中已经公开的汇总指标（增益、NF、通过率）。
5. 不执行任何远程或 Cadence 操作（ssh、bench cadence-check、bench pdk-*、--backend pdk|cadence）。
   只允许运行离线命令：
   export PYTHONPATH=src
   python -m pytest tests/test_repro_core.py -q
   python -m orfadc.repro.bench smoke --out results/repro/guide_smoke
   python -m orfadc.repro.bench design --spec S2 --seed 0 --policy rule
6. 论文勘误以代码和测试为准：Eq.(3) 的 Y11 分母末项应为 R_S ω0³ Q s（见 tests/test_repro_core.py）；
   讲到 Eq.(3) 时，要同时给出原式和修正式，并说明测试是如何验证的。
7. 全文用中文；公式用 LaTeX；框图和流程图用 Mermaid；代码标识符保持英文。

# 文档结构（按此组织，章节标题可微调）
第 0 章 导读：一页纸讲清"输入规格 → 四个阶段 → Spectre 判定 → 结果"；给出全局 Mermaid 流程图和阅读路线（必读 / 选读）。

第 1 章 预备知识速成（只讲本项目用到的部分，每节配一个小算例）
  1.1 LNA 的作用与指标：增益、带宽、纹波、S11、NF、IP1dB、功耗，以及它们之间的折中
  1.2 S 参数、阻抗匹配与 Q 值；为什么宽带匹配难
  1.3 噪声系数、Friis 级联公式、NFmin 与最佳源阻抗
  1.4 两端口 ABCD 矩阵级联，以及噪声相关矩阵（Hillbrand–Russer）为什么能把噪声也一起级联
  1.5 优化算法（PSO / GA / BO）与 LLM 智能体（ReAct：思考 → 调用工具 → 观察）各用一页讲清

第 2 章 问题定义：论文 Table II/III 的规格 S1–S10 逐项解释（对照 config/ 中的规格文件）；
  S9s/S10s 是什么、为什么要有它们。

第 3 章 电路设计方案
  3.1 论文图 3 的三级 LNA 拓扑：各级的作用（输入匹配与低噪声、共栅/差分增益级、输出级）；
      用 Mermaid 或 ASCII 画出拓扑，并与 circuit.py 中的数据结构一一对应
  3.2 MCR 结构与 Eq.(3)：推导思路、原式与修正式、二分法如何把抽象参数映射成元件值
  3.3 器件模型：代理 EKV 类模型（device.py）与 PDK 器件表（pdk_v2.py）各自提供哪些小信号量；
      Stage 1 的"知识库"是什么

第 4 章 仿真引擎：一次"仿真"到底算了什么
  4.1 从元件值到每级的 ABCD 与噪声相关矩阵，再到级联得到增益、S11、NF 的完整计算链
      （配一个数值例子：取 S2 的一个实际设计，手算或用脚本复现一个频点的结果）
  4.2 压缩点（IP1dB）的估计方法
  4.3 多保真：lf / hf_critical / hf_full 分别是什么；等效 EDA 时间成本模型（0.002 s / 0.5 s / 12 s）如何记账；
      为什么能省时间

第 5 章 四个阶段的工具（Table I）
  每个工具写清：输入、输出、内部算法、调用的仿真类型、典型耗时、失败时返回什么。
  5.1 Stage 1 有源器件尺寸与偏置（active_sizing）
  5.2 Stage 2 阻抗匹配（impedance_matching，PSO）
  5.3 Stage 3 频带规划与校准（band_planning）
  5.4 Stage 4 全链评估（fullchain_evaluation），以及什么时候交给 Spectre

第 6 章 智能体如何驱动设计
  6.1 Manager / Searcher / Refiner 的分工；回溯策略（失败后退回哪一级）
  6.2 v1：规则策略加两个 LLM 决策点
  6.3 v2：三个智能体都由 LLM 以 ReAct 方式驱动；节选 prompts/ 中的提示词，解释一次 LLM 调用的输入和输出
  6.4 KB/EB 记忆与"自进化"（Fig. 10）
  6.5 对照组 GA/BO 的做法，以及为什么搜索空间是 18 维和 14 维

第 7 章 接入真实 EDA：Cadence Spectre 与 PDK
  7.1 PDK 是什么；为什么需要先做器件表征（扫偏置、提取 Y 参数和噪声参数）
  7.2 网表是如何由设计自动生成的（render_pdk_netlist 的结构，只讲结构不写 PDK 参数）
  7.3 Spectre 的 SP、Noise、HB 分析分别给出什么；PSF 结果如何被解析
  7.4 远程执行链路（Mac → ssh → 虚拟机 → Spectre → 回传）与资源护栏（每设计上限、总账本）
  7.5 引擎与 Spectre 的一致性如何验证（tests/fakes/mna_spectre.py、docs/132 的对比数据）

第 8 章 动手实践：带你跑一遍
  8.1 环境准备与上面列出的离线命令；给出每条命令的预期输出（以你实际运行的结果为准）
  8.2 逐段解读 design 命令输出的 JSON：report、metrics、violations、sims、trace 各字段的含义
  8.3 跟踪一次完整设计：从 trace 中挑出关键步骤，说明智能体在每一步看到了什么、做了什么决定

第 9 章 实验结果与如何解读
  9.1 主要结果表（v1/v2、代理/PDK、与论文对照），全部注明出处和证据等级
  9.2 没有复现的部分及原因（S3/S6/S7/S10）
  9.3 局限性：等效时间是成本模型；PDK 结果是原理图级；样本量小

第 10 章 常见问题、术语表与思考题
  - 术语表：中英文对照，每条一两句解释
  - 思考题 8–12 道，从概念题到动手题（例如"把 ORFADC_Q_MATCH 从 25 改成 15，预期哪些指标会变？跑一下验证"），附参考答案要点
  - 延伸阅读：教材章节（Razavi《RF Microelectronics》、Lee《The Design of CMOS Radio-Frequency Integrated Circuits》中对应的章节）和论文中的关键参考文献

附录 A 代码地图：表格列出每个源文件的职责、关键函数和对应章节。
附录 B 重要公式汇总。

# 写作要求
- 每章开头用 2–3 句话说明"这一章解决什么问题"，结尾用 3–5 条要点小结。
- 先直观，后公式，再代码；每个公式说明每个符号的物理含义和单位。
- 至少 6 张 Mermaid 图：全局流程、三级 LNA 拓扑、多保真调用关系、Manager/Searcher/Refiner 交互时序、Spectre 远程链路、回溯状态机。
- 至少 3 个数值算例，且必须来自实际运行或仓库中的原始文件。
- 表格用于对比（v1 与 v2、代理与 PDK、论文与本项目）。
- 篇幅：正文约 2–3 万字；宁可清楚，也不要堆砌。

# 交付与自检
1. 输出到 docs/137_student_guide.md，并在 docs/00_index.md 中加一行索引。
2. 完成后逐条自检，并把结果附在回复里：
   - [ ] 所有数字都有出处路径
   - [ ] 所有代码引用都有 文件:行号，且与当前代码一致
   - [ ] 每个结果都标注了证据等级（代理 / PDK 原理图级 / 论文）
   - [ ] 没有出现 PDK 模型路径、器件参数或 *.local.yaml 的内容
   - [ ] 第 8 章的命令都实际运行过，输出摘录与实际一致
   - [ ] Eq.(3) 的原式与修正式都已给出
   - [ ] Mermaid 图都能正常渲染
3. 最后列出你认为本科生最难理解的 3 个地方，以及文中是如何处理的。
````

## 使用说明

- 文档较长，建议分两次生成：先让它写第 0–5 章，确认风格合适后再写第 6–10 章和附录。
  可以在提示词末尾加一句"本次只写第 0–5 章"。
- 只想要某一部分（例如只学仿真引擎），可以只保留第 1、3、4 章的要求。
- 如果想换成 PPT 或 Word，把"交付与自检"第 1 条的输出格式改掉即可。
