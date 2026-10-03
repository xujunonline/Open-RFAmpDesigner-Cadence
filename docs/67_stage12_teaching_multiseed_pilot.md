# Stage 12：教学 MOS1 五 seed 同预算 random/PSO 比较

## 范围与协议

在 `docs/60_stage12_teaching_pso_equal_budget.md` 的 seed=17 单次 pilot 基础上，增加 seed=1、2、3、4。每个 seed 的 random 与本项目教学 PSO 各执行 **4 次 Cadence Spectre DC/SP/noise**；相同 seed 的两法前两点相同，后两点才受 PSO 反馈影响。五组均使用同一个公开 MOS1 教学共源电路、8–12 GHz 最差 NF/S11、相同 Stage 2 诊断 cost、相同 LGS/LSS 域、偏置和停止预算。汇总器会逐项核对随机法与 PSO 的配置快照，并跨 seed 校验共同配置一致。

这不是授权 PDK LNA，不是论文 `scikit-opt` PSO，不是 Table IV/V 的 pass@1，也不是 Fig. 10 的 sample efficiency。两法 5×4 次评估虽可比较样本数，运行跨越不同日期，不比较墙钟或 CPU 效率；每个源档仍 `not_lna_result=true`、`spec_pass=null`。

## 原始档案与结果

每组的两个搜索档各包含四个独立 Spectre 点和自身来源清单；配对报告通过 `audit_teaching_stage2_comparison` 重放源档。括号内是最终四次评估后的**最低教学诊断 cost**，越低越好，均非 LNA 达标。

| seed | random 源 run_id | PSO 源 run_id | 配对报告 run_id | random / PSO 最佳 cost |
| ---: | --- | --- | --- | ---: |
| 1 | `20260927T033104Z_aad0ea29` | `20260927T033126Z_fcbff559` | `20260927T033148Z_a0af3407` | 9784.051 / 10255.639 |
| 2 | `20260927T033201Z_c631e3ae` | `20260927T033223Z_fe7489a6` | `20260927T033243Z_cad37566` | 11466.805 / 11904.664 |
| 3 | `20260927T033250Z_fda39d3f` | `20260927T033311Z_b2b0a3d5` | `20260927T033333Z_988fc074` | 9090.144 / 9090.144 |
| 4 | `20260927T033343Z_3bf947e5` | `20260927T033404Z_255f754f` | `20260927T033425Z_d1e01337` | 10681.415 / 9744.190 |
| 17 | `20260926T151700Z_061d699f` | `20260927T012145Z_92281c4d` | `20260927T012415Z_6b24413a` | 10539.199 / 10539.199 |

五组共 40 个真实 Spectre 评估点；PSO 最佳 cost 较低 1 组，random 较低 2 组，打平 2 组。五 seed 的最终最佳 cost 均值为 random≈10312.323、PSO≈10306.767，差值很小。样本量、问题域与方法实现均不足以支持算法总体优劣判断；不能由该教学 cost 推算论文成功率。

跨 seed 结果档：`results/runs/teaching_stage2_multiseed/20260927T033634Z_f6923862/`。它保存源配对报告 ID、每 seed 与每次评估 CSV、JSON 和自身 SHA-256 清单。`src/orfadc/experiments/summarize_teaching_stage2_multiseed.py` 在生成及只读审计时都会再次重审每个配对报告、两种搜索轨迹及底层 Spectre 原始点；拒绝重复 seed、混合规格/参数域/算法配置/预算、重哈希伪造数值与 `spec_pass=true`。重审：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.summarize_teaching_stage2_multiseed `
  --audit-dir results/runs/teaching_stage2_multiseed/20260927T033634Z_f6923862
```

## 教学样本效率图

`src/orfadc/plots/plot_teaching_stage2_efficiency.py` 在重审上述五 seed 汇总档及底层 Spectre 来源后绘制均值最优诊断 cost 与每法评估次数的关系。已生成并只读重审 `results/runs/teaching_stage2_plots/20260927T043054Z_1c5c5a35/teaching_stage2_sample_efficiency.png`；同目录保存 `metrics.json` 和哈希清单。图中明确写明是教学 MOS1 诊断，**不是论文 Fig. 10 或合格 LNA**。图表审计还根据源档重新渲染并逐字节比较 PNG；图像、源清单或结果标签被篡改都会拒绝。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.plots.plot_teaching_stage2_efficiency `
  --audit-dir results/runs/teaching_stage2_plots/20260927T043054Z_1c5c5a35
```

## 剩余门禁

要得到论文式 GA/BO/PSO/SA 和多智能体消融，必须先在授权 PDK、**合格且可实现的 LNA** 上统一候选域、fullchain 指标、压缩点、仿真预算、种子和超时规则。当前教学五 seed 仅扩大了方法层验证，不能填充论文结果表或 Fig. 10-like 曲线。若后续研究样本效率，应预注册更多 seed/预算、处理失败点和许可等待，并将随机/优化器版本、真实 Spectre 调用数、CPU/墙钟与模型调用时间分别记录。
