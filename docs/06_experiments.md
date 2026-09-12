# 实验复现设计

## 阶段 1：论文结构复现

- 复现 Table I 工具接口。
- 复现 Table II 变量范围。
- 复现 Table III 规格表。
- 实现公式 (1)(2)。
- 定义 Table IV/V/VI-like 输出 schema。

## 阶段 2：Cadence 简化 LNA

- 使用实验室授权 PDK。
- 建单级或两级 LNA。
- 跑 DC op、S 参数、noise、AC、compression。
- 输出 `metrics.json` 和 `waveforms.csv`。
- 验证 Python-OCEAN 闭环。

## 阶段 3：论文级近似复现

- 三阶段 LNA。
- MCR 或等效 RLC 网络。
- Table III 的 10 个 specs。
- 5 seeds。
- 输出 Fig. 7-11-like 和 Table IV-VI-like。
- 明确标注不能严格对比论文 TSMC N65 原始数值。

