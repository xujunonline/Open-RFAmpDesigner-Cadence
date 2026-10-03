# Stage 11: 受限模型 Manager 的候选优先级

## 已实现

`LLMManagerPolicy` 在确定性 Manager 已生成**至少两个**同 spec/seed 候选、且仍有评估预算时，向可注入的模型传入脱敏规格、预算与候选 ID/功率比例/状态。模型只能回答 `{"action":"EvaluateCandidate","candidate_id":"现有ID"}`。重复 JSON 键、额外字段、越权 ID、非评估动作、超长响应或调用异常均回退为 FIFO；模型既不能生成候选、改参数、派发仿真，也不能宣称 `spec_pass`。单候选时无需调用模型。默认 Manager 仍完全确定性；必须显式注入策略才启用此路径。

选择写入 `QueuePriority` journal 事件的 `candidate_id` 与 `source=model|fallback`；可选两阶段私有模型运行档启用时还写 `model_call_id`，不保存私有 prompt 或模型错误文本。`inspect_journal` 重放队列重排，要求下一事件就是所选候选的 `EvaluateCandidate`，并审计模型调用与该动作的角色/前缀/候选绑定，见 `docs/112_stage11_model_action_binding.md`；拒绝不在队列的 ID、虚假的 fallback、重复或未消费的优先级事件。若在记录选择之后、派发评估之前中断，`resume_manager_after_search` 从已审计 journal 顺序和候选快照恢复，不再询问模型；既有 planned run ID、锁和候选来源约束仍适用。旧 FIFO 归档与旧测试保持兼容。

定向测试用**假模型**覆盖第二候选优先、非法 JSON/动作/ID、超时脱敏回退、journal 篡改以及优先级事件后的中断恢复。该测试没有调用在线 LLM，也没有派发新的 Cadence 仿真。它验证了调度权限边界与持久化机制，不验证模型设计策略是否优于 FIFO。

## 未达到的论文能力

论文中的 RFAmpManager 还要在 Autonomous Search 与 Retrieve-and-Refine 间切换，依据候选质量安排 Searcher/Refiner、控制返工深度和停止条件。当前模型 Manager **只做已有队列排序**；Search/Stop 仍由确定性预算决定，Refiner 只给受限动作而不生成下一候选。可选传输已有假客户端验证的计量接口（`docs/110_stage11_model_usage_accounting.md`），但尚无合格 LNA fullchain backend、在线模型调用或实际模型 ID/token/延迟/费用证据，也无 with/without Manager 的等预算多 seed 消融。下一步须在可审计的真实 LNA 观测上逐步扩展可允许动作，并保持 journal 状态机和原始仿真证据门禁，不得用 mock 决策冒充论文 agent 成功率。
