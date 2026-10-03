# Stage 11：模型提案接入的第一道门禁

本阶段新增 `src/orfadc/agents/llm_searcher.py`，把可替换的模型传输对象接到现有 Manager/Searcher 接口；另有可选 `src/orfadc/agents/openai_transport.py`。**当前只有假模型/假客户端单元测试，没有真实 API 调用记录，也没有由 LLM 产生的 Cadence 合格 LNA。** 原论文所用模型与本项目可选后端的区别见 `agent_system/`；这里描述已落地的代码。

## 一轮调用

1. Python 从已验证的 `Spec` 组装纯规格/seed 输入，读取 `agents/prompts/searcher.md` 作为系统指令，调用注入的 `ModelTransport.complete(...)`。传输对象由调用方提供。可选 OpenAI 传输从环境变量 `OPENAI_API_KEY` 初始化官方 SDK，模型 ID 必须显式传入；不把密钥写入仓库。
2. 模型只能返回一个严格 JSON 工具请求，形如 `{"tool":"active_sizing","arguments":{"power_ratio_list":[0.4,0.3,0.3],"total_current_ma":9.0}}`。响应最多 4096 UTF-8 字节；重复键、额外键、代码围栏、非有限数、比例不合计 1、超规格电流及其他工具均拒绝。
3. `AgentToolRegistry` 再次校验，并调用本地 `active_sizing`。当前无经验证的三级 PDK lookup，所以候选状态为 `needs_verified_active_lookup`，不含 `sim_result` 或 `spec_pass`。
4. 候选 ID 由 spec、seed、规范化提案哈希生成，相同提案会被 Manager 去重。哈希只记录提案，不证明来自真实模型；也不代替 Cadence 运行证据。

离线使用示意：

```python
from orfadc.agents.llm_searcher import LLMSearcher
from orfadc.agents.manager import Manager

class FakeModel:
    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        return '{"tool":"active_sizing","arguments":{"power_ratio_list":[0.4,0.3,0.3],"total_current_ma":9.0}}'

manager = Manager(LLMSearcher(FakeModel()), max_searches=1, max_evaluations=1)
# manager.search_candidates(spec, seed=0)  # spec 必须是已校验的 Spec
```

此适配器只覆盖 Searcher 的**候选提案**，不是完整多智能体系统。可选传输后续已有假客户端验证的计量、离线价格快照计算与私有意图/结果记录（`docs/110_stage11_model_usage_accounting.md`、`docs/111_stage11_model_call_evidence.md`），但仍需在线传输的授权环境验收、调用与候选/run 双向绑定及实际费用/延迟记录、经过原始数据重算的 fullchain observation、完整 Manager 搜索/精炼调度、KB/EB 检索和同预算消融。模型文本永远不能直接写入 `metrics.json`、设置 `spec_pass`、执行任意 shell/SKILL 或绕过证据清单。Stage 03/05 的 LNA 门禁未因本改动改变。

后续进展：Refiner 的**离线受限返工提案**已实现，见 `docs/79_stage11_llm_refiner_contract.md`；上句其余门禁仍未完成。

可选在线接线要求单独安装官方 `openai` Python SDK，再由调用方显式构造 `OpenAIResponsesTransport.from_environment(model="<已授权模型 ID>")`。传输层使用 Responses API 的 `instructions`/`input`、单请求超时、关闭 SDK 自动重试，并要求 `status=completed` 和非空 `output_text`；`store=False` 只控制 API 响应存储请求，不能代替实验室数据出境审批。[OpenAI 官方文本生成文档](https://developers.openai.com/api/docs/guides/text)说明了 Responses 的这些输入/文本输出字段。当前环境未安装 SDK、未做在线调用，绝不声称模型可用、费用已核实或真实 agent 复现已完成。
