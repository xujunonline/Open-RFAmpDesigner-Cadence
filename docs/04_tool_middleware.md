# 工具中间件

论文 Table I 的四个工具对应：

- `active_sizing.py`
- `impedance_matching.py`
- `band_planning.py`
- `fullchain_eval.py`

设计原则：LLM 只能调用工具和提交 JSON 参数；工具负责数值计算、仿真调用和结果校验。任何真实 pass/fail 必须来自 Cadence/Spectre 或明确标注的开源仿真 fallback。

当前 `impedance_matching.py` 中的 `ideal_shunt_l_series_c_output_match()` 仅用公开教学 MOS1 归档的复数 S22 求 10 GHz 理想输出 L/C 起点，随后由受控 Spectre runner 与只读审计验证。它不处理论文 Stage 2 的 NF/S11、级间网络、PSO 或工艺无源约束，不能代替 Table I 工具验收；实测中心改善但宽带失败见 `docs/34_teaching_output_match_probe.md`。

独立实验入口 `run_teaching_input_grid.py` 已把公开教学电路的 LGS/LSS 扫描接到真实 Spectre DC/SP/noise、原始数据审计与 `stage2_cost()`；9 点结果及全部未达 S11 门槛见 `docs/35_teaching_input_matching_grid.md`。它没有接入面向论文候选的 `AgentToolRegistry.impedance_matching`，也没有 stage-specific PDK lookup、PSO、级间网络或可实现无源，因此仍是教学方法子集，不返回可信 LNA `spec_pass`。
