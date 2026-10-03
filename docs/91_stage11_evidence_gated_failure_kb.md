# Stage 11: 原始证据门禁下的失败事实 KB

## 已实现的范围

`src/orfadc/agents/memory.py` 新增 `VerifiedFailureKB`。当前唯一受支持的来源是 `docs/90_stage09_rf_ladder_same_candidate_fullchain.md` 的**同候选、只读审计通过、但规格失败**报告。入库前和每次读取时，先重新执行报告审计；它还会重审六个 HB 点和梯形候选的原始 SP/noise/DC、来源清单与网表对应关系。然后从已审计报告生成固定键集合的 JSONL 事实，保存到 Git 忽略的 `results/memory/kb.jsonl`。首个真实条目来自私有报告 `20260927T111305Z_1748e1d0`，`kind=diagnostic_failure`、`eligible_for_seed=false`、`eligible_for_experience=false`。

记录只含规格、S11/S21/S22/NF/纹波/IP1dB/电流的诊断数值、五项超限量、run ID 和证据清单摘要；没有商业模型路径、网表、OA 库名或任意自由文本。OS 写锁、重复 ID 拒绝、行长度和总量上限、重复 JSON 键拒绝、符号链接拒绝与写后 fsync 限制了误写和并发冲突。外部持有写权限的人仍可能同时修改源档与 KB，因此这**不是不可篡改数据库**；它依赖现有原始归档审计和本机文件保护。

`retrieve_failure_context` 仅返回中心频率相差不超过约 10%、相对带宽绝对差不超过 0.1 的已审计失败摘要，按相似度排序。摘要只写失败约束、来源 ID 和两个禁止复用标志，不传入原始指标、路径或器件参数。`LLMSearcher` 可选择注入 KB；此时模型输入增加 `diagnostic_failure_context`，不注入时维持原契约。模型仍只能提出一个受限 `active_sizing` 功率分配请求，工具注册表决定是否有已验证器件 lookup；KB 不赋予模型改写指标、网表或宣称通过的权限。

## 仍未实现

当前只有一个**不合格且理想无源**的真实事实，不是成功候选；不能用它作为跨工艺/跨频段的 sizing 起点。没有至少两份同适用范围、独立且合格的 LNA 事实支持，故 `eb.jsonl` 不填任何“经验规律”，也不把示例经验当成实测。相似度只是检索筛选，不证明电路参数可迁移。没有真实在线 LLM 调用、token/延迟/费用记录、模型版 Manager 决策、完整 ReAct 轨迹或 with/without EB 消融。`JsonlMemory` 仍是旧的低层任意 JSONL 工具，不能代替这个原始证据门禁，也不能用于成功候选采纳。

下一步先取得合格 LNA 的同候选 fullchain 后端与原始审计，再扩充 KB 的成功事实类型和模型/工艺/频带作用域；EB 的每条规律需多个独立事实、适用条件、失效条件和人工或可重放规则验证。之后才能在相同预算与真实模型下比较有无 KB/EB 的多 seed agent 表现。
