# Stage 11：模型版 Refiner 的受限返工决策

## 已实现的调用路径

`Manager(refiner=LLMRefiner(transport))` 可把模型版 Refiner 注入现有执行器；Searcher 仍可独立选确定性策略或 `LLMSearcher`。真实后端运行档进入 `Manager.record_result` 后，候选/spec/run ID 和证据清单先绑定，再由 `Refiner.refine_from_run` 读取结果。缺失或变更的证据、`spec_pass=true` 但未从原始全链数据重提取的成功声明，均停在 `needs_evaluation`，不调用模型。

对其余报告，Refiner 沿用原有规格、候选、频带、分析类型、参考平面和指标完整性校验，再由 `fullchain_violations` **重新计算** NF、S11、增益、IP1dB、功耗超限。模型只能看见 `Spec` 数值、候选 ID/seed/功率比例、这五个非负超限值和允许动作，不接收 `metrics.json` 原文、网表、模型路径、候选 `active_params` 或原始波形。当前使用严格单对象 JSON：

```json
{"action":"retry_stage2"}
```

动作只从实际正超限生成：NF/S11→`retry_stage2`，增益→`retry_stage3`，IP1dB→`retry_stage1_or_stage3`，功耗→`retry_stage1`。同时有多项超限时，模型可以在这些动作中选择一个。响应超过 1024 字节、重复/额外键、代码围栏、非有限数、未授权动作、拒绝或超时，均记录固定的回退说明并执行原确定性 Refiner。无超限或非完整 LNA 结果不调用模型；模型永远不能输出 `accepted`、设置 `spec_pass` 或写仿真指标。

```python
from orfadc.agents.llm_refiner import LLMRefiner
from orfadc.agents.manager import Manager

# transport 实现 ModelTransport.complete；必须由实验室在授权环境配置。
manager = Manager(refiner=LLMRefiner(transport), max_searches=1, max_evaluations=1)
```

## 验证与边界

`tests/test_llm_refiner.py` 仅使用假模型和显式标作 mock 的完整失败报告来测动作选择/Manager 注入；另用已有真实 Cadence 共源诊断档确认它**不会**进入 LNA Refiner。合成证据清单只验证程序接口，**不是原始 Spectre fullchain 审计**。没有真实模型 API、token/费用/延迟记录，也没有合格 LNA 的可供返工 observation。目前 Manager 记录返回的返工状态，但**不会自动重排或生成下一候选**；该候选变异、候选队列优先级、LLM Manager 调度与真实全链后端仍是 Stage 10/11 的下一门禁。真实模型接入还须实验室确认数据出境、凭据和费用预算，模型输出来历不能替代仿真证据。

本轮定向回归 `28 passed`，全量 Python 回归 `745 passed, 3 skipped`；新增代码没有触发在线 API 或新的 Cadence 作业。

本地定向检查：

```powershell
$env:PYTHONPATH='src'
python -m pytest -q --disable-warnings tests/test_llm_refiner.py tests/test_agent_safety.py tests/test_manager.py --basetemp=results/runs/pytest_llm_refiner_stage11
```
