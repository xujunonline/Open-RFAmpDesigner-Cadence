# Stage 11: 模型调用意图与结果的私有运行档

## 实现

`ModelCallEvidence` 接收 `results/runs/` 下的 agent trace 目录和 `Manager`/`Searcher`/`Refiner` 角色。目录可先创建、再构造 agent；首次模型调用**必须等执行器写入 `RunStarted` journal 后**，否则意图拒绝写入且模型请求不发。可选 `OpenAIResponsesTransport(…, usage_evidence=evidence)` 在向 Responses 客户端发请求**之前**，独占创建并 `fsync` 一份 `<call_id>.intent.json`；响应成功、空输出、不完整或客户端异常时，再独占创建并 `fsync` `<call_id>.result.json`。两者只记录模型 ID、角色、trace ID、前后 agent journal SHA-256、时间戳、完成分类、本地耗时及服务端返回的 token 字段；不保存 prompt、响应正文、异常正文、密钥、网表或私有 PDK 路径。

意图写入失败时不发模型请求。进程在意图落盘后至结果落盘前崩溃，意图会保留；`audit_model_calls(trace_dir)` 报告 pending call ID，费用/用量仍未知。同一 trace 存在未结意图时，下一次 `begin` 在本机文件锁下拒绝新的模型请求；两线程竞态测试只允许一个意图落盘。不能通过重试来猜测前一次是否已计费。结果落盘失败时不能假装模型响应已被完整记账，传输调用会失败关闭。审计器只读检查文件名/严格字段、独占结果与意图哈希、模型 ID、token 一致性，以及调用前后 journal 哈希是否按顺序出现在当前 journal 的追加前缀中。最后的 journal 可以增加新的 agent 事件，但改写已有前缀将使审计失败。零调用或任一未结调用不能标作“计价计数齐全”。这只检查 JSON 行格式和前缀绑定，不替代 `inspect_journal` 的 agent 状态机审计或跨主机锁。

示意接线（**仅在模型服务、费用和数据出境都已获实验室授权时**）：

```python
from orfadc.agents.model_call_evidence import ModelCallEvidence, audit_model_calls
from orfadc.agents.openai_transport import OpenAIResponsesTransport

evidence = ModelCallEvidence(trace_dir, role="Searcher")
transport = OpenAIResponsesTransport.from_environment(
    model=approved_model_id, usage_evidence=evidence,
)
# 将 transport 注入 LLMSearcher；调用结束后：
report = audit_model_calls(trace_dir)
```

本阶段只用假 Responses 客户端验证调用前意图、正常/异常结果、未结意图、journal 改写和字段篡改拒绝；另用真实 `execute_manager` 控制流与假模型验证可在 `RunStarted` 之前构造模型 Manager，并在 `QueuePriority` 事件之前记录一次调用。后续已补三个角色调用 ID 与 journal 动作、候选及已有运行证据的本地绑定，见 `docs/112_stage11_model_action_binding.md`。**没有运行在线模型，也没有新 Cadence 仿真。** 意图是本地客户端记录，不是供应商已接收请求的证明；返回的用量是本地保存的 API 元数据，不是供应商账单。SHA-256 用于检测意外改动和来源错配，不是签名；有本机写权限者可同时改写整个本地证据集。仍没有价格快照归档或完整 Table VI-like 统计。

## 下一门禁

1. 三角色调用 ID 与动作、候选及可用 run ID 的本地绑定已实现；仍需在跨进程恢复和故障注入中检验整轮私有模型运行档，不把未结调用自动重发。
2. 将经授权的费率来源、版本、服务层级和快照冻结进私有运行档；对用量缺失、缓存写入类别不明和失败调用不填 0 成本。
3. 在合格 LNA fullchain 与真实模型授权可用后，以同规格、种子、预算比较模型/仿真时间和费用；教学诊断与假客户端数据不得填 Table VI。
