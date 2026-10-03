# Stage 11: 模型调用计量与离线价格快照

## 已落地的边界

`OpenAIResponsesTransport.complete(...)` 仍返回文本；Searcher、Manager、Refiner 的工具权限、JSON 校验和确定性回退不变。`drain_usage_events()` 取出该传输实例自上次读取以来的计量事件。每次实际 `responses.create` 尝试产生一条：请求/响应模型 ID、完成/不完整/空输出/传输异常分类、本地单调时钟耗时，以及 API 实际返回的 input、cached input、cache-write input、output、reasoning output、total token 数。它不保存 prompt、响应正文、异常文本、密钥或网表。**默认**事件只在内存中，进程崩溃前未取出的事件会丢失；可选两阶段私有持久化见 `docs/111_stage11_model_call_evidence.md`。共享实例并发调用时，内存事件按完成顺序入队；需要 agent 角色归属时应给各角色单独实例，且不能把队列顺序误当成候选 ID 绑定。

字段不存在、类型不合法或计数相互矛盾时记为 `null`，绝不把未知当作零。传输异常可能已被远端计费，但本地拿不到 usage，必须保持 `unpriced`。SDK 响应含 usage 的字段定义见 [OpenAI 官方 Python Responses API 参考](https://developers.openai.com/api/reference/python/resources/responses/methods/create)；`store=False` 不等于零保留或数据出境授权，见 [OpenAI 官方数据控制说明](https://developers.openai.com/api/docs/guides/your-data)。

`ModelPriceSnapshot` 要求显式模型 ID、快照版本、HTTPS 来源及普通输入/缓存读取/缓存写入/输出的 USD/百万 token 十进制费率。`price_usage_event` 只在响应模型与快照一致、关键 token 完整且自洽时计算；缓存写入费率与普通输入费率不同时，还必须得到缓存写入计数，否则拒绝估算。价格不内置、不动态抓取；示例里的 `mock-model-1`/价格只用于单元测试，**不是实际供应商报价**。计算式为

```text
USD = ((input - cached - cache_write) * input_rate
       + cached * cached_rate + cache_write * cache_write_rate
       + output * output_rate) / 1_000_000
```

缓存写入是与普通输入互斥的计价类别，而非叠加收费，见 [OpenAI 官方 Prompt Caching 文档](https://developers.openai.com/api/docs/guides/prompt-caching)。模型价格还可能按服务层级、批量、音频/工具等另有规则，本简化计算器只适用于与快照四档价格语义一致的文本调用。它不包括 Cadence 许可、计算、人工或网络成本，不给出论文 Table VI 的 effective cost/latency。没有真实在线调用、费用审批或授权数据出境，当前不能生成有实测含义的 Table VI-like 数值。

## 下一门禁

1. 确认实验室对规格摘要、失败指标及模型服务的数据出境范围，设置用户自己的凭据和费用上限；本仓库不可自动代为授权。
2. 可选私有归档已能持久化意图/结果并绑定 role/trace/journal 前缀；三个角色的 call ID 已与各自 journal 动作、候选及可用 run ID 做本地绑定，见 `docs/112_stage11_model_action_binding.md`。下一步冻结价格快照并覆盖重启对账。失败、超时及未知 usage 均保留，不得重复计算或伪造丢失事件。
3. 获得合格 LNA 原始 fullchain 后，在同预算/同 seed 消融中再计算搜索、精炼、仿真与实际模型调用的有效时间/费用；没有数据的列保留不可用。

本阶段的测试只使用假 Responses 客户端和人为指定的测试价格，不调用在线 API。
