# Stage 12: 教学 MOS1 匹配微型 GA pilot

## 目的与证据等级

在 `docs/60_stage12_teaching_pso_equal_budget.md` 和 `docs/77_stage12_teaching_sa_three_method_pilot.md` 的同一公开 MOS1、LGS/LSS 范围、固定偏置与 NF/S11 cost 上补一个可重放的 GA 控制流。该控制器是**本项目的两成员教学 GA**，不是论文所用软件实现，也不是授权 PDK LNA 的 baseline。每个 score 来自新执行的 Cadence Spectre DC/SP/noise 原始档，不由代理或近似公式填造。

## 方法

`src/orfadc/tools/stage2_ga.py` 使用固定 seed、两成员种群；每个候选先在归一化二维范围生成，再映射到 LGS 0.7–1.3 nH、LSS 180–320 pH。完整评估两个成员后，按真实 cost 排序，通过偏向较优父代的线性混合和每轴 ±0.2 的归一化变异生成下一代，边界截断。预算限定偶数 4–12；ask/tell 先后、非有限/负 score 和越界预算均拒绝。保留全局最优仅用于报告，不伪作额外仿真样本。

`src/orfadc/experiments/run_teaching_matching_ga.py` 对每点调用现有 `run_teaching_lna`，先检查证据清单和点参数，再由独立 `audit_teaching_lna` 从原始档重算 NF/S11，写 `search.csv`、`metrics.json` 和源清单。任一 Spectre/解析/审计失败即停止，不用无效点更新 GA。`audit_teaching_matching_ga.py` 从 seed 开始重放全部提案与评分，逐点检查原始 Spectre 档、CSV、汇总和 manifest；重哈希后篡改配置、CSV、最佳分数也会被拒绝。

## 单 seed 实测

私有原始档为 `results/runs/teaching_matching_ga/20260927T100305Z_b891a9ae/`，seed=17、预算四点，审计 `verified`。四点均实际完成，最佳点出现在第 4 次评估：LGS≈1.007909 nH、LSS≈256.666259 pH，最差带内 NF≈1.186 dB、S11≈-9.945 dB，教学 cost≈10054.720。S11 仍明显未满足教学目标；没有合格 LNA 或论文规格成功。该 pilot 与既有方法只共享电路、范围、目标和预算，不构成统计性能比较。没有 GA 的五 seed 汇总、BO、授权 PDK fullchain 或论文 Table IV/V/VI、Fig. 10 结果。

本轮 GA 单 seed 定向测试 `8 passed`；后续已完成同一组五 seed 扩展，见 `docs/87_stage12_teaching_four_method_multiseed.md`。所有原始 Spectre 网表、波形、日志和私有配置留在 Git 忽略目录。Stage 12 继续 `partial`；BO 和真正 LNA baseline 仍未完成，教学结果必须与其分开。
