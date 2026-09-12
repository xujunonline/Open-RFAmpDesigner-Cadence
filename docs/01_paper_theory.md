# 论文理论拆解

本文件是 `open_rfampdesigner_cadence_full_plan.md` 的精简入口，便于后续继续扩展。

RFAmpDesigner 的核心是把 RF amplifier sizing 拆为资源分配问题。原始设计向量包含有源尺寸、偏置、MCR 和匹配网络等约 30 个变量；工具中间件把 LLM 的任务限制为电流、增益、NF headroom 和线性度压力等低维决策。

论文公开可直接复现的内容：

- Table I 工具接口；
- Table II Stage 2/3 变量范围；
- Table III benchmark 规格；
- Stage 2 和 Stage 3 cost function；
- Manager/Searcher/Refiner 的角色定义；
- KB/EB 的记录思想；
- Table IV/V/VI 和 Fig. 7-11 的结构。

论文不可直接复现的内容：

- TSMC N65 PDK；
- PCells 和 post-layout netlist；
- 作者 OCEAN scripts；
- lookup table；
- prompts；
- KB/EB 原始内容；
- 最终候选参数。

