# Stage 12：教学 MOS1 的 random/PSO/SA 同预算实测

## 实验边界

继 `docs/67_stage12_teaching_multiseed_pilot.md` 的五 seed random/PSO 实测，本轮加入一个**本项目自实现的教学模拟退火（SA）**。三法均使用同一个公开 MOS1 共源匹配电路、相同 8–12 GHz 诊断 Stage 2 cost、LGS 0.7–1.3 nH、LSS 180–320 pH、固定偏置及每 seed **4 次**真实 Cadence Spectre DC/SP/noise 评估；seed 为 1、2、3、4、17。SA 与同 seed random 的**首点完全相同**，其后按已测 cost、500 起始温度、0.65 降温系数和归一化 0.25 邻域提出/接受候选。每个点存原始 Spectre 与导出文件，SA 状态可从这些文件重放。

此实现不是论文或 `scikit-opt` 的 SA，不是授权 PDK LNA，更不是 Table IV/V 的 pass@1 或 Fig. 10 原始/近似数值。三法共 **60 个**实测点，其中 SA 本轮新增 20 个；random/PSO 的 40 个是此前归档，不重复计为新仿真。每个源档均保留 `not_lna_result=true`、`spec_pass=null`。运行跨不同时间，**只比较评估调用数和本教学 cost，不比较墙钟/CPU/许可等待效率**。

SA 的第一点由 seed 的均匀随机数给出；此后在当前已接受点的两个归一化坐标各扰动最多 0.25，并截断到 `[0,1]`，映回 LGS/LSS 的物理单位。第 `n=1,2,3` 次邻域提案使用 `T_n=500×0.65^(n-1)`；若新 cost 不高于当前 cost 则接受，否则以 `exp[-(J_new-J_current)/T_n]` 的概率接受。**每个被提出的点都调用一次 Spectre**，即使未被 SA 接受也计入预算，并参与“历史最佳已测 cost”。这只是一个固定超参数的小预算教学实现，不声称是论文源码。

## 私有来源与结果

| seed | SA 源 run_id | random 最佳 cost | PSO 最佳 cost | SA 最佳 cost |
| ---: | --- | ---: | ---: | ---: |
| 1 | `20260927T065114Z_2bcd0d3f` | 9784.051 | 10255.639 | 9079.331 |
| 2 | `20260927T065133Z_f178301a` | 11466.805 | 11904.664 | 11417.829 |
| 3 | `20260927T065151Z_548efd9b` | 9090.144 | 9090.144 | 10155.137 |
| 4 | `20260927T065211Z_01e91e3d` | 10681.415 | 9744.190 | 10528.656 |
| 17 | `20260927T065034Z_023ee77a` | 10539.199 | 10539.199 | 9442.555 |

五 seed 最终最佳 cost 均值为 random≈10312.323、PSO≈10306.767、SA≈10124.702。SA 在三个 seed 上获得三法最低 cost，另两个 seed 没有；这些极小预算的教学数据**不支持总体优劣或显著性判断**。SA 的 `point_00` 至 `point_03`、配置、CSV、原始指标和证据清单位于 `results/runs/teaching_matching_sa/<run_id>/`，旧 random/PSO 来源见前述文档。

三方法汇总 `results/runs/teaching_stage2_three_methods/20260927T065413Z_42538ea4/` 保存每 seed 和每次评估的 CSV/JSON；`summarize_teaching_stage2_three_methods.py` 重审旧五 seed 汇总、其下 40 个源点及新的 20 个 SA 点，并检查 seed、预算、目标、变量域与共同首点。三曲线 PNG 位于 `results/runs/teaching_stage2_plots/20260927T065650Z_4ec855f4/teaching_stage2_three_methods.png`；图像审计从源档重新渲染并逐字节比较。图仅叫**教学 MOS1 三方法诊断曲线**，不叫论文 Fig. 10 复现。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.summarize_teaching_stage2_three_methods `
  --audit-dir results/runs/teaching_stage2_three_methods/20260927T065413Z_42538ea4
python -m orfadc.plots.plot_teaching_stage2_three_methods `
  --audit-dir results/runs/teaching_stage2_plots/20260927T065650Z_4ec855f4
```

在授权 Cadence 环境中重新做**新实验**时，先按 `docs/31_vm4g_memory_acceptance.md` 检查宿主余量，再对各 seed 调用 `python -m orfadc.experiments.run_teaching_matching_sa --seed <seed> --budget 4`；每次自动创建独立私有目录。逐档运行 `python -m orfadc.experiments.audit_teaching_matching_sa <新目录>`。将新 SA 目录与相同 seed/预算/目标的 random/PSO 多 seed 汇总传给 `python -m orfadc.experiments.summarize_teaching_stage2_three_methods --baseline-dir <旧或新汇总目录> <各SA目录>`，通过后才绘图。不要直接改写本轮已有档案，失败运行也应保留。

## 后续门禁

真正的论文式算法比较仍需**同一合格 PDK LNA fullchain**、可实现无源/版图与角落约束、统一 GA/BO/PSO/SA/random 搜索域、相同 seed/预算/超时、压缩点和原始数据复核。LLM 多智能体消融与 KB/EB 必须在该后端可用后独立实施；不能把本教学 MOS1 的 cost 直接换算为论文成功率或时间优势。
