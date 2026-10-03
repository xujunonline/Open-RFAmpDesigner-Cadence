# Stage 12: 四方法五 seed 教学匹配汇总

## 数据来源

在 `docs/86_stage12_teaching_ga_pilot.md` 的同一 GA 配置下，新增 seed 1、2、3、4，每个四次新的 Cadence Spectre 教学 MOS1 DC/SP/noise 评估；连同 seed 17 共五个 seed/20 个 GA 点，逐个从原始波形与证据清单重放为 `verified`。已有 random/PSO/SA 各 20 点来自 `docs/77_stage12_teaching_sa_three_method_pilot.md` 的已审计归档，没有重跑或改写。

`src/orfadc/experiments/summarize_teaching_stage2_four_methods.py` 以三方法汇总和五个 GA 原始归档为输入，逐层重审原始点，核对相同的 seed、四次预算、MOS1 电路参数、LGS/LSS 域、NF/S11 cost 和共同初始点，保存逐 seed 与逐评估 best-cost CSV、源档哈希及 `metrics.json`。私有汇总 `results/runs/teaching_stage2_four_methods/20260927T101428Z_4e5d538c/` 从 80 个真实 Spectre 教学点重建为 `verified`；重哈希后篡改配置、CSV 或均值均被拒绝。

| 方法 | 五 seed 最终最佳教学 cost 均值 |
| --- | ---: |
| Random | 10312.32 |
| PSO | 10306.77 |
| SA | 10124.70 |
| GA | 9719.90 |

这些只是固定五 seed、每法四点评分预算的描述统计。微型 GA、教学 SA/PSO 都不是论文实现；五 seed、四次评估和失败的匹配目标不足以判断算法优劣或样本效率的普遍趋势。结果不是合格 RF LNA、不是论文 Fig. 10 或 Table IV/V/VI，也不产生 `pass@1`。本机无 `scikit-opt`、scikit-learn、SciPy 或 scikit-optimize，BO 尚未实施。Stage 12 仍为 `partial`；真实授权 PDK fullchain baseline 与 agent 消融依赖合格候选后端。

更新：上段是四方法报告生成时的环境快照。随后已在隔离目录安装 `scikit-optimize` 并完成教学 BO；新的五方法 100 点报告见 `docs/93_stage12_teaching_bo_five_method_multiseed.md`。论文 `scikit-opt` 仍未用于本工程，不可把两者混同。
