# 阶段 03：CDF 写入诊断与停止条件

2026-09-26 继续 `docs/23_stage03_stability_cdf_followup.md`。所有脚本、日志、报告和 OA 视图仅在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/` 或授权虚拟机中；本文不包含商业 PDK 文件、模型或许可证内容。

## 本轮实际执行

1. 重跑只读 `probe_mos_cdf_v1_v2.ocn`，新运行 `probe_mos_cdf_readonly_20260926_02/` 返回 0；新旧报告各 26 行且内容一致。它证明本次 PDK 初始化和只读 CDF/实例查询可完成，不证明写入 callback 正常。
2. 第一个单 MOS 写入诊断 `probe_mos_cdf_set_20260926_02/` 在脚本第 6 行因当前 OCEAN 工作目录未注册设计库而报错，**未执行到 `vfoSetParam`**。后续 X I/O 错误发生在交互进程未正常退出阶段，不能据此推断 callback 崩溃。失败输入和日志完整保留。
3. 新名称运行 `probe_mos_cdf_set_20260926_03/` 先将既有设计库路径注册到当前进程，成功进入全新单 MOS cell，并在日志中打印“setting CDF parameters”；此后没有保存/完成标记。OCEAN 非正常返回，部分报告为 0 字节，新 cell 的 `sch.oa` 为 0 字节，远端复查无残留 OCEAN/Xvfb 进程。**无法判定哪个参数或 callback 导致停止，也不能认为任何几何寄生属性已正确更新。** 不复用或删除两个失败诊断 cell。

宿主/来宾资源门禁通过后才启动上述逐次运行，且没有并行 Cadence 作业；不能把第二次失败简单归因为内存不足。每次运行均有独立名称、日志和 180 秒命令上限。此处停止重复无图形 `vfoSetParam` 试错。

## 工程含义与下一步

[Cadence 关于程序化 CDF 修改的讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/19224/how-to-use-skill-to-change-pcell-parameter-like-using-edit-instance-properties-to-change-parameter)指出，程序化修改实例属性与交互式属性表单的 callback 行为不能默认等同；[另一则 PDK 案例](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/65415/strange-parameter-setting-behaviour-in-a-specific-pdk)显示某些器件还依赖表单初始化过程。这些是通用风险提示，**不是**本工艺回调故障的诊断结论。

下一步需在授权环境由熟悉该 PDK 的人员检查其 CDF 初始化/回调约定，优先用交互式 Virtuoso 对一个**新**诊断 cell 做单参数更改、Check and Save、导出网表，并与原值对照。如果要继续无图形自动化，先有可复现的最小 callback 过程、明确的超时/失败退出，再检查 `W/Wfg`、`nf/fingers` 与结面积/周长等有效属性及最终网表；绝不自行编造几何公式。该门禁通过前，v1/v2/v3 只作为诊断证据，阶段 03 仍为 partial。

2026-09-26 后续只读 SSH 探测：来宾 SSH 可用，Xorg/GDM 进程存在，但当时没有 Virtuoso 进程，也没有已就绪的用户交互式 Virtuoso 图形会话。本次未尝试写 CDF、启动失败 cell 或重跑 `vfoSetParam`。这只说明**当时**不能验证交互式属性表单，不证明工艺 callback 本身故障；图形会话可用后仍按上段的新 cell/原值对照门禁操作。

同日新增一轮只读 OCEAN 探测：SSH 正常、宿主物理余量约 3.28 GiB、来宾没有 Virtuoso/OCEAN 进程或用户图形登录。脚本只读打开已成功的 v1/v2 schematic，返回码 0，报告和日志保存在忽略目录的 `probe_mos_pcell_mapping_20260926_01.*`。两个 MOS 实例均引用普通 `symbol` master，未暴露 `superMaster/parameters`；实例属性仍为两组不同的 `w/Wfg` 字符串。这说明通过**该 symbol 查询**无法检查实际 PCell 参数，也没有推翻此前导出网表几何传播的疑点。没有修改 OA、运行 callback 或得出 CDF 已修复的结论。[Cadence 关于表单回调与数据库属性区别的说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/36448/skill-command-to-create-the-cell-view/1348674)及[回调调用顺序的讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/37665/invoke-pcell-callback---simple-case-of-abinvokecdf-functions)仅指导后续受控诊断，不代表该 PDK 的已验证调用步骤。

独立于 Cadence 故障，`Refiner` 已开始强化接口：必须接收后端指标 envelope 和当前 spec/candidate 上下文，并在 Python 中重算 violation。这个改动防止仅凭 LLM 声称的 `pass` 或 violation 接受候选，但 JSON 自身不能证明真实仿真；后续 Manager 必须从受控 backend 的原始产物构造 observation，不能转发模型提交的指标。
