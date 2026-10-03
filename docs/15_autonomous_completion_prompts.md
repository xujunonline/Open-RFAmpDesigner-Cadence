# Open-RFAmpDesigner-Cadence 全项目步进自动实施提示词

Stage 09 的三级教学候选远端恢复协议见 `docs/105_stage09_three_stage_remote_recovery.md`；planned Manager、同候选 HB、终态收尾与安全续跑见 `docs/106_stage10_three_stage_planned_agent.md` 至 `docs/109_stage10_teaching_agent_pre_second_resume.md`。实际运行中 SSH 控制连接断开的**不完整负例**见 `docs/100_stage10_live_ssh_disconnect_incomplete.md`。单候选 planned 共源诊断的受限隔离侧车见 `docs/113_stage10_incomplete_remote_quarantine.md`；后续远端不可覆盖决定、提交后丢回复及双控制端模拟竞争见 `docs/114_stage10_remote_quarantine_fence.md`，均**仅模拟远端验证**。2026-09-29 SSH 255，旧真实档仍 pending、未实机隔离，不能重派；真实跨主机派发互斥及授权 PDK CDF/PCell、DRC、物理有损耦合、合格 fullchain 仍是独立门禁。

Stage 11 传输侧已有假客户端验证的模型 ID/token/延迟计量与显式价格快照离线估算，见 `docs/110_stage11_model_usage_accounting.md`；可选私有意图/结果两阶段运行档及 agent journal 前缀审计见 `docs/111_stage11_model_call_evidence.md`。三个模型角色与 journal 动作、候选及可用 run ID 的本地绑定见 `docs/112_stage11_model_action_binding.md`。尚未冻结运行价格快照，也没有在线模型、实际报价或 Table VI-like 实测；后续先处理授权价格与未结调用的重启对账，再谈真实调用和费用比较。

原始 Stage 09 教学反馈见 `docs/104_stage09_teaching_three_stage_candidate_feedback.md`：公开 MOS1 三级直接 Spectre 的两个受限 S1 候选，在原始档重审后以 10 GHz/62 fF 的 LC 启发式调整输出副边电感。其**旧归档**没有事前远端身份计划，也没有同候选压缩点；后续 v3/v4 恢复、planned Manager 与 HB 使用**新候选归档**，不得倒填旧档或自动重试。即使新样本局部 S21/S22 改善，规格与物理资格仍失败，必须继续授权 PDK 门禁。

最新软件侧进展见 `docs/101_stage10_two_round_diagnostic_feedback.md`、`docs/102_stage10_second_feedback_pending_recovery.md` 和 `docs/103_stage10_feedback_terminal_snapshot_recovery.md`：两次新 Cadence OA 共源诊断已由确定性 Manager/Searcher/Refiner 按真实原始结果完成一次 RD 反馈；第二轮 planned pending 的**成功归档**恢复/对账，以及 Refine 已写后的三个终态快照断点，均用真实源数据与合成故障协议演练。它们不是 LNA sizing 或论文多智能体结果。接续工作优先处理第二轮终态失败/不完整结果的审计式隔离边界、真实断线演练，并继续授权 PDK CDF/PCell/DRC、物理无源、模型与合格同候选 fullchain 门禁；没有这些证据，不启用论文式成功判定、EB 成功经验或 Table IV/V 数值。

本文件用于从当前已实测的 Cadence 被动二端口 S 参数和 noise/NF 数据链路出发，逐步推进到可审计的方法级复现。适用对象是能读取和修改本地仓库、运行命令及连接授权 Cadence 环境的 Codex 桌面任务。网页版 ChatGPT 可以审阅方案，但无法自行访问本地 F 盘和虚拟机。

使用方式：先阅读 `docs/audits/2026-09-26_audit_closure.md`、`docs/16_implementation_status.md`、`docs/17_noise_data_pipeline.md`、`docs/18_ssh_recovery_from_ota.md`、`docs/20_stage03_active_smoke.md` 至 `docs/39_stage03_inductive_oa_precision.md` 中与当前阶段相关的文件。阶段 00 审查已收尾；原 6 GiB VM 的 A09 曾在约 16 分钟轻负载范围内通过，之后仍出现资源不足。用户启用 Windows 页面文件后，6 GiB VM 仍未达 2.66 GiB 宿主门禁；经正常关机和备份改成 4 GiB 后，3 轮轻负载检查、有源诊断候选、理想 MCR AC 和共源 HB 诊断通过，不能推及长时/高负载。阶段 02 被动 noise、阶段 04 共源 HB 与阶段 05 的被动/有源诊断均已有实测，**都不是合格 LNA 验收**。阶段 01 仍缺有源 LNA fullchain；阶段 03 私有 OA 共源 v1/v2 的 DC/SP-noise、PSFXL/S12 与独立直接 Spectre PSFASCII 已交叉核验。公开电感 OA cell 与高精度 OCEAN/直接 Spectre 交叉核验也完成，但采样 K 仅略大于 1、输出匹配不足，不是稳定 LNA。CDF 参数传播未闭环，不再原样重试无图形 `vfoSetParam`；尚无合格 Virtuoso LNA 或有源 fullchain backend。若一次任务上下文不足，每次复制一个阶段提示词并附“续接提示词”。阶段实施必须有代码、仿真和验收证据，不能以计划代替。`docs/09_step_by_step_operation_guide.md` 使用另一套教学编号，`docs/10_detailed_prompts.md` 是历史参考；最新状态以 `docs/16_implementation_status.md` 和原始运行产物为准。

最新续接提示：Stage 09 的授权 RF 默认器件全链失败诊断见 `docs/88_stage09_rf_diagnostic_fullchain.md`，另一个理想输入梯形网络候选的六点 HB 夹持见 `docs/89_stage09_rf_ladder_hb_diagnostic.md`。两者是不同电路，不能互借压缩点；后者仍为 OA 导出网表副本、非合格物理 LNA。下一轮优先复核本机全量测试和这六点原始归档，再推进授权有损无源/合法器件几何及同候选 fullchain；若工艺物理门禁暂不可达，可推进独立的 agent/基线代码，但不可将教学或诊断档标成规格通过。

续接更新：梯形网络 SP/noise 与其**自身**六点 HB 已组成 `docs/90_stage09_rf_ladder_same_candidate_fullchain.md` 的只读失败报告，按 S1 9–11 GHz/81 点重审，但 `unverified_score`、`spec_pass=null`，不是可供 agent 接收的合格 fullchain。下一步不再重复理想网络搜索或借用默认电路 HB；优先建立授权有损无源、CDF/PCell 合法几何、模型警告和 DRC 的可信边界。若需继续软件侧，可独立推进真实 Manager/Searcher/Refiner 受限调用、BO/工具基线与事务恢复，但必须保留缺少合格 LNA 后端的不可用状态。

Stage 11 已有 `docs/91_stage11_evidence_gated_failure_kb.md` 的私有失败事实 KB：从上述全链报告原始档重审生成首条记录，读取再审计，可选给 `LLMSearcher` 提供只有失败约束/来源 ID 的脱敏上下文。该条目不能作为成功种子或 EB 经验；没有真实在线模型、合格 LNA 成功事实或 self-evolution 消融。后续应先解决合格 fullchain 来源，再扩充经验证的 KB 成功类与多证据 EB，而非把诊断失败改写为成功经验。

可选模型 Manager 的**现有候选队列优先级**见 `docs/92_stage11_llm_manager_priority_contract.md`：模型只能选下一评估的既有候选 ID，异常回退 FIFO；journal 可重放优先级并在派发前中断时按记录恢复。这是受限调度接口，不是论文完整 Manager 的 Search/Refine/Stop 策略，也没有在线模型和同预算消融。后续扩展动作前必须保持候选快照、预算、计划派发和原始仿真审计的状态机一致。

## 0. 仓库现状与依赖

新增路线 B 入口见 `docs/33_stage03_teaching_mos1_route_b.md`、`docs/38_stage03_public_oa_closed_loop.md`、`docs/39_stage03_inductive_oa_precision.md`：公开 MOS1 教学共源已用直接 Spectre 跑通四个同网格 VBIAS 点；公开 Virtuoso OA 平面和源退化电感 cell 均由可重建 OCEAN 脚本完成 schematic→netlist→DC/SP-noise→PSFXL 导出→Python 审计。电感 cell 的旧六位导出导致近边界 Rollett K 错判，现默认 15 位导出且有独立直接 Spectre PSFASCII 交叉验证；高精度 K 略大于 1 也仅是采样近边界结果。HB 高功率因模型警告停止。它只扩展 Stage 03/04 的方法级诊断，不关闭路线 A 的**授权 PDK CDF/PCell**、合格 LNA fullchain 或论文数值复现门槛；后续代理必须先查上述文档再决定是否复用路线 B。

同一路线的理想输出 L/C 单频匹配与宽带失败见 `docs/34_teaching_output_match_probe.md`：10 GHz S22 可改善到约 -31 dB，但 8–12 GHz 最差仍近 0 dB、S11 和纹波失败。不要将其当成阶段 07 的论文式输入/级间宽带匹配工具，后续应优先核实授权 PDK 的 CDF/PCell 和物理无源约束。

随后公开 MOS1 有损输出匹配诊断见 `docs/42_stage03_damped_teaching_lna.md`：150 Ω 阻尼候选在 8–12 GHz/161 点恰好覆盖带边，最差 S11/S22 约 -10.13 dB，但纹波 3.32 dB、匹配余量约 0.13 dB，且理想器件未受 Q/自谐振约束。四个有效 HB 功率点与小信号实际网表逐个绑定；0 dBm 模型警告点被排除，P1dB 未夹住而保持 null。此项是教学路线 B 的同电路方法诊断，不满足 Stage 03/04/05 的合格 LNA 门槛。

该阻尼拓扑又在全新公开 Virtuoso OA cell 通过 `schCheck=(0 0)`，经典 OCEAN/Spectre DC/SP-noise 和 15 位 161 点导出；与此前**独立**直接 Spectre/PSFASCII 的逐频 S/noise 数值交叉核验通过，见同一文档。失败的 SKILL 语法/悬空端子 cell 均保留；新 OA 运行不是授权 PDK，直接模板 HB 也不能被改称 OA 同次大信号分析。

公开 MOS1 的初版 cascode 首级完成同条件 161 点直接 Spectre DC/SP/noise 与双管工作点审计，也在全新 Virtuoso OA cell 完成 schematic→OCEAN→Spectre→15 位导出；两份独立归档的复数 S 与 noise 逐频交叉核验，见 `docs/43_teaching_cascode_first_stage.md`。加上管后采样隔离/稳定指标改善，但此偏置下带内最差 S21 下降、NF/纹波增加；不能用单次比较代替 Stage 1 sizing。OA 双管工作点现已接入正式 OCEAN 导出、自动 runner 和只读审计；同参数的新 OA cell 只用于通路验收，不能重复计入优化样本。后续另建的三级公开教学结构见下文；它仍不是论文的工艺电路或合格 fullchain。

VCAS=0.85/0.95/1.05 V 的同网格公开 MOS1 cascode 直接 Spectre 小预算扫描与源归档重算见 `docs/44_teaching_cascode_bias_sweep.md`；0.85 V 的 M1 VDS 裕量仅约 2.3 mV。1.05 V 又经新 OA cell 的参数传播、OCEAN 导出及独立直接 Spectre 逐频交叉核验。报告只说明局部偏置敏感性，不是连续寻优、授权工艺结果或论文 Stage 1 资源分配验收；同参数 OA 重复运行只算通路验收，勿冒充新样本。

Stage 09 的公开 MOS1 三级**直接 Spectre**结构探针及三点末级无源实测见 `docs/45_teaching_three_stage_spectre_probe.md`：单端 cascode 首级、两级差分共源、理想互感、交叉电容和 1787 Ω || 62 fF 差分端口已形成可重建的 DC/SP/noise 源归档。同一教学基线现已在新 Virtuoso OA cell 由 OCEAN 实跑、导出并同独立直接 Spectre 逐频/六管工作点交叉核验，另有一键 runner 复验，见 `docs/46_stage09_public_oa_three_stage.md`。同拓扑低驱动 HB 与 47 元件 OA/HB 配对见 `docs/47_stage09_three_stage_low_drive_hb.md`、`docs/48_stage09_three_stage_same_circuit_pair.md`；后续十点真实 Spectre HB 扫描给出**教学诊断级** 10 GHz P1dB，夹点 7/9/11 谐波敏感性有六个源点，见 `docs/49_stage09_three_stage_hb_compression_diagnostic.md`、`docs/50_stage09_three_stage_harmonic_sensitivity.md`。同一基线 0.1–20.1 GHz/401 点离散 K/Δ 带外探针见 `docs/51_stage09_three_stage_broadband_stability.md`，采样判据通过但输出匹配/增益/纹波失败。仍无**合格 LNA**压缩点、物理 MCR、授权 PDK 或完整候选评分，阶段 09 仅 `partial`。

Stage 08 的新一端口门禁见 `docs/52_stage08_passive_quality_gate.md`：公开 RLC 网表已用 Spectre 原始 SP、Touchstone 和解析阻抗式校准；授权 PDK 的一个**默认参数**螺旋实例和另一个直接写入 `w=7u` 属性的新 OA 诊断 cell 已经 `schCheck`、导出网表和独立 Spectre SP 运行，两个 591 点源档与哈希清单可重审。默认/变体的 8–12 GHz 最小 Q 约 10.524/10.515，均低于本项目教学筛选阈值 15；两次均有 5 条重复 `scalefactor` 模型警告。配对网表仅宽度属性不同，最大复数 S11 差约 0.04082，但**未执行 CDF 回调，未证明 PCell 合法几何**。至 30 GHz 未见电抗过零仅为模型扫频下界。耦合、角落和 EM/PEX 都未验证；不能因此将理想三级无源替换为“已认证 PDK MCR”。

同一门禁现额外涵盖**另一种对称型默认螺旋器件**：新用户库 OA 一端口及独立 591 点 Spectre SP、原始数据审计均通过，8–12 GHz 最小 Q≈10.714，仍低于 Q≥15 教学门槛；5 条同类警告。与标准型差异不是单因素几何实验。见 `docs/52_stage08_passive_quality_gate.md`；耦合与物理资格门禁不变。

Stage 09 新增授权 PDK **有源 MOS + 理想无源**三级 OA 诊断，见 `docs/53_stage09_pdk_hybrid_three_stage.md`：新 cell `schCheck=(0 0)` 并成功网表化，直接 Spectre DC/六管 OP/161 点 SP/noise、PSFASCII 与混合端口 S2P 独立审计通过。首个直接运行因未导出 OP 文件而保留失败；后一个 0 errors/5 PDK 配置警告。最差 S21 约 -58.68 dB、NF 约 46.85 dB，完全不是合格 LNA。同网表另起 AC 内部节点探针，在 10 GHz 发现首级和两段级间耦合均有电压衰减；AC 电压比不等于 S21。CDF/PCell、物理无源、压缩点和真实候选 fullchain 均未通过。后续优先做受控单因子诊断与 CDF 几何核验，再谈参数寻优；不得用这份数据填论文结果。

Stage 09 首个单因子派生见 `docs/54_stage09_pdk_k12_sensitivity.md`：在私有 OA 网表**副本**只改理想 K12 0.45→0.8，SP/noise 与并联 AC 探针独立实跑，源差异、远端回读和双基线均可审计。10 GHz S21 改善约 4.86 dB，但带内最差 S21/NF 仍约 -53.93/42.10 dB；`k=0.8` 无物理可实现性证据。不要把派生网表称为新 OA schematic，或把理想耦合敏感性当作论文 MCR 优化。下一步优先 CDF/PCell 与实际耦合器件 Q/k/SRF 门禁；虚拟机当前没有可用的用户 Virtuoso 图形会话，不原样重试失败的无图形回调。

Stage 09 新发现授权 PDK 的专用 RF MOS，见 `docs/55_stage09_rf_default_device_probe.md`。只读 OCEAN 先因系统默认 Xvfb 不存在而失败；按项目已配置的用户 Xvfb 路径另起成功探针。随后新 OA 三级的六管**完全使用器件默认 CDF 参数**，`schCheck=(0 0)` 并导出网表，直接 Spectre DC/工作点/161 点 SP/noise 独立审计通过。最差 S21/NF 仍约 -33.92/25.57 dB，供电约 9.82 mA；这与通用 MOS 基线同时改变模型和几何，不能称单变量优化。默认参数网表不等于 RF 可调几何的 CDF callback/PCell 验收，更不等于物理耦合 MCR 或 LNA fullchain。后续优先内部节点定位与授权交互式几何验证；不把新数据填入论文 Table IV/V。

同一 RF 默认器件 OA 网表另起 161 点 Spectre AC 内部节点探针并独立审计：10 GHz 三段有源电压比分别约 +1.85/+3.68/+2.92 dB，首级、第二级间及输出耦合约 -8.85/-6.57/-5.05 dB。并联理想 AC 源下的电压比不是 S21；结果只指向优先处理**可实现的有损耦合与宽带匹配**，不能直接提高理想 k 后宣称物理 MCR 或 LNA 达标。仍需 RF CDF/PCell、Q/k/SRF、角落/带外稳定与压缩点。

同一 RF 默认器件 OA 源网表的**受控端口激励派生**又完成 -70 dBm/10 GHz 低驱动 HB，见 `docs/56_stage09_rf_default_low_drive_hb.md`。派生输入与原 OA 仅端口类型及新增分析不同；原始 HB 端口相量与同次 SP S21 的功率增益差约 0.000078 dB，且 SP/noise/DC/六管 OP 数值与独立小信号档一致。此点没有高功率夹持，不能填 IP1dB/OP1dB 或称合格 LNA；后续的物理无源、CDF/PCell 和警告门禁不变。

后续又形成**同一不合格三级诊断电路**的 7 点真实 Spectre HB 功率扫描，见 `docs/57_stage09_rf_default_hb_compression_diagnostic.md`。聚合器逐点原始档案复审并用前三点建立线性参考，在 -11/-10 dBm 的 1 dB 宽相邻区间插值得诊断级 IP1dB≈-10.579 dBm、OP1dB≈-33.328 dBm；`spec_pass=null`。夹点 7/9/11 谐波六个原始档案的局部比较已见 `docs/58_stage09_rf_default_harmonic_sensitivity.md`；不代表全功率/全频带收敛。这不是合格 LNA fullchain、论文数值或物理 MCR 验收，尚需授权工艺无源和几何资格。

路线 B 的输入 LGS/LSS 九点/四点网格见 `docs/35_teaching_input_matching_grid.md`，另有 seed=17 的四点随机基线见 `docs/40_stage07_teaching_random_baseline.md`：逐点真实 Spectre 与整体只读审计通过，但自定 NF/S11 诊断目标下均未达 -20 dB S11。固定 L 的 200/300/400 um 教学 MOS1 同偏置表见 `docs/37_teaching_multi_width_lookup.md`，其源运行与表均经只读审计；无三级 stage 映射。后续先复核已有归档，不无故重跑相同点；这些记录不改变面向论文候选的 `impedance_matching` 和授权 PDK `active_sizing` 后端不可用状态。

阶段 05 的被动诊断候选实测与边界见 `docs/27_passive_diagnostic_candidate.md`；OA 共源候选与九点 HB 的同电路配对和只读报告见 `docs/41_stage05_same_circuit_diagnostic_pair.md`。两次原始作业的实际电路主体、伴随模型及同频 SP 已交叉验证，但仍不是合格 LNA；“尚无真实候选 backend”仅指尚无**已实机验收的有源 LNA fullchain**。

以下为 2026-09-26 本轮实测后的续接快照；每次执行前仍须重新检查：

| 能力 | 当前证据 | 下一个缺口 |
| --- | --- | --- |
| 论文与教学资料 | `references/paper/`、`docs/01` 至 `11`、`docs/audits/`；阶段 00 已通过；式 (3) 的 `Z21` 子表达式和本项目对称理想网络已用 Spectre AC 校准，印刷 `Y11` 疑点保留 | 作者原意、物理 MCR、源/负载参考平面仍待核；不能重做审查代替开发 |
| Windows 到 Cadence | `remote_runner.py`、`docs/18_ssh_recovery_from_ota.md`、`docs/31_vm4g_memory_acceptance.md`；4 GiB VM 的 A09 3 轮轻负载通过 | 每次实测前复查 SSH/Tools/宿主内存；长时、高负载另验 |
| S 参数 | 被动二端口 Spectre S 参数及 noise/NFmin、私有 OA 共源和教学共源的 SP/noise 原始数据均有独立审计 | 合格 LNA 的稳定匹配、全链 noise 和压缩点；诊断结果不可当论文 LNA 结果 |
| RF 数据解析 | `touchstone.py`、`psfascii_reader.py`、`ocean_ascii.py`、`run_passive_noise.py`；47 点 S 参数与 NF/NFmin 实测、F/NF 交叉核验；v1 schema/运行时 guard | 阶段 01 的真实 LNA spec/candidate/seed/timeout 数据链与压缩点 |
| 有源器件链路 | 私有 OA 共源 v1/v2 均 `schCheck=(0 0)`、网表化；经典 + batch OCEAN 完成并导出 PSFXL 47 点，与独立直接 Spectre PSFASCII 交叉核验。公开 MOS1 的平面/源退化电感/阻尼共源/cascode OA cell 由 `run_teaching_oa.py` 实跑与审计；电感版六位 K 精度失真已用 15 位重导出纠正，阻尼与 cascode 的 161 点 OA/直接 Spectre 亦独立逐频核对；cascode OA 双管工作点已在新归档中自动导出、只读审计并与独立 Spectre 16 字段对照，见 `docs/38_stage03_public_oa_closed_loop.md`、`docs/39_stage03_inductive_oa_precision.md`、`docs/43_teaching_cascode_first_stage.md` | 无授权 PDK CDF/PCell 参数传播验收、合格 LNA、可实现宽带匹配、规格通过或 LNA 压缩点；原始受限产物仅在忽略目录 |
| 三级教学结构 | `docs/45` 至 `48` 的三级直接/OA/HB 同电路证据；`docs/49` 的十点 HB 诊断级 P1dB，`docs/50` 的夹点 7/9/11 谐波局部敏感性，`docs/51_stage09_three_stage_broadband_stability.md` 的 401 点采样 K/Δ | 尚无该三级**合格 LNA**候选的 P1dB、物理匹配/MCR、PDK CDF/PCell 或 LNA fullchain；不能用教学指标填论文结果 |
| 候选运行证据 | `evidence.py` 对同一运行的路径、大小、SHA-256、候选快照与日志做校验；被动及 OA RD/VBIAS 有源诊断后端均有独立实测和原始数据重提取，见 `docs/25_candidate_evidence_manifest.md`、`docs/29_active_diagnostic_backend.md`、`docs/31_vm4g_memory_acceptance.md` | 无合格 LNA/fullchain；清单和共源诊断不能证明论文规格通过 |
| 工具中间件 | 四工具受限注册表；公开 MOS1 固定 L 的多 W/偏置表征、九点输入匹配教学 cost、理想 MCR AC、公开 RLC Q/SRF 解析校准及 PDK 螺旋默认/宽度属性一端口 SP 均有原始结果 | PDK CDF 回调/PCell 合法性、警告解释、耦合/EM/角落、授权 PDK 三级 lookup、Stage 2/3 论文式真仿真及合格 LNA fullchain |
| 多智能体 | 确定性 Manager 已接真实共源诊断 evaluator、搜索候选参数快照、journal/候选证据绑定与归档审计；可选模型传输与 Searcher 提案仅经假客户端测试 | 合格 LNA observation、pending 幂等恢复、失败变异、Refiner/Manager 模型策略、在线授权调用、检索与消融 |
| 实验与图表 | Table III YAML 已导出 10 行规格输入 CSV；教学运行有独立指标/趋势汇总 | Table IV/V/VI-like 和 Fig. 7–11-like 需合格 LNA 多种子实验，不可由教学网格填充 |
| OCEAN 脚本 | `verify_design.ocn` 与公开教学 MOS1 的 create/run/export 三脚本已分别实机通过；后者还覆盖阻尼共源与 cascode OA/DC/SP-noise，但不是论文工具 | `run_sparam/noise/compression/fullchain` 等通用 LNA 脚本仍是模板，不因教学 OA 或被动测试而标为通过 |

当前已验收的原始结果：S 参数 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/`，被动 noise `results/runs/rf_smoke/passive_noise/20260926T011402Z_80ac76f0/`，A09 `results/logs/a09_20260926_acceptance/`。这些目录默认被 Git 忽略，不能把仅存在于文档的路径当成新机器上的运行证据。`not_lna_result=true`、`spec_pass=null` 是被动结果的强制边界。

进入当前阶段前先运行 `git status --short`。工作树可能已有未提交更改；理解后继续，不覆盖或回滚。`results/runs/` 默认被 Git 忽略；真实仿真文件和私有配置应留在本地。

依赖顺序：已完成论文/规格核对和被动数据链路 -> 阶段 01 统一指标契约 -> 阶段 03 有源模型/PDK 与单级 LNA -> 参数扫描和 lookup -> 四个工具 -> 确定性 agent -> LLM/KB/EB -> baseline/消融 -> 多规格实验 -> 图表与报告。MCR、PEX 与版图放在单级 LNA 全链路成功之后。阶段 02 可先于阶段 01 的剩余契约独立完成；不要因此跳过阶段 01。

## 1. 总控提示词：自动逐步推进

复制以下整个代码块给拥有本仓库访问权的 Codex：

```text
你现在负责继续实施 F:\Open-RFAmpDesigner-Cadence，而不是只写方案。先读 README.md、docs/00_index.md、docs/15_autonomous_completion_prompts.md、docs/16_implementation_status.md、docs/17_noise_data_pipeline.md、docs/18_ssh_recovery_from_ota.md、审查问题台账、当前代码/测试及 git status。论文原文是事实冲突时的最高依据；只有发现具体新矛盾时才针对性复核论文，不重新发起已收尾的阶段 00 全量审查。

已完成基线：阶段 00 审查通过；A09 仅在约 16 分钟轻负载条件下通过；被动二端口 S 参数及 Spectre noise/NF 数据链路实测通过。阶段 01 已有 v1 指标 envelope、fail-closed guard 和候选上下文一致性检查，但真实 LNA spec/candidate 数据尚未贯通。私有 OA 共源 v1/v2 testbench 均通过 `schCheck`；经典 + batch OCEAN 完成 DC/SP-noise，PSFXL 经 OCEAN 导出 47 点 S/NF/电流，各自与独立直接 Spectre PSFASCII 指标交叉核验。v2 的最差 S21 仍为负，S11 近 0 dB，虽 NF 改善但电流和 ripple 增加；两轮都有模型警告，不是合格 LNA。后续共源诊断 HB 已有真实夹持的压缩点数据链，但所有 smoke 仍 not_lna_result=true、spec_pass=null；没有合格 Virtuoso LNA、合格 LNA 压缩点或论文数值复现。先核对最新证据，再实现源退化/匹配并核对 PDK 几何参数；不要覆盖或无故重跑已通过的结果。附带许可证说明仅作诊断资料，不照其文字修改许可文件。

目标：按 docs/15_autonomous_completion_prompts.md 的阶段门槛，把 Open-RFAmpDesigner-Cadence 推进到证据支持的最高可完成层级。自动执行当前可行的文件修改、测试、受控远程 Cadence 仿真、结果归档和文档更新。每阶段先列出已经验收、待补和依赖受阻的子项；只对待补项动手。独立工作可并行推进，但不能把下游局部成功当作上游全通过。一次任务内完成可行的连续工作；若外部依赖受阻，转做不依赖该资源的任务并记录边界。

每阶段工作循环：
1. 查看本阶段输入、代码、论文依据和相关结果；建立“已验证/仅模板/未实现/受阻”清单。
2. 选择最小、可复核的实现范围，实际修改代码、网表、脚本和文档。
3. 运行针对性测试；有授权环境且前置条件具备时运行真实 Spectre/OCEAN，并读取原始日志和产物。
4. 保存每次运行的参数、网表或可公开模板、原始结果、标准化 CSV、metrics.json、错误记录和数据来源。商业 PDK 生成的受限文件只放被 Git 忽略的本地目录。
5. 对照验收门槛做阶段判定。更新 docs/16_implementation_status.md 和本阶段实验记录；仅在入口或操作步骤实际变化时更新 docs/00_index.md、docs/09_step_by_step_operation_guide.md。失败时定位根因并修复；外部阻塞时记录具体证据、受影响项和独立可做的后续工作。

贯穿约束：
- 论文 PDF 和原文优先于旧聊天与翻译；标清“论文给出”“本项目选择”“实测结果”。对 Table II/III 和公式逐项核对，发现差异要修正并留下说明。
- dry_run、mock、解析器样例、理想被动电路、教学 MOS、授权 PDK 仿真和 post-layout 是不同证据等级；状态、文件名和表图必须显式标注来源。缺失关键指标时返回 incomplete/failed，不得默认为通过。
- 不虚构 NFmin、IP1dB、pass@1、Cadence 数值或作者实验；不能声称严格复现 TSMC N65。
- 不把密码、私钥、商业模型、PCell、受限 netlist、许可证或个人连接详情写进仓库、prompt、LLM 请求或公开报告。不输出私有配置全文。
- Agent 只能提出经过 schema 校验的数值决策；Cadence backend 是指标来源。LLM 未配置时使用确定性策略和 mock 测试，标注真实 LLM 对比尚未完成。
- 不因单项外部阻塞而停止整个项目：继续做纯 Python、开源模型或教学电路可完成的工作；需真实授权工艺才能验收的项目明确保持 blocked。不要以教学模型冒充授权 PDK。
- 控制仿真预算：先 1 candidate/1 seed，再小规模扫参，最后才做 10 specs x 5 seeds。运行时间、模型费用和计算资源须在结果中记录；不要无限搜索。
- 每次远端运行前先检查 SSH/Tools 和宿主可用内存；A09 只覆盖当时轻负载窗口，不授权多小时/并行扫描。资源不足或连接不稳就停止负载并保留失败证据，不通过硬重置制造通过。
- PDK 探查只读、限已知 cds.lib/项目库和经授权的目录；能访问文件不等于获得再分发许可。私有库名、模型路径、原始受限网表不进入仓库、提示词或外部 LLM 请求。
- 尊重已有未提交修改，不删除失败结果；除本次用户明确授权并完成的 6→4 GiB 变更外，不擅自改变虚拟机配置、许可证或宿主机网络设置。

每阶段完成时输出：修改文件、执行命令、测试/仿真证据、数据来源、未完成项、下一阶段第一项。只有结果和证据满足阶段门槛时才写“完成”；不能严格复现论文数值的边界始终保留。
```

## 2. 阶段提示词

下列提示词可单独复制执行。它们均继承总控提示词中的证据等级、隐私、运行预算和状态标注要求。

### 阶段 00：基线审计与论文对齐

当前已完成；以下提示词仅在出现可定位的新论文事实冲突或审查证据损坏时使用，不作为新任务的默认起点。

```text
在 F:\Open-RFAmpDesigner-Cadence 实施阶段 00。首先按 docs/16_paper_to_project_audit_prompt.md 执行从英文论文到整个仓库的彻底审查与修复。本阶段不能仅核对 Table II/III 或现有测试；必须覆盖论文、全部相关代码/网表/配置/测试/文档、跨层数据链、真实运行证据、未跟踪文件以及旧工作树修改。对 Table I/II/III、公式 (1)-(3)、Table IV/V/VI、Fig. 7-11 和多智能体描述建立可追溯来源表，查明并修正错误。

实际修复当前环境能修复的问题；编译、运行现有测试、dry-run 和可用的受控 Cadence smoke；记录基线及修复后的证据。生成 docs/audits/ 下的审查交付物和 docs/16_implementation_status.md。修正过时状态，但保留历史事实。不要改动无法由论文或运行证据证明的数值。

验收：符合 docs/16_paper_to_project_audit_prompt.md 的全部完成门槛；高优先级可修复问题关闭并验证，外部受限项明确登记。审查未通过时不得跳到下一阶段。
```

### 阶段 01：RF 指标契约与失败语义

```text
实施阶段 01 的剩余部分。已有 Spec 数值校验、缺测/NaN 拒绝、被动 S 参数与 noise/NFmin 解析、带边覆盖/log(f)-dB 插值、真实文件对齐及被动来源评分护栏，先跑测试确认，不重写这些已通过的功能。审阅 docs/19_rf_metric_contract.md、src/orfadc/schemas.py、extract_rf_metrics.py、noise_metrics.py、cost_functions.py 和 tests，建立可机读的统一 JSON Schema：spec、candidate、analysis、units、频带/参考平面、metrics、violation、simulation_status、spec_pass、source、run_id、seed、timeout。实现 schema 校验和失败语义，区分 |S21| dB 与功率增益；为 NF/NFmin、电源电流、IP1dB/OP1dB 与 ripple 保留明确单位/来源。未实现的压缩点字段须保持 unavailable，不能用教学或被动值补全。

使用小型确定性样例测试频带未覆盖、带边、缺测、非法单位、来源错误和通带为空。给真实运行、解析样例、dry-run 分别定义机读状态；已有被动结果只作迁移回归，不回填成 LNA pass。为后续阶段提供版本化 metrics.json schema；写 docs/16_implementation_status.md 的阶段记录。

验收：关键指标缺失绝不 pass；模拟和来源状态可机读；单元测试通过。
```

### 阶段 02：Spectre noise 数据链路

当前已通过“被动二端口数据链路”验收；以下提示词仅用于迁移到另一台机器或实测回归，不代表有源 LNA 噪声已测。

```text
复核阶段 02 被动数据链路。先查看 results/runs/rf_smoke/passive_noise/ 下最新的真实 run，确认网表、Spectre 日志、47 点 PSFASCII/S2P/CSV/metrics 和来源标记。只有证据缺失或换机器时，才经 SSH/Tools/内存门禁运行 python -m orfadc.experiments.run_passive_noise。当前本机 Spectre 25.1 已证明 sp donoise=yes、oprobe/iprobe 和 noisedata=twoport 可用；真实 PSFASCII 有 NF/NFmin dB 与 F/Fmin 线性迹线。不要把被动结果称为 LNA 性能。

保存 netlist、spectre.log、原始 PSFASCII/其他原始格式、noise.csv、metrics.json、失败日志。以两个以上频点验证单位和频率轴；用测试覆盖解析失败、频率不对齐、缺少 NFmin。更新 docs/09 和新增的阶段实验说明。

验收：真实 Cadence noise 分析完成，解析值可在原始数据中追溯；如果所用 analysis 不支持 NFmin，记录 unavailable 并继续，不填假值。
```

### 阶段 03：授权 PDK 识别与单级 LNA

续接限制：`docs/94_stage03_mutter_x11_focus_boundary.md` 已实测隔离 Mutter 注册成功；鼠标点击档目标位置因 WM 移窗不可核验，另一次 X11 外窗焦点请求虽立即读回同一窗口 ID，Cadence 仍为 `hiGetCurrentForm=nil`、`Wfg=InfoAll` 且 X I/O 异常退出。停止当前 Xvfb/`-nographE` 路径上的自动键盘写值。后续需授权交互桌面或工艺/EDA 负责人确认表单与 CDF/PCell 合法映射，不能继续把窗口管理器存在当成门禁通过。

再补充：已在独占 Xvfb/Mutter 上做完整 Virtuoso GUI（不带 `-nographE`）的只读对照，远端可用物理内存门禁通过，仍是 `hiGetCurrentForm=nil`/`InfoAll` 与 X I/O 退出；详见同一 `docs/94`。虚拟机 `X0` 属于 GDM 登录界面，不是可借用的用户设计桌面。停止对当前无交互路径重复焦点试验；除非获得新的授权桌面/工艺指导，否则优先推进独立的 Stage 10/11 事务和工具工作。

最新复核：`docs/97_stage03_absolute_wfg_click_boundary.md` 用点击时的**绝对** X11 窗口几何纠正旧档相对坐标歧义，分别在 `-nographE` 与完整 GUI 做了一次只读 Wfg 点击；两份新档的点击位置可审计，然而 Cadence 内部延时焦点仍为 `InfoAll`，`hiGetCurrentForm=nil`，且 X I/O 异常退出。旧归档的目标未证实结论保留。不能因此尝试键入参数或将 CDF/PCell、模型寄生或 DRC 门禁标记通过；下一有效输入是授权交互桌面或工艺/EDA 指导。其间继续推进独立 Stage 10/11 项。

```text
继续阶段 03。先读 docs/20_stage03_active_smoke.md；直接 Spectre 共源级 smoke 已完成但不是 LNA。私有 OA 共源核心和独立平面 testbench 已通过 `schCheck=(0 0)`；OCEAN `createNetlist` 已成功。首次默认 ADE 高性能模式下等待许可证超时；采用经典 Spectre、batch 控制及运行根目录后，v5 OCEAN/ADE 完成 DC + `sp`/noise、结果读取及干净退出。v5 PSFXL 经 OCEAN 导出 47 点 S/NF/电流，同一 OA 网表的独立直接 Spectre PSFASCII 已交叉核验；两次运行来源必须分开。现有电路最差 S21 为负，`not_lna_result=true`、`spec_pass=null`。不要重建、覆盖或再次试验本机不支持的 ADE `psfascii` 选项。先从已有结果核对 DC 器件工作区，设计输入匹配与增益改进，并将新候选接入阶段 01 契约；实跑前仍做资源门禁，所有新运行用独立目录和完整日志。不要漫扫私有目录，也不要把真实路径、PCell、模型、受限 netlist、许可证记录或库清单写入 Git/LLM 请求。教学模型须标为 teaching_model。

补充当前进展：docs/21_stage03_v2_candidate.md 已记录第二个 OA 共源级尺寸/负载对照，OCEAN 与独立直接 Spectre 均 0-error，工作点有 VDS 裕量，最差 S21 仍为 -2.51 dB、S11 接近 0 dB。下一候选优先验证源退化与匹配、稳定性和无源器件可实现性；查清宽度变化后 PDK 几何寄生字段未明显变化的原因。不得把 v2 当作已完成 LNA。

再补充：docs/22_stage03_ideal_match_probe.md 的 v3 只是在 OA 网表复制件上加入理想电感并直接 Spectre 仿真。10 GHz S11/S21 峰值改善但宽带起伏约 25 dB，采样网格 K<1，且未证明片上无源可实现；不是新 OA schematic 或可通过的 LNA。下一步先加密频率、检查稳定性/带外和实际无源约束，再决定是否建立新的 OA cell。不要重复 v3 单点扫描。

最新复核见 docs/23_stage03_stability_cdf_followup.md：原 v1/v2 PSFXL 已各自补导出 S12，OCEAN 与独立直接 Spectre 均给出 K<1；解析器必须检查曲线的同源 resultsDir。理想 LS=70/150/300 pH 已在 8-12 GHz 加密扫频，300 pH 虽在该带内采样点 K>1，0.1-20 GHz 粗网格仍 K<1，且 S11/ripple 不合格。不要重复该小扫描或误报稳定 LNA。CDF 只读属性提示宽度相关几何可能未由 callback 更新；此前新 cell 诊断未留下有效报告，不能仅由显示 I/O 报错推断 callback 原因。最新分解诊断见 docs/24_stage03_cdf_write_diagnostic.md。失败 cell 不复用、不清理；之后才在有 Q/自谐振约束下选可实现网络，补带内/带外加密、稳定圆/实际端接、角落与压缩点。每一步保存独立日志、资源门禁和失败原因。

更新纠偏：docs/24_stage03_cdf_write_diagnostic.md 显示，首个单 MOS 写入脚本在 `vfoSetParam` 前因设计库未注册失败，第二个新 cell 虽到参数设置步骤，仍没有保存/报告。不要把全部失败归因于显示连接，也不要原样再试无图形回调。先用授权交互式环境确认该 PDK 的初始化/回调及网表传播。独立推进阶段 10 时，Refiner 已改从仿真 envelope 重算 violation，Manager 已有确定性预算、去重和单 pending 调度；下一门槛是 backend 原始数据重提取、持久化 trace、参数变异和真实闭环，不能让 LLM 直接提供可接受的指标 JSON。

新增证据见 docs/61_stage03_rf_layout_readonly.md 至 docs/68_stage03_cdf_callback_response_probe.md：两个**新用户库 layout cell**已完成默认/单参数变体的低层 PCell 几何响应。首次 `strmout` 虽返回 0 却无图形，已保留失败档；显式绑定技术库后两个新归档均有非空 GDS。两个 Calibre DRC 作业都正常结束，但各有非零违规和运行警告，`drc_pass=false`。完整 Virtuoso `-nographE` 的只读 CDF 与旧 OCEAN 报告逐字节相同。随后从 v2 schematic 复制全新用户 cell，经属性表单单独修改 `Wfg`、Check and Save、独立 OA 读回及 Spectre 网表导出；`Wfg` 已持久化，模型 `w/l/nf` 未变，但多个寄生参数改变。默认单管尝试因 PDK 长度下限报错，失败档保留。原 v2 与新 cell 的独立同条件 Spectre DC/SP/noise 及 47 点 OCEAN 导出已交叉审计：两次均 0 error、均有五条既有模型警告，S21/NF 曲线有可测差异。在另一个全新用户 cell 上显式调用 `Wfg` CDF callback 后，独立网表只有 `pd/ps/sa/sb` 四个寄生参数相对表单变体变化；同条件 47 点 15 位 SP/noise 与 DC 电流导出全部相同。**调用 callback 不等于验证其工艺正确性**。下一步在授权环境做真实 GUI 字段交互编辑，由工艺负责人审阅 Wfg/模型宽度/寄生关系和 DRC 违规，再做同候选 layout/网表/角落门禁。不能把 GDS/Calibre 退出码、字段赋值、曲线差异或只读 CDF 报告提升为合格 PDK LNA。

补充只读焦点探针：`docs/69_stage03_form_focus_probe.md` 证明属性表单显示，但即时/延时字段焦点查询仍为 `InfoAll`；一次延时运行超时，另一次回调写完报告后出现致命 X I/O 异常，审计为 `focus_not_proven`。未发送键盘输入。下一步先查明窗口与 Wfg 字段焦点并实现干净退出，才可进行真实 GUI 单字段编辑；仍需工艺负责人审阅 Wfg/模型宽度/寄生关系和 DRC 违规，以及同候选 layout/网表/角落门禁。公开 MOS1 固定阻尼网络的偏置单因素复核见 `docs/70_stage03_teaching_bias_tradeoff.md`：0.55/0.60 V 降电流同时恶化全带匹配、增益和 NF，不继续该网络 HB，不能据此推断压缩点或迁移到授权 PDK。

授权 PDK `SFE-1131` 重复缩放警告的**只读定位**见 `docs/84_stage03_sfe1131_scale_probe.md`：已打印的五个后写入位置与日志有效值一致，但 Spectre 抑制了后续同类警告，未核实全部 include/角落及模型尺寸语义。该私有报告不改变警告未解决、CDF/PCell、DRC 或 LNA fullchain 门禁；后续需要授权 PDK/仿真负责人审阅，不能自行改 PDK 或用此报告豁免。

验收：至少一个有源 RF 电路在 Cadence 中有真实 DC、S 参数、noise、power 结果和完整日志；报告区分授权工艺与教学模型。只读发现 PDK 文件、仅 netlist 成功或仅被动 smoke 均不满足验收；没有器件/模型的可验证调用方法时停止猜测。未完成真实 PDK 验收时不得宣称完成 PDK LNA。
```

### 阶段 04：大信号压缩点

```text
继续阶段 04；先读 docs/32_stage04_hb_diagnostic.md。共源诊断网表已有 Spectre 25.1 HB 7 谐波/9 点实测，基波输出功率、同次 S21 小信号核对、每点哈希清单与 1 dB 夹持插值通过；`audit_hb_sweep` 已从 7 点/9 点归档独立重提取，但它们不是稳定匹配的合格 LNA。后续先解决阶段 03 门槛，在真实 LNA testbench 上重复至少四个输入功率点，其中至少两点建立小信号线性区；统一端口 dBm/50 Ω 功率参考平面，核对谐波数、角落与功率步长，再用相邻实测点插值求 IP1dB/OP1dB。若未夹住应报告 unbracketed，不得外推。保存功率扫描 CSV、原始 PSFASCII、日志、质量标志和每点来源。

验收：压缩点可从实测曲线重算；未夹住或 HB/PSS 失败有结构化失败原因；单元测试覆盖无压缩、单调性异常、边界插值。
```

### 阶段 05：完整候选仿真后端

```text
继续阶段 05；先读 docs/25_candidate_evidence_manifest.md、docs/27_passive_diagnostic_candidate.md、docs/29_active_diagnostic_backend.md、docs/31_vm4g_memory_acceptance.md 和 docs/41_stage05_same_circuit_diagnostic_pair.md。现有 evidence.py 校验同一运行目录的路径、大小、SHA-256、候选快照和日志；`candidate_runs.py` 独占预留目录。被动白名单候选已有 Spectre 成功与真实 SSH 权限失败，不重复。OA 共源诊断后端只允许旧私有网表的 RD/VBIAS 数值变化，4 GiB VM 上已经归档一次 SFE-868 失败和修复后一次 DC/SP/noise 成功；后者的 47 点/9 指标从原始 PSFASCII 独立重提取且 11 文件清单通过。九点 HB 扫描现已与同一候选的实际网表、ADE 模型伴随文件及 10 GHz 小信号 SP 逐点配对，派生报告可再次从原始归档重建；源模板哈希不同，不误称相同模板。入口强制宿主可用物理内存不低于 2.66 GiB。该后端仍不解决 MOS CDF/几何问题；`spec_pass=null`、`not_lna_result=true` 固定不变。下一步先验证授权工艺参数传播与可实现匹配，再补合格 LNA 压缩点和 fullchain；长时/高负载另验。候选输入只能改变白名单许可的数值，禁止任意 shell/netlist 拼接。每次候选使用独立 results/runs/<spec>/<seed>/<candidate>/<run_id>/，保存参数快照、日志、原始结果、标准化 CSV、metrics.json、evidence_manifest.json 和失败原因；商业 PDK 网表仅存 Git 忽略目录。复用 RemoteRunner、控制超时/许可错误分类并避免远端目录碰撞。只有真实实测并从原始数据重提取的结果才能被评估，诊断后端不得冒充 fullchain 通过。

验收：同一候选重复运行结果来源清晰；一个成功候选和一个故意失败候选均可归档；dry_run 不能通过规格。
```

### 阶段 06：MVP 扫参与有源 lookup

```text
实施阶段 06。先为单级 LNA 建一个小预算参数扫描：配置 W/L/偏置/Ls/Lg/C、限制和单位，生成候选，调用真实 fullchain backend，按已验证 cost 排序，保存全部失败记录。然后用授权 PDK 或明确标为教学模型的器件表征网表，扫描 W/VGS/电流，保存 Id、gm、gds、寄生电容与可测阻抗，形成来源、工艺、温度、模型版本齐全的 lookup CSV。实现 active_sizing 查表、插值或最近邻与越界拒绝，不能用跨 PDK lookup。

验收：小规模真实扫参至少有多个不同参数的运行记录；每个 lookup 行可追溯到仿真；无 lookup 时返回 blocked/incomplete，不给虚拟有源参数。当前已有元数据/单位边界与空表拒绝，也有公开 MOS1 **固定 L 的四偏置/三宽度直接 Spectre 教学表征 CSV**（见 docs/30_stage06_lookup_contract.md、docs/37_teaching_multi_width_lookup.md）；它没有三级 stage、多 L/角落或授权 PDK，不是论文 lookup，`metadata_matched_unverified` 不能算器件已验证。
```

### 阶段 07：Stage 2 阻抗匹配

```text
继续阶段 07；先读 docs/35_teaching_input_matching_grid.md 和 docs/40_stage07_teaching_random_baseline.md。公开 MOS1 的规则网格与 seed=17 四点随机基线已逐点 Spectre 实测并独立审计，但均不达自定 -20 dB S11，采样 K 贴近 1；不要重跑相同候选或将它们当作论文 Stage 2。按论文 Table I/II 和已核对公式 (1) 实现面向合格 LNA 的 impedance_matching：读取有源级参数和 NF headroom；在合法 k、L、R、C、Ls 范围内提出候选；生成匹配网络并调用真实 Cadence S 参数/噪声 testbench；计算 band/中心点规则下的 NF 与 S11 violation；记录每次试验与 PSO/随机初始化种子。教学随机基线现只验证受控提案→Spectre→原始数据重算的局部方法，后续 PSO 与随机比较必须使用相同候选域、规格和仿真预算；器件值通过正值、工艺范围与物理可实现性检查。

验收：至少一个候选由仿真得分而非从 active_params 中抄入分数；输出最优候选与完整失败历史；缺失噪声数据时不能标记 matching 成功。
```

### 阶段 08：Stage 3 频带规划与 MCR

```text
实施阶段 08 剩余部分。先读 docs/28_mcr_equation3_model.md 和 docs/52_stage08_passive_quality_gate.md；英文 TeX 式 (3) 的复数模型和本项目选择的对称并联 RLC/k 映射已离线测试，后者在 30 GHz 理想被动 Spectre AC 的 41 点逐频校准和零耦合对照已实跑。论文 `Z21` 子表达式在该理想对称映射下逐点相符。印刷 `Y11` 分母末项有量纲疑点；仅对本项目理想对称网络增加一个 `s` 的独立候选式与旧 41 点 Spectre 原始 AC 一致，但不能声称论文已正式勘误或工艺物理网络已校准。公开 RLC 的一端口 Q/SRF 算法已用 Spectre 和解析式校准；标准型默认 PDK 螺旋、直接 `w=7u` 属性变体以及另一种对称型默认螺旋的独立 SP 均成功，8–12 GHz 最小 Q 分别约 10.524/10.515/10.714，均未过本项目教学 Q≥15 门槛。5 条模型警告未解释；前两者仅验证网表属性敏感性，第三者是不同器件而非单因素优化。CDF 回调、PCell 合法几何、耦合和 EM/PEX 都未验证。原式某些参数给出负的并联 R/C，不能直接生成为被动元件。下一步在授权环境用新用户库 cell 证明 CDF/PCell 合法参数变化、版图与网表/S11 一致，再做耦合/角落/物理匹配；不原样重试先前失败的无图形写入。复核论文 Fig. 4 的源/负载参考平面和线圈极性，明确 `Y11` 作者原意，建立更接近论文的可实现网络。基于论文公式 (2) 实现 gain/ripple 的 band planning。不要把理想被动 AC 或 PDK 一端口曲线命名为 Fig.7 LNA 结果。

补充授权 RF 默认器件输入匹配约束：`docs/71_stage09_rf_input_match_estimate.md` 已从两份独立、可重审的 Cadence 源档推导输入阻抗及单个额外理想串联 L 的代数极限。该档没有新候选仿真，不能把预测 S11 当实测。后续必须实跑含实部变换/多频峰值的受限网络，并用合法 PDK Q/SRF/几何、损耗与耦合数据筛选，不要只扫描现有 LG 或将默认螺旋串接倍数视为版图方案。

进一步一端口敏感性见 `docs/74_stage08_spiral_turns_sensitivity.md`：从同一默认授权 PDK 螺旋 OA 网表副本，仅把 `nr=3` 改为 4/5，分别真实运行 591 点 Spectre SP。10 GHz Leff 约 0.638→1.274→2.398 nH，但带内最低 Q 约 10.524→8.219→4.518，观测 SRF 下降；两份新档原始数据与派生来源已审计。它们未使用 PDK CDF/PCell 或 DRC，不能称合法几何扫描，也不支持继续凭理想 5.602 nH 目标盲目加匝。下一步应先取得工艺允许的几何/适用频段与实际 Q/SRF、耦合门禁，再重做有损匹配网络。

螺旋 PCell 的后续物理门禁见 `docs/75_stage08_spiral_pcell_gds_gate.md`：默认和 `nr=4` 的**新用户 layout cell**已低层保存，独立只读重开证明参数与核心几何响应，OA 字节未变；不等于 CDF/合法几何。显式技术库/layer map 的两份非空 GDS 均有两条空 via 结构 `XSTRM-399` 警告，虽然 OA 自身存在部分空 master 引用，仍不能证明 GDS 完整。原始跨档审计和负例测试通过；`drc_ready=false`。下一步需授权版图/工艺负责人澄清空 via 与官方映射，再得到可解释的 DRC 输入，不可用作论文物理 MCR。

上述两份**未通过输入资格门禁的 GDS**已经各做一次诊断性 Calibre DRC，见 `docs/76_stage08_spiral_drc_diagnostic.md`：同一授权源规则、每份 2319 个 rulecheck，默认 83 组/83 结果、`nr=4` 为 85 组/85 结果，报告还有运行警告。原始 GDS/脚本/报告/规则源哈希经跨档只读审计；结论始终是 `drc_input_qualified=false`、`drc_pass=false`、`physical_qualification=false`。这不是“已完成 DRC 门禁”；下一步仍是工艺负责人核查空 via、官方映射、参数合法性和违规性质，再用合格输入重新导出、复验，不能自行豁免。

验收：模型与 Spectre 对同一组网络参数的趋势可比较，差异量化；Stage 3 最优选择有仿真证据；MCR 无法实作时写替代网络及复现等级。
```

### 阶段 09：三阶段 LNA 与 fullchain 工具

```text
实施阶段 09。在授权工艺允许时，按论文的单端 cascode 首级、差分共源后级、中和电容、源退化及 MCR/等效网络建立三阶段宽带 LNA。逐级先验证 DC、稳定性和小信号增益，再做接口匹配、全链 S 参数、noise、功耗和压缩点。严格记录单端/差分端口定义、1787 ohm || 62 fF 负载是否实际实现、仿真温度与参考平面。若工艺或模型范围不支持 50 GHz，不得外推到该频段。

授权 RF 默认器件三级的**派生网表**已按源 S11 在 10 GHz 合成并实测一次理想两元件输入 L-match，见 `docs/72_stage09_rf_ideal_lmatch_probe.md`。原始 Cadence 161 点与网络解析预测逐频核对，但 8–12 GHz 最差输入匹配、增益、NF、纹波和输出仍不合格，也没有新 OA cell/物理无源。不得用中心 S11 的数值尖峰代替全带门禁；下一步需实际仿真多频匹配并逐步纳入有损、合法 PDK 器件，再考虑同候选 HB/fullchain。

全带理想四元件输入梯形网络的固定种子 16,384 次搜索及**唯一候选**真实 Spectre 161 点验证见 `docs/73_stage09_rf_ideal_ladder_search_and_probe.md`。解析复数 S11 与 Spectre 全频最大差约 `7.59e-8`，最差 S11 提升至约 -6.115 dB，但最差 S21≈-25.796 dB、NF≈17.500 dB，仍不合格。理想 5.602 nH 电感和 10 fF 边界电容未经合法 PDK Q/SRF/几何或耦合验证；不要把无损网络搜索继续当成物理候选优化。下一步先建立授权器件实际无源约束及模型警告/DRC 门禁，再用有损网络、同候选 OA/fullchain/HB 验收。

上述理想网络候选已另跑六点真实 10 GHz/七谐波 HB，见 `docs/89_stage09_rf_ladder_hb_diagnostic.md`；六点原始档与候选 161 点 SP/noise/DC 逐点绑定，在 -21/-20 dBm 夹住诊断级 1 dB 压缩。其同候选 S1 频带聚合见 `docs/90_stage09_rf_ladder_same_candidate_fullchain.md`，最差 S11/S21/NF 均失败，报告固定 `unverified_score`。与无梯形网络的 `docs/88_stage09_rf_diagnostic_fullchain.md` 严格区分，不能交叉拼指标或以单频压缩达限豁免匹配、增益、噪声和物理门禁。

公开 MOS1 的三级候选一步反馈见 `docs/104_stage09_teaching_three_stage_candidate_feedback.md`：两次新 Spectre DC/SP/noise 都与参数、规格、原始清单绑定，输出副边 2.0→4.085532 nH 的 9–11 GHz 最差 S21 从 -1.210 提至 1.677 dB、S22 从 -0.948 改至 -2.072 dB，但离合格 LNA 甚远且无同候选 HB/IP1dB。只把该结果用作受限反馈协议和教学趋势，不填论文数值表；远端派发不确定时保留 planned/uncertain，不重发。

后续**新** planned agent 第二轮候选已补 12 点同参数真实 Spectre HB 与原始 SP/noise 逐频同电路审计，见 `docs/107_stage09_teaching_agent_same_candidate_hb.md`。诊断级 10 GHz IP1dB≈-11.820 dBm，S1 带内最差增益≈1.677 dB、NF≈5.664 dB、纹波≈8.452 dB 仍失败，且理想无源/公开 MOS1 无物理资格；它不能代替授权 PDK 合格 `fullchain_eval` 或论文 Table IV/V。旧 `docs/104` 两个原始候选档自身仍无 HB，不能倒填。

新增授权 RF 默认器件的**单点源端接验证**见 `docs/78_stage09_rf_noise_source_termination.md`：从原 50 Ω Cadence SP/noise 的 `Fmin/Gopt/Bopt/RN` 与复数 S 参数预测改为 100 Ω 输入端接后的 161 点 NF/传输增益，另起真实 Spectre DC/SP/noise 验证的最大绝对差约 `4.62e-14/1.44e-12 dB`。最差 NF≈22.970 dB、S21≈-31.315 dB 仍失败；这只校准了噪声/源端接工具公式，不代表实际 50→100 Ω 无源网络可制造、模型警告已消除或 LNA 合格。后续需结合合法 PDK 有损器件约束，不能只追理想 `Γopt`。

将 active_sizing -> impedance_matching -> band_planning -> fullchain_eval 接成真实闭环。验收：四工具输出契约统一，至少一个 candidate 完整跑通并生成可审计的真实指标；被替代的论文结构逐项标注。
```

### 阶段 10：确定性多智能体

新增三级教学电路的确定性两轮 planned Manager/Searcher/Refiner 见 `docs/106_stage10_three_stage_planned_agent.md`：正常双运行 trace 绑定 journal/规格/候选/远端身份；另有**两次独立新实验**分别在首轮、第二轮真实 Spectre 返回 0 后受控丢回复，先 pending，再用原远端完整结果 v4 恢复、同 run ID 对账，不重派原候选。首轮恢复后才派发新的第二轮，第二轮恢复只接管该轮。第二轮候选后续同参数 HB 诊断见 `docs/107_stage09_teaching_agent_same_candidate_hb.md`。它不是在线 LLM、合格 LNA、物理 SSH 断线或论文数值复现。下一步优先解决远端不完整作业隔离、授权 PDK 物理无源/CDF/DRC 和真正 fullchain；不能用该教学闭环填论文表格。

第二轮 Refine 已持久化的三级教学 agent 只读收尾见 `docs/108_stage10_teaching_agent_terminal_recovery.md`；首轮 Refine 后、第二轮计划前的受限续跑见 `docs/109_stage10_teaching_agent_pre_second_resume.md`。这些不处理远端缺档；单候选共源诊断的缺档隔离和远端决定协议另见 `docs/113_stage10_incomplete_remote_quarantine.md`、`docs/114_stage10_remote_quarantine_fence.md`，尚无真实远端在线验收。

续接边界：`docs/95_stage10_uncertain_remote_dispatch.md` 与 `docs/96_stage10_terminal_failure_recovery.md` 分别约束不确定派发和有可信非零终结汇总的失败档。运行中实际 SSH 控制连接断开已由 `docs/100_stage10_live_ssh_disconnect_incomplete.md` 观察到，但该档缺 SP/noise 和终结汇总，仍 pending；静止并不等于失败。`docs/113_stage10_incomplete_remote_quarantine.md`、`docs/114_stage10_remote_quarantine_fence.md` 的隔离协议只在远端身份、双次哈希、隔离下载和本地来源核对后，先尝试远端不可覆盖决定，再复核原始文件并发布本地侧车；保持原 run ID 不可重派，预算结果未知。远端决定只围住隔离决策，非通用跨主机派发锁；在线旧档、真实两主机与端点认证仍缺，不能升级为合格 LNA agent 后端。

新增 `docs/98_stage10_real_spectre_lost_reply_probe.md`：新 S1 单候选已由真实 Spectre 完成，实验 runner **只在远端返回 0 后**向控制端注入一次 255；agent 因此留下 pending，经两次远端文件哈希观察、原始下载/重提取和 journal 对账后关闭，未重发仿真。它比历史已完成档模拟恢复更接近真实派发，但不是 SSH 物理断线或运行中作业，也不是合格 LNA。后续不要重做这一档来冒充真实 in-flight 门禁。

再新增 `docs/99_stage10_live_inflight_observation.md`：另一新 OA 共源诊断的独立 SSH `/proc` 原始响应在同一 run 内读到 `active=1`，当时日志和 SP/noise 尚未出现；完成后一次受控丢回复保留 pending，随后静止哈希/原始下载/对账均通过。该证据关闭“从未观察真实在途进程”的缺口，但没有模拟真实 SSH 断线或跨进程并发，Stage 10 仍 `partial`；绝不据此自动重发。

`docs/100_stage10_live_ssh_disconnect_incomplete.md` 的真实旧档观察到 active=1 后终止控制 SSH，随后静止但缺 SP/noise、无终结汇总；原 journal/run ID/staging 保留。2026-09-29 SSH 255 时没有新鲜远端观察，`safe_to_dispatch=false`，不得将模拟隔离协议的通过写成该档已隔离。恢复连接后先只读复核，再验收授权端点与远端 `ln` 原子语义；只有满足 `docs/114_stage10_remote_quarantine_fence.md` 的窄条件和显式写入授权，才可尝试旧档隔离；绝不重派原 run。

```text
继续阶段 10；先读 docs/26_deterministic_manager_mvp.md 和 docs/59_stage10_pending_archive_reconciliation.md。Manager 已有搜索/评估预算、候选 ID 去重和单 pending 槽；执行器在真实 OA 共源诊断后端中完成 Search -> Evaluate -> Refine -> Stop，保存去敏 trace、逐事件 journal、候选参数/规格快照和清单绑定。新 planned 模式**先持久化唯一 run ID 再调用 evaluator**，返回错误目录会失败；旧一参数 evaluator/旧 journal 保持只读兼容。操作系统锁内的 `resume_manager_after_search` 只允许零评估中断回合；另一个**仅限 RD/VBIAS 共源诊断**的 `reconcile_pending_diagnostic` 可对新格式、单次 planned pending 的已完成归档做 OA 源网表/伴随文件/PSFASCII/CSV/清单原始重审，随后只接收该档案，不重发 Spectre。RD=190 Ω 的一次真实 Spectre 归档后故意中断并对账通过，`Refiner=needs_evaluation`、`spec_pass=null`；重复对账拒绝。精炼事件已写但终态 trace 未落盘时，另用 `finalize_diagnostic_trace` 重新审计同一档案、核对 Refiner 状态再收尾，真实档案只读重审通过；它不是新仿真样本。上述恢复都不覆盖旧 pending 或远端仿真仍在运行的情形。空队列、超时和工具错误有分类结局；任何未经合格 LNA fullchain 原始数据核验的成功声明不得 accepted。四工具 JSON 白名单/预算/候选上下文注册表已接入默认 Searcher 的 active_sizing，其他三个工具缺实测后端时只报 unavailable。下一步补跨机器/远端在途核验、失败参数变异和优先级，以及 Stage 2/3 与真实 LNA fullchain evaluator；Searcher 只提交资源分配与工具参数，诊断结果不能进入论文表格。

新增 `docs/80_stage10_pending_remote_readonly_probe.md`：planned pending 的只读 SSH 探针已经能区分远端目录、原始文件和可见 Spectre 进程；在历史已完成目录上只验证了静止情形，所有返回均禁止自动重发。后续必须在真实在途/中断情形下验证进程可见性、下载/审计恢复和跨主机事务，再谈安全续跑；不能把“未见进程”当作新仿真许可。

新 planned 诊断回合的派发前远端配置快照绑定见 `docs/81_stage10_remote_identity_binding.md`：同一配置对象传给 journal 和 Spectre 后端，探针在 SSH 前对比原快照；旧未绑定 trace 只读兼容但不准用新探针定位。已有一轮新真实 Spectre 诊断原始档及 trace 重审，仍不是 LNA。下一步是实际在途/断线时的身份与进程复核、远端静止结果的受控下载/原始审计，以及不重复派发的恢复事务。

远端静止文件的双次哈希只读门禁见 `docs/82_stage10_remote_artifact_stability.md`。在历史已完成真实档上，六个关键文件两次哈希稳定且与本地原档一致，但该观察仍 `stable_unverified`、禁止自动接收。远端缺控制端 stdout/stderr，后续恢复器必须有明确的缺失日志来源契约、传输前后远端哈希和本地下载哈希，以及原始 PSFASCII 审计；不能填造空日志或只靠目录静止就调用 `reconcile_pending_diagnostic`。

上述恢复器现已实现并在**合成 pending、已完成远端源**上实际 SSH 下载、原始 PSFASCII 重审和接管，见 `docs/83_stage10_remote_quiescent_recovery.md`。这不是实际断线或在途故障测试；下一步做受控真实中断/进程在途验证、半成品事务的幂等续接，以及主机端点认证。所有失败路径保持不重发 Spectre，也不可把此诊断协议用于 LNA fullchain。

更新：已将恢复文件的发布移到 staging 原始审计之后，完整文件逐个不覆盖发布、清单最后发布；两种发布位置中断后的续接和清单已存在时直接对账通过离线故障注入，第二次已完成远端目录的 SSH 回收演练亦通过。仍缺真实 in-flight/断线、跨主机锁、端点身份和任意异常条件的事务性证明；下一步不要重复现有合成演练来冒充这些门槛。

验收：Search -> Evaluate -> Refine -> Stop 完整 trace 可读；超时、空队列、工具失败、dry_run 都有确定结局；不能把诊断或占位候选 accepted 为真实 pass。当前 `inspect_journal` 能检测事件顺序、预算和悬而未决的候选，但所有审计结局均禁止自动续跑；只有候选参数、evaluator 运行目录和原始仿真证据可事务性重建后，才设计续跑路径。
```

### 阶段 11：LLM 策略、KB/EB 和自进化

```text
实施阶段 11。先读 docs/36_llm_searcher_proposal_contract.md。确定性策略仍为 fallback；已有可注入 `ModelTransport` 的 Searcher 单工具 JSON 提案、Refiner 的受限失败阶段动作、Manager 的既有队列优先级和可选 OpenAI Responses 传输，只有假模型/假客户端测试，没有在线调用或真实 LNA。不得重写已通过的解析/范围门禁。模型只接收在实验室授权出境范围内的脱敏规格/候选摘要/指标/经验，不接收私有 PDK 路径或原始 netlist。mock LLM 继续覆盖正常 JSON、格式错误、越界参数、重复动作、超时与拒绝。传输已有内存计量、可选私有意图/结果记录和显式价格快照离线估算；真实模型仅在已有用户配置的凭据、数据出境审批与费用预算内接入，并须将调用与候选/run 双向对账、冻结费用来源和版本；未配置时明确标记未运行。

新增模型版 Refiner 的接口、输入边界和回退见 `docs/79_stage11_llm_refiner_contract.md`：可注入 Manager；只对校验后的失败约束提供受限阶段返工建议，实际诊断档、伪成功声明和无效模型响应不能绕过确定性门禁。它尚未生成新候选，真实 LNA 原始全链 observation、模型在线成本/授权、完整 LLM Manager Search/Refine/Stop 调度和成功 KB/EB 仍需实施，不得把 mock 报告当成实测。

目前首个真实失败事实 KB 和可选 Searcher 检索见 `docs/91_stage11_evidence_gated_failure_kb.md`。这是 KB 的**诊断失败子集**，不是成功候选复用或 EB；模型只接收受限摘要，不接收 PDK 路径、网表和自由文本。每次检索重审原始档，当前仅 S1 一条事实；不能据此声称完整论文 RAG/self-evolution 或 with/without EB 比较已做。

模型 Manager 优先级见 `docs/92_stage11_llm_manager_priority_contract.md`；可选传输的计量、离线估价与意图/结果证据见 `docs/110_stage11_model_usage_accounting.md`、`docs/111_stage11_model_call_evidence.md`。下一步仍需在合格 LNA 原始全链观测与可用模型授权下，逐步扩展 Search/Refine 选择、返工候选生成、ReAct 记录、候选绑定计量与公平消融；当前只验证假模型的受限候选排序及其 journal 恢复，不填论文 Table VI。

KB 存储可追溯事实，EB 存储由多次验证支持的经验；实现相似规格检索、来源引用、置信度与过期策略，失败经验不得未经验证变为正向建议。做 with/without EB 小预算对比。验收：mock 全通，真实模型如可用至少完成一个受控候选回合，决策不能绕过仿真与校验。
```

### 阶段 12：baseline、公平比较与消融

续接证据：五 seed、每法四点评估的教学 random/PSO/SA/GA/BO 已完成 100 个真实 Spectre 点和逐层只读审计，详见 `docs/93_stage12_teaching_bo_five_method_multiseed.md`。BO 使用隔离的 `scikit-optimize` GP/EI，并非论文的 `scikit-opt`；此前“没有 BO/没有 scikit-optimize”的陈述只描述当时状态。下一步仍是**合格授权 PDK LNA fullchain** 上的方法公平比较及 multi-agent 消融，不能用教学 MOS1 结果代填论文表图。

```text
实施阶段 12。先读 docs/60_stage12_teaching_pso_equal_budget.md 与 docs/67_stage12_teaching_multiseed_pilot.md：公开 MOS1 输入匹配的五 seed、各法四次预算 random 与本项目教学 PSO 均已真实 Spectre 实跑，并由跨 seed 汇总器逐层重审两法搜索轨迹及原始点。PSO 最佳 cost 较低 1 seed、random 较低 2 seed、打平 2 seed，不能据此主张优劣。当前没有 `scikit-opt`，此 PSO 不是论文实现；非合格 LNA 不形成论文 sample efficiency 或 pass@1。下一步在真实授权 PDK 合格 LNA 设计域实现 random、GA、BO、PSO、SA 及工具增强版本中依赖可支持的算法。所有方法使用相同 spec、候选空间、seed、仿真后端、预算和终止规则；区分模拟调用数、真实 Spectre CPU/墙钟时间和 LLM 时间。完成 full multi-agent、single-agent、without Refiner、without ReAct、with/without EB、tool-only 的消融；某模式无法真实运行时只输出 unavailable，不补零或编造成功率。

新增教学 SA 的五 seed、每 seed 四次**新** Spectre 实测及与旧 random/PSO 40 点的同预算配对见 `docs/77_stage12_teaching_sa_three_method_pilot.md`。三方法 60 点汇总和 PNG 均可从原始档只读重审；首点按 seed 与 random 相同。SA 是本项目教学实现，不是论文/`scikit-opt` 算法，也没有统计显著性或时间效率结论。Stage 12 的真正授权 PDK 合格 LNA GA/BO/PSO/SA 及多智能体消融仍未完成。

验收：同一小型 spec 至少两个可执行方法的运行数据可比较；结果带算法版本与配置快照；pass@1 分母、超时与失败处理定义明确。
```

### 阶段 13：10 specs、5 seeds 与图表

```text
实施阶段 13。先审核资源与授权工艺适用范围，再按 S1/S2/S4/S3/S5/S6/S7/S8/S9/S10 的难度递进执行。每个 spec 先一个 seed 和小预算；确认收敛与错误分类后扩展至五个 seed。每次运行完整记录频带、工艺、模型、仿真版本、方法、seed、候选数、search/refine 次数、token、耗时和 pass/fail。未运行的 spec 保持 unavailable，不能出现在成功率分母里冒充失败或成功。

Table III 的 `results/tables/table_iii_specs.csv` 已由 `py -m orfadc.experiments.export_specs` 从论文规格 YAML 生成；它只有输入规格，绝非实测结果。Stage 12 另有五 seed 公开 MOS1 **教学诊断**样本效率 PNG，经源档重审与重绘审计，见 `docs/67_stage12_teaching_multiseed_pilot.md`；它不是 Fig. 10-like LNA 曲线。从真实合格 LNA 结果生成 table_iv_like.csv、table_v_like.csv、table_vi_like.csv 和 fig7-11_like PNG。图表注释标明数据来源、工艺、样本量和缺测项；Fig.7-like 仅用本工程实际仿真曲线。验收：结果表中每个数据点能追溯到 run_id 和原始结果；有数据才画曲线，空数据只产生 schema/说明。
```

### 阶段 14：版图后仿与最终报告

```text
实施阶段 14。仅在前级电路与授权环境已跑通时推进 layout、DRC/LVS、PEX 和后仿真，并对比 schematic/post-layout 的 S 参数、NF、功耗与压缩点。版图工具（包括 ALIGN）的使用要符合 PDK/许可证；没有实际 PEX 就标记未完成。整理课程设计/科研训练报告：论文依据、本项目实现、从 OTA 到 LNA 的迁移、每个仿真条件、对照实验、已验证结果、偏差和不可严格复现边界。更新 README、文档索引和最小复现命令。

验收：报告中每个实测数值均有可定位产物；真实、教学、dry-run、mock 图表分开标明；最终状态表清楚列出已完成、近似完成、外部阻塞和未完成。
```

## 3. 续接与审查提示词

### 新任务续接

```text
继续 F:\Open-RFAmpDesigner-Cadence 的自动实施。先读 README.md、docs/00_index.md、docs/15_autonomous_completion_prompts.md、docs/16_implementation_status.md、docs/20_stage03_active_smoke.md 至 docs/32_stage04_hb_diagnostic.md，并检查 git status 和本机原始运行证据。
阶段 00 已收尾，A09 只在短时轻负载范围通过，阶段 02 被动 noise 已实测。阶段 03 私有 OA 共源 v1/v2 的 DC/SP-noise 与 S12 已交叉核验，但不是合格 LNA；理想 LS=300 pH 在 8-12 GHz 采样 K>1，在 0.1-20 GHz K<1 且匹配/ripple 失败。授权 RF MOS 已完成低层 PCell 单参数几何响应和两个非空 GDS 导出，但两次 Calibre DRC 都有违规，不能称物理验收；见 docs/61 至 docs/63。无图形参数写入诊断未保存有效 OA，停止原样重试，由授权环境检查 PDK 初始化、交互式参数修改及同候选网表，并请工艺负责人逐条审阅 DRC 违规。
阶段 05 已有运行文件哈希清单、独占 run_id 目录和固定 R/L/C 的被动诊断候选入口；一次 Spectre 被动实测通过，47 点原始 S2P/noise 可重提取；一次受控 SSH 权限负例在上传前失败并归档，两者 `spec_pass=null`。OA RD/VBIAS 白名单直接 Spectre 后端在 4 GiB VM 上归档一次缺伴随文件失败，修复后完成 DC/SP/noise、47 点/9 指标独立重提取与清单。阶段 04 的单管共源 HB 7 谐波/9 点实测给出诊断级 IP1dB≈-8.99 dBm、OP1dB≈-7.75 dBm；只读审计可重算 7/9 点归档；该电路 S11/稳定性失败，不是合格 LNA。4 GiB VM 的 3 轮 SSH/Tools/OCEAN 轻负载门禁通过，长时/高负载未验。阶段 10 有确定性 agent→真实 OA 诊断回合；新 journal 的候选清单摘要可跨目录验证，Refiner 仍 needs_evaluation。尚缺优先级、变异、可信恢复及真实 fullchain。阶段 08 式 (3) 理论模型有非被动等效点；本项目理想并联 RLC 的 `Z21` 子表达式与 41 点 Spectre AC 一致，印刷 `Y11` 末项量纲疑点已按独立候选式作只读 AC 对照，不能称论文 MCR 全部已校准。
下一步保持资源门禁；VM 当前为 4 GiB 并运行，实测前重新测宿主余量。优先用授权交互环境解决 CDF/PCell 参数传播，随后推进稳定匹配、**合格 LNA** 压缩点与 fullchain；并行推进 Manager 恢复/变异及论文 MCR 拓扑/参考平面校准。只有 CDF/PCell 门禁通过后，才用可实现无源网络做带内、带外和角落实测。许可证材料只作诊断，不修改许可文件。不要重做已通过的被动正例/权限负例或上述有源成功候选，不复用失败 cell，不覆盖未提交修改，不把共源/理想网络称作合格 LNA。若外部条件受阻，继续可独立完成的工作并更新状态。
```

### 阶段验收审查

```text
请按 docs/15_autonomous_completion_prompts.md 的当前阶段验收门槛审查实际仓库。逐条给出代码/日志/原始数据/测试证据，指出缺失项并直接修复可以在本任务内修复的问题。只在全部门槛满足时更新 docs/16_implementation_status.md 为 passed；否则标记 partial/blocked，并注明具体原因与下一条可执行命令。不得仅因为已有文件或文档就认定功能已实现。
```

### 故障恢复

```text
请诊断本阶段最近一次失败运行。先定位 run_id、完整命令、日志、仿真版本和输入参数；区分连接/许可、网表、收敛、分析类型、解析、指标、agent 逻辑。构造最小复现并只修改相关代码或配置。修复后重跑失败用例及相关测试，保留原失败产物和修复前后差异。涉及私有 PDK 时只在本地被忽略目录保存原始文件，公开文档只记录脱敏结论。
```

## 4. 对自动完成的现实定义

“自动完成”指代理持续实施所有已具备前置条件的任务，并以实测证据推进阶段；它不意味着无授权 PDK 也能生成真实工艺 LNA、无模型凭据也能完成真实 LLM 对比，或无版图也能声称 post-layout 结果。阶段表应准确报告最高完成层级，避免用一个总完成百分比掩盖关键实验缺口。
