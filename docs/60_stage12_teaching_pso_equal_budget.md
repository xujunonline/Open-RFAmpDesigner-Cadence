# Stage 12：教学 MOS1 的 random/PSO 同预算诊断 pilot

本阶段只验证“优化器提案 → **同一 Cadence Spectre 后端** → 原始 SP/noise 计分 → 独立重放 → 同预算比较”。对象仍为 `circuit/spectre/teaching_mos1_lna.scs` 的单管教学共源级，**不是**授权 PDK、论文三级 LNA、Table IV/V 性能或 Fig. 10 的论文 sample efficiency。详见随机先行实验 `docs/40_stage07_teaching_random_baseline.md`。

## 共同问题

两法均用 seed=17、4 次真实仿真预算、8–12 GHz 最差 NF/S11、同一个 `stage2_cost`（NF 上限 2.0 dB、headroom 0.2 dB、S11 门槛 -20 dB）。固定 VBIAS=0.65 V、WMOS=300 µm、LDD=2 nH、CBLOCK=5000 fF；仅 LGS∈[0.7,1.3] nH、LSS∈[180,320] pH 可变。每点由相同 `run_teaching_lna` 执行 DC/SP/noise，保留网表、Spectre 日志、原始 PSFASCII、S2P、CSV、指标和哈希清单；两法均调用 `audit_teaching_lna` 从原始数据重算分数。

当前环境没有 `scikit-opt` (`sko`)。`TeachingStage2PSO` 是本项目的**教学级确定性实现**，不是论文使用的 `scikit-opt` PSO：两个粒子、两代，归一化二维位置和速度；惯性 0.55、个体/群体权重各 1.4、速度绝对值上限 0.25，越界裁剪后物理参数保留 6 位小数。粒子代内同步评价；一代全部完成后才根据原始分数更新位置。四次运行恰为 2×2，不允许失败点以假分数继续。相同 seed 的前两次初始化提案与随机法完全一致，后两次才体现反馈。参数、方法标签和电路条件保存在私有 `search_config.json`；程序不将教学分数送入论文 `impedance_matching` 工具或 LNA pass/fail。

## 真实运行与重审

- 随机源档：`results/runs/teaching_matching_random/20260926T151700Z_061d699f/`，4/4 点；`audit_teaching_matching_random` 再审计为 `verified`。
- PSO 源档：`results/runs/teaching_matching_pso/20260927T012145Z_92281c4d/`，4/4 点；`audit_teaching_matching_pso` 按原始 Spectre 分数**重放每次 ask/tell 及下一代提案**，再审计为 `verified`。运行前宿主物理余量约 3.94 GiB，高于 2.66 GiB 门禁。
- 派生同预算报告：`results/runs/teaching_stage2_comparisons/20260927T012415Z_6b24413a/`，存源 run ID/manifest SHA-256、逐次 cost/截至该次的最优 cost、CSV/JSON 和自身清单；`audit_teaching_stage2_comparison` 重新审计两个源档后重算比较。

| 已评估点数 | 随机本次 cost | PSO 本次 cost | 两法截至该点最佳 cost |
| ---: | ---: | ---: | ---: |
| 1 | 10539.199 | 10539.199 | 10539.199 |
| 2 | 13529.627 | 13529.627 | 10539.199 |
| 3 | 12219.905 | 11076.924 | 10539.199 |
| 4 | 11647.543 | 12402.375 | 10539.199 |

在这**一个 seed、四次评估**中，观测最优点是双方共有的首点，最差 S11≈-9.46 dB，仍未达到 -20 dB；NF≈1.25 dB 只满足此教学 cost 的 NF 部分。后两点 PSO/随机各有高低，最佳 cost 打平。离散频点的稳定性 K 不等于连续频率、任意端接或版图后稳定性证明；不能据此推断 PSO 与随机搜索的总体优劣，也不能计算论文 pass@1。旧随机档与新 PSO 档在不同日期运行，**不比较墙钟延迟或 CPU 效率**；这里只有相同调用数下的样本序列。两源和报告均 `not_lna_result=true`、`spec_pass=null`。

重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_matching_pso results/runs/teaching_matching_pso/20260927T012145Z_92281c4d
python -m orfadc.experiments.compare_teaching_stage2 `
  --audit-dir results/runs/teaching_stage2_comparisons/20260927T012415Z_6b24413a `
  --random-dir results/runs/teaching_matching_random/20260926T151700Z_061d699f `
  --pso-dir results/runs/teaching_matching_pso/20260927T012145Z_92281c4d
```

后续已按相同教学规格与四次预算扩展到五个 seed，见 `docs/67_stage12_teaching_multiseed_pilot.md`；该扩展没有解决授权 PDK LNA、长预算或算法实现差异。真正的下一门槛是同一**合格、可实现的授权 PDK LNA**设计域与统一 fullchain evaluator，再做 GA/BO/PSO/SA 的同预算比较和论文样式消融；若比较时间效率，还须统一 CPU/墙钟、失败点和许可等待的记录协议。不得用教学报告填充 Table IV/V/VI 或 Fig. 10-like 论文结果。
