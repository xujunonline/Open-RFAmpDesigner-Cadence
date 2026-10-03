# Stage 07: 教学 MOS1 输入匹配随机基线

本实验只验证“由优化器提出 LGS/LSS 数值、Cadence Spectre 实测、从原始数据计分、独立复核”的方法链。它使用公开的 MOS1 教学模型和单管共源电路，不是授权 PDK，也不是论文的三级 LNA、MCR 匹配或 Stage 2 完成验收。

## 固定问题与实现

- 电路为 `circuit/spectre/teaching_mos1_lna.scs`，固定 VBIAS=0.65 V、WMOS=300 um、LDD=2 nH、CBLOCK=5000 fF；仅改变 LGS 和 LSS。该教学网表的 SP/noise 是 0.1–20 GHz 线性网格，共 200 个频点，本项目在 8–12 GHz 取最差 NF/S11。
- `stage2_sampling.py` 用固定 seed 生成 1–12 个随机候选，LGS 在 0.7–1.3 nH，LSS 在 180–320 pH。不是论文 Table II 的完整合法设计域，也没有 PSO 或物理无源约束。
- `run_teaching_matching_random.py` 逐点调用原有 Spectre runner，保存候选网表、原始 PSFASCII、Touchstone、日志、指标和证据清单；每个点再调用 `audit_teaching_lna` 重提取原始 RF 指标后才计算 `stage2_cost`。任何一个点失败即停止，归档 `incomplete` 和失败类型。
- `audit_teaching_matching_random.py` 重新由 seed 生成搜索计划，并逐点核对配置、源清单 SHA-256、原始 SP/noise 与 DC 审计、CSV/JSON 指标、cost 和最佳点；旧归档只读，不回写分数。

命令示例：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.run_teaching_matching_random --seed 17 --budget 4
py -m orfadc.experiments.audit_teaching_matching_random results/runs/teaching_matching_random/<run_id>
```

运行前仍须满足授权 SSH、Spectre 可用和宿主至少 2.66 GiB 物理余量。默认结果位于 Git 忽略目录，不能把商业模型/授权路径加入仓库。

## 本次实测

2026-09-26 在 4 GiB VM 上经 SSH 探测 Spectre 可用，运行前宿主物理余量约 3.13 GiB。`results/runs/teaching_matching_random/20260926T151700Z_061d699f/` 的 seed=17、budget=4 四个点均完成 Spectre，整体只读审计 `verified`。NF 目标为 2.0 dB、headroom 为 0.2 dB，即 NF 诊断门槛 1.8 dB；S11 诊断门槛 -20 dB。

| 点 | LGS (nH) | LSS (pH) | 最差 NF (dB) | 最差 S11 (dB) | 诊断 cost | 采样最小 K |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1.013190 | 292.936709 | 1.2486 | -9.4608 | 10539.20 | 1.0000000016 |
| 1 | 1.276297 | 220.547553 | 1.5936 | -6.4704 | 13529.63 | 1.0000196682 |
| 2 | 1.159664 | 278.590781 | 1.4783 | -7.7801 | 12219.91 | 1.0000000029 |
| 3 | 1.096830 | 195.422687 | 1.2286 | -8.3525 | 11647.54 | 1.0000473750 |

四点 NF 均过自定门槛，但 S11 均失败；最优点只是该 cost 定义下的最小违反，并非可接受匹配。K 接近 1 的采样结果不能替代带外、角落、实际端接和布局后稳定性验收。输出匹配、级间匹配、增益纹波、压缩点均未纳入此目标；`not_lna_result=true`、`spec_pass=null`。随机基线也不能与现有规则网格直接宣称算法优劣，因为两者候选集不同且都很小。

## 后续门槛

教学级 random/PSO 的 seed=17、各四次真实 Spectre 同预算 pilot 与原始数据重放见 `docs/60_stage12_teaching_pso_equal_budget.md`；它仅验收优化/仿真/审计方法链，未得到合格匹配，也不能推断算法优劣。下一步仍须在授权 PDK/CDF 几何参数传播和实际无源约束下建立合格 LNA 候选，使通用 `impedance_matching` 接真实 Cadence Stage 2 后端并扩展多 seed 公平比较。未经该验收，agent 注册表必须返回匹配后端不可用，不能消费教学分数作为论文成功观察。
