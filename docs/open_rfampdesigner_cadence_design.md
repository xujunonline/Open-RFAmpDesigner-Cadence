# Open-RFAmpDesigner-Cadence：基于 Cadence、开源项目与多智能体 LLM 的 RF 放大器自动设计复现方案

## 1. 项目背景

RFAmpDesigner 的核心贡献是把 RF 放大器 sizing 从 30 维左右的直接 netlist 搜索，改写成低维“资源分配 + 工具中间件 + 高保真仿真反馈”的流程。LLM 不直接写 Cadence netlist，而是做类似人类 RF 工程师的概念级决策：电流怎么分、关键级是否需要更多 NF headroom、线性度不足时是否降低前级增益、候选失败后回溯到哪一阶段。

本工程的目标是做 Cadence 主线的开源复现底座。它能帮助已有 Cadence/OCEAN/Python 自动扫参经验的学生，把 OTA 自动 sizing 的思路迁移到 RF LNA：从 DC/AC 指标扩展到 S 参数、噪声、匹配、压缩点和宽带 ripple。

## 2. 可复现边界

严格可复现：

- Table I 工具接口；
- Table II 变量范围；
- Table III 10 个 LNA benchmark 规格；
- 论文公式 (1)(2)(3) 的 Python 结构；
- 日志、候选、仿真结果、表格和图的输出格式。

近似可复现：

- Cadence/Spectre 自动仿真闭环；
- 三阶段 LNA 或简化 RF 放大器的趋势级优化；
- Manager/Searcher/Refiner 的多智能体调度；
- GA/BO/PSO/SA 与工具中间件的对照实验。

不能严格复现：

- 作者 TSMC N65 PDK、PCells、post-layout netlist；
- 作者 OCEAN scripts、lookup table、KB/EB、prompt、最终候选参数；
- 作者硬件队列、并行策略、LLM 延迟和 token 价格；
- Fig. 7 原始曲线和 Table IV/V 的精确数值。

因此，最终报告只能声明“方法级复现”“流程级复现”“趋势级复现”，不能声明“严格复现论文原始 TSMC N65 结果”。

## 3. 论文拆解

论文对象是三阶段宽带 LNA：第一级单端 cascode，重点负责输入匹配和低噪声；后两级为带中和电容的差分共源级，重点负责增益、宽带响应和线性度；级间网络使用 MCR 磁耦合谐振器，负载近似为 `1787 ohm || 62 fF`。任务中心频率覆盖 10、30、50 GHz，相对带宽覆盖 10% 到 80%。

传统 GA/BO/RL 的难点在于直接面对高维、强耦合、稀疏可行域。LLM 直接改 netlist 又不可靠，因为 RF 参数关系主要是数值仿真和工艺数据库驱动，不是纯文本规则。RFAmpDesigner 的中间路线是：让 LLM 输出资源分配意图，再由确定性工具和 Cadence 仿真把意图编译成候选设计。

## 4. RF/LNA 理论基础

从 OTA 到 LNA 的迁移可以这样理解：OTA 自动扫 W/L 时关注增益、UGF、相位裕度、功耗；LNA 自动 sizing 仍然关注增益和功耗，但多了端口匹配、噪声和大信号线性度。`S11` 描述输入端有多少信号被反射，`S21` 描述正向增益，`S22` 描述输出匹配。`NF` 是放大器额外引入噪声的程度，第一级 NF 最关键，因为后级噪声会被前级增益压低。`IP1dB/OP1dB` 衡量大信号压缩点，是线性度指标。

Cadence 中通常用 `sp` 仿真提取 S 参数，用 `noise` 或 `sp-noise` 提取 NF/NFmin，用 AC 或 PAC 看小信号增益，用 PSS/HB/QPSS 或输入功率 sweep 估计 1 dB 压缩点。Python 层只接收 CSV/PSFASCII 结果，不直接解释商业模型。

## 5. Cadence 仿真流程

MVP 采用两条路线：

- 路线 A：实验室授权商业 PDK。使用真实 MOS、MIM cap、spiral inductor/transformer 或 PDK 提供的无源模型。
- 路线 B：教学/简化模型。使用 Spectre 的简化 MOS 或等效 gm/RLC 网络跑通闭环，只报告方法趋势。

推荐 Virtuoso 命名：

- library：`orfadc_lna_lib`
- cell：`lna_3stage_schematic`、`tb_sparam`、`tb_noise`、`tb_compression`
- view：`schematic`、`spectre`、`maestro`

仿真步骤：

1. 手工或 SKILL/OCEAN 创建 schematic，设置 MOS 宽度、偏置、电感、电容、MCR 等效网络和端口。
2. `Check and Save` 后导出 Spectre netlist。
3. `run_sparam.ocn` 运行频率 sweep，导出 S11/S21/S22。
4. `run_noise.ocn` 运行噪声仿真，导出 NF/NFmin。
5. `run_compression.ocn` 做输入功率 sweep 或 HB/PSS，导出 IP1dB/OP1dB。
6. Python 读取 CSV/PSFASCII，计算 pass/fail、violation 和 cost。
7. 每个候选保存到 `results/runs/<spec>/<seed>/<candidate>/`。

## 6. 工具中间件设计

Table I 映射为四个 Python 工具：

- `active_sizing`：输入 `power_ratio_list` 和总电流，输出每级电流、候选 W/VGS/gm/阻抗。无授权 lookup table 时只生成结构化占位候选。
- `impedance_matching`：输入有源候选、`NF_headroom` 和可选增益要求，调用 Stage 2 PSO 或确定性候选生成，按公式 (1) 评分。
- `band_planning`：输入有源/无源候选、目标增益和带宽，用 MCR 低保真模型和 Stage 3 SA 规划通带，按公式 (2) 评分。
- `fullchain_eval`：调用 Cadence 全链路仿真，导出真实性能指标。无 Cadence 时只允许 `dry_run`，不能伪造 pass。

## 7. 数学公式实现

Stage 2 cost：

```text
NF_violation  = max(0, NF_sim - (NF_user - 0.2))
S11_violation = max(0, S11_sim + 20)
cost = 1000 * NF_violation + 1000 * S11_violation
```

Stage 3 cost：

```text
gain_violation   = max(0, abs(gain_user - min(gain_cal)) - 3)
ripple_violation = max(0, max(gain_cal) - min(gain_cal) - 3)
cost = 1000 * gain_violation + 1000 * ripple_violation
```

公式 (3) 的 MCR 传递函数在 MVP 中先保留接口，后续用 NumPy 实现复数频率响应，并用少量 Cadence 仿真残差做多保真校准。

## 8. 多智能体设计

`RFAmpManager` 维护候选优先队列，动作空间为 `SearchCandidates` 和 `RefineCandidate`。`RFAmpSearcher` 负责提出功率分配、枚举有源候选、运行关键级匹配。`RFAmpRefiner` 读取失败指标并选择回溯策略：NF 不足回到 Stage 2 增加 headroom；S11 不足调整匹配网络；gain/ripple 不足回到 Stage 3；线性度不足重分配增益或电流；持续失败时回到 Stage 1。

第一版不强依赖 LLM API，而是用确定性策略跑通状态机。后续把 prompt 模板接入 LLM，要求所有 agent 输出 JSON，禁止自由文本直接修改 netlist。

## 9. 开源项目复用方案

| 开源项目 | 地址 | 可复用模块 | 用于本方案哪一部分 | 与 RFAmpDesigner 的关系 | 局限 |
|---|---|---|---|---|---|
| AnalogCoder | https://github.com/laiyao1/AnalogCoder | problem set、prompt、simulation-in-loop | agent prompt 和 benchmark 组织 | 同属 LLM + 仿真闭环 | 原始后端偏 PySpice/ngspice，不是 Cadence RF |
| EEsizer | https://github.com/eelab-dev/LLM-transistor-sizing | 规格到 sizing 的反馈循环 | Refiner 失败反馈 | 参数 sizing 思路相近 | RF/S 参数/NF 支持不足 |
| AutoCkt | https://github.com/ksettaluri6/AutoCkt | spec yaml、reward、action space | baseline 和配置 | 自动电路优化底座 | 主要是 ngspice/RL |
| AnalogGym | https://github.com/CODA-Team/AnalogGym | benchmark 目录 | 公开任务组织 | benchmark 化思路一致 | Cadence 商业环境需改造 |
| SPICEBridge | https://github.com/clanker-lover/spicebridge | 仿真 API 化 | Cadence tool registry | 工具中间件思想一致 | ngspice MCP 不能直接替代 OCEAN |
| virtuoso-bridge-lite | https://github.com/Arcadia-1/virtuoso-bridge-lite | Virtuoso/Spectre bridge | 可选 Cadence agent bridge | 贴近 Cadence 控制 | 需实验室许可和安全审查 |
| ALIGN | https://github.com/ALIGN-analoglayout/ALIGN-public | netlist-to-layout 流程 | 后续 layout/PEX | sizing 后扩展方向 | 第一阶段不处理 layout |
| ngspice/Xyce | https://github.com/ngspice/ngspice / https://github.com/Xyce/Xyce | 开源仿真 fallback | 无 Cadence 调试工具层 | 可跑方法闭环 | 不能声称等价 Cadence/PDK 结果 |

所有第三方代码必须记录 license；不能把商业 PDK 路径、模型、PCell 或仿真日志中的工艺敏感信息提交到开源仓库。

## 10. 数据结构

核心 JSON/YAML 对象：

- `spec`：`id, fc_ghz, fbw_ratio, power_ma, gain_db, nf_max_db, ip1db_min_dbm`
- `candidate`：`candidate_id, spec_id, seed, active_params, passive_params, stage, status`
- `sim_result`：`s11_db, s21_db, s22_db, nf_db, nfmin_db, ip1db_dbm, op1db_dbm, power_ma, ripple_db`
- `violation`：每个指标的超限幅度与总 cost
- `memory record`：候选、指标、失败原因、可迁移经验

## 11. 代码结构

当前骨架采用 `src/orfadc` 包：

- `cadence/`：OCEAN/Spectre 调用、结果解析、netlist 模板；
- `tools/`：论文 Table I 工具和 cost function；
- `agents/`：Manager/Searcher/Refiner、memory、prompt；
- `baselines/`：GA/BO/PSO/SA/random search 占位；
- `experiments/`：Table IV/V、消融、自进化实验入口；
- `plots/`：Fig. 7/8/9/10/11-like 绘图脚本。

## 12. 实验设计

阶段 1：论文结构复现。完成 YAML、公式、日志和表格格式。

阶段 2：Cadence 简化 LNA。先跑单级或两级 RF 放大器，提取 S 参数、NF、gain、power，验证 Python-OCEAN 闭环。

阶段 3：论文级近似复现。实现三阶段宽带 LNA、MCR 等效网络、10 specs、5 seeds、Table/Fig-like 输出，并清楚标注不可严格对比。

## 13. MVP 实施计划

第 1 周：建目录、配置、cost function、dry-run 实验记录。

第 2 周：接入实验室 Cadence 路径，跑通 S 参数和 noise testbench。

第 3 周：实现 active lookup table 生成和 Stage 2 impedance matching。

第 4 周：实现 Stage 3 band planning 和全链路评估。

第 5 周：接入 Manager/Searcher/Refiner 和 baseline。

第 6 周：生成 Table/Fig-like 报告。

## 14. 给大二学生的学习路线

先把 OTA 自动扫参中的“参数、仿真、指标、cost、优化器”五件事对应到 LNA。然后补 S 参数和 Smith 圆图，理解为什么 50 欧姆系统需要输入/输出匹配。接着学习噪声系数和 Friis 公式，明白第一级为什么最重要。最后再学习 PSS/HB 和压缩点，把小信号指标扩展到大信号线性度。

实践顺序不要从三阶段毫米波 LNA 开始。先做 1 GHz 以下简化共源级或教学 MOS/RLC 网络，确认 Python 能驱动 OCEAN 并解析 CSV；再换成实验室 PDK 的单级 LNA；最后扩展到多级和 MCR。

## 附录 A：论文表格复现清单

- Table I：已映射到 `src/orfadc/tools`。
- Table II：已写入 `config/variable_ranges_table_ii.yaml`。
- Table III：已写入 `config/specs_table_iii.yaml`。
- Table IV/V/VI：第一版只定义输出 schema，不复写为实验成功。

## 附录 B：RF/LNA 指标公式速查

- `S11 < -10 dB` 通常表示输入匹配可接受；论文 Stage 2 使用 `S11 < -20 dB` 的更严格目标。
- `Gain = S21` 或电压增益，需说明仿真上下文。
- `NF_total` 主要受第一级 NF 和增益决定。
- `ripple = max(gain_band) - min(gain_band)`。

## 附录 C：Cadence/OCEAN 命令速查

实际命令因 Cadence 版本和实验室环境不同而变化。本工程只保留模板：`ocean -nograph -restore <script.ocn>`，真实路径写在本地未提交配置中。

## 附录 D：Python 模块设计

所有 Cadence 调用必须通过 `RunConfig`，所有仿真结果必须保存 `metrics.json`，所有 agent 决策必须保存 `agent_trace.json`。

## 附录 E：Agent prompt 模板

要求模型只输出 JSON，字段包含 `thought_summary`、`action`、`arguments`、`stop_condition`、`risk_note`。完整模板位于 `src/orfadc/agents/prompts/`。

## 附录 F：JSON/YAML schema

第一版用 dataclass 表达 schema，后续可迁移到 Pydantic。

## 附录 G：License 注意事项

clone 第三方项目后先读 `LICENSE`、`README` 和引用论文。只复用结构和思想时也应在 `third_party_notes/` 记录来源。

## 附录 H：实验记录模板

每次实验记录：规格、seed、候选 ID、Cadence 环境、PDK 名称但不含路径、脚本 hash、指标、失败原因、截图或曲线。

## 附录 I：常见错误和排障

- OCEAN 找不到 library：检查 `cds.lib` 和启动目录。
- PSF 解析失败：先导出 CSV/PSFASCII。
- S 参数端口方向错误：检查 port 阻抗和 differential/single-ended 设置。
- NF 异常偏低：检查噪声源、端口和温度设置。

## 附录 J：报告写法

报告中把“论文公开信息”“本工程近似实现”“实验室 PDK 结果”分成三列，避免把不同来源的结果混在一起。

