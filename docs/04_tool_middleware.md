# 工具中间件

论文 Table I 的四个工具对应：

- `active_sizing.py`
- `impedance_matching.py`
- `band_planning.py`
- `fullchain_eval.py`

设计原则：LLM 只能调用工具和提交 JSON 参数；工具负责数值计算、仿真调用和结果校验。任何真实 pass/fail 必须来自 Cadence/Spectre 或明确标注的开源仿真 fallback。

