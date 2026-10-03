# Stage 11: 模型调用与 Agent 动作绑定

## 已实现的边界

可选的 `ModelCallEvidence` 为每次请求先写私有 `model_calls/<call_id>.intent.json`，再写结果。`OpenAIResponsesTransport.last_call_id()` 保留本线程最近一次已落盘意图的 ID；Searcher、Refiner 在调用结束或异常时读取该 ID，Manager 优先级策略把 ID 连同决策返回。执行器与 Manager 把 ID 写入对应 journal 事件。使用不支持此接口的假传输或纯确定性 agent 时，不添加字段，旧 journal 仍可审计。

| 角色 | 调用后 journal 事件 | 绑定对象 | 异常边界 |
| --- | --- | --- | --- |
| Searcher | `SearchCandidates` 或 `SearchFailed` | 新候选 ID 列表、候选参数快照；失败时无候选 | 响应完成但 JSON 无效、传输异常及结果文件写入失败均保留调用 ID；前两类可读完成结果，最后一类只有未结意图 |
| Manager | `QueuePriority` | 既有队列中的候选 ID、`source=model|fallback`；随后必须是同候选 `EvaluateCandidate`，planned 模式还记录 run ID | 模型无效或异常回退 FIFO，未结意图仍不能自动再发同一请求 |
| Refiner | `RefineCandidate` | 已评价候选 ID、状态；有完整匹配的运行证据时还绑定 run ID 与清单 SHA-256 | 无效/失败请求只能给允许的确定性回退动作；运行证据不足时 run ID 保持 null，不能宣称完整仿真绑定 |

`inspect_journal(trace_dir)` 首先重放现有状态机、队列及候选快照，再核对每个 `model_call_id` 在私有运行档中的角色、调用前后 journal 前缀位置和完成分类。一个 ID 不得在同一动作序列重复使用；终态 journal 不允许遗留未被事件引用的该角色模型调用。`JournalAudit` 分别报告 `model_call_bindings`、`search_call_bindings`、`refiner_call_bindings` 和验证标志。调用结果落盘失败时审计只承认匹配的 pending 意图，费用与 usage 为未知，不将其视为成功计价。

私有档不保存 prompt、响应文本或异常正文。故此审计证明的是**本地调用意图/结果、角色、journal 动作与候选/已有运行证据的一致性**，不是模型确实产生了某段答复的密码学证明，更不是供应商收款或 Cadence 仿真合格证明。SHA-256 防止无意错配；掌握本地所有文件写权限者仍可重写完整档案。`QueuePriority` 的模型权限仍仅限已有候选排序；Searcher 仍只生成受限提案；Refiner 仍只选已验证失败约束允许的动作。它们尚不构成论文的完整自主搜索、检索精炼和自进化策略。

## 验证与后续

假 Responses 客户端的测试覆盖三个角色的正常决策、无效 JSON、传输异常、结果落盘异常及未被消费调用；错误 call ID 的 journal 篡改会被拒绝。Refiner 测试的“运行”是临时目录中的**明确标记 MOCK TEST FIXTURE ONLY 的合成失败规格证据**，仅用于绑定协议回归，绝不是新 Cadence 结果。无在线模型请求、新 Spectre 仿真、实际价格或 Table VI-like 成本数据。

下一门禁是授权后冻结价格版本/服务层级快照，明确数据出境与预算，再在合格 LNA 同候选 fullchain 可用时进行在线模型与确定性策略同规格、同 seed、同预算比较。任何未结意图、缺失 usage 或未验证 run ID 都应保留未知状态；不能自动重发请求，也不能填零成本。
