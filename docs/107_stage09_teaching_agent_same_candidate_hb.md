# Stage 09：三级教学 agent 候选的同电路 HB 压缩诊断

## 目标与来源

`docs/106_stage10_three_stage_planned_agent.md` 的正常两轮 agent trace `results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba/` 有第二轮候选 `S1_seed0_teach3_resonance`，输出副边电感 4.085532 nH。此前只有 DC/SP/noise，不能从旧的 1.0 nH 基线 HB 借压缩点。本轮对**相同的公开 MOS1 教学网表参数**新跑 10 GHz、7 谐波的独立 HB 功率点，并从原始 PSFASCII/端口相量与独立 SP/noise 档重建同候选报告。所有内容继续 `not_lna_result=true`、`spec_pass=null`。

## 真实仿真与计算

12 个新的 Spectre 运行逐点独立归档于 `results/runs/teaching_three_stage_hb/`，输入功率为 -70、-50、-30、-20、-17、-15、-14、-13、-12、-11.5、-11、-10 dBm；均是公开模型，0 errors/0 warnings。`results/runs/teaching_three_stage_hb_sweeps/20260927T194309Z_29931698/` 从每点清单、同一公开模型、161 点四条复数 S、HB 基波的真实输入可用功率与差分输出交付功率重建驱动曲线，并在 -12/-11.5 dBm 夹住 1 dB 交点。前三个低驱动点拟合得到的**诊断级** IP1dB 约 -11.820 dBm、OP1dB 约 -5.277 dBm。7 谐波、单频单角落的插值结果未经全功率/谐波收敛或物理电路核验，不是论文 Table IV/V 的数值。

新 `audit_teaching_three_stage_agent_fullchain.py` 先各自重审 agent 两轮源档与上述 HB 扫描，再核对第二轮候选的参数/网表、公开模型、两端口混合参考平面。候选 DC/SP/noise 与 HB 扫描首点的 161 点 `S11/S21/S12/S22` 复数原始轨迹及 `NF/NFmin` 原始轨迹逐频比较；HB 扫描器保证所有驱动点小信号轨迹不变。结果 `results/runs/teaching_three_stage_agent_fullchain/20260927T194442Z_94ec29cd/` 的最大 S 与噪声差均为 0；报告清单及全部来源可独立重算。旧 1.0 nH 扫描替换、混合电感点、汇总指标篡改并重算清单均被测试拒绝。

该同候选的 9–11 GHz 最差 S11 约 -14.221 dB、S21 约 1.677 dB、S22 约 -2.072 dB、NF 约 5.664 dB、S21 纹波约 8.452 dB，供电电流约 14.885 mA。S1 的增益目标 25 dB、NF 上限 5 dB 均失败；虽诊断压缩点高于 S1 所列 -25 dBm 门槛，也不能用它豁免其他约束。S22 的 -10 dB 是本地输出失配诊断阈值，不应伪称 Table III 独立规格。没有授权 PDK 的有损无源 Q/k/SRF、CDF/PCell/DRC、模型告警排除、角落/EM/PEX 或稳定性全域资格；混合输入/输出参考阻抗亦须保持注明。因此本报告只叫**同候选教学诊断聚合**，不能开放合格 `fullchain_eval`，不能输出 `spec_pass=true`。

## 复核

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage_hb_sweep --audit-dir results/runs/teaching_three_stage_hb_sweeps/20260927T194309Z_29931698
python -m orfadc.experiments.audit_teaching_three_stage_agent_fullchain results/runs/teaching_three_stage_agent_feedback/20260927T191321Z_b2769bba results/runs/teaching_three_stage_hb_sweeps/20260927T194309Z_29931698 --audit-dir results/runs/teaching_three_stage_agent_fullchain/20260927T194442Z_94ec29cd
python -m pytest -q --basetemp="results/runs/pytest_teach3_fullchain_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_teaching_three_stage_agent_fullchain.py tests/test_teaching_three_stage_hb_sweep.py
```

`--audit-dir` 只读重算既有派生报告，不会创建新仿真或报告。不得重新派发已完成的 HB 点。下一优先级转回授权 PDK 的物理无源/合法几何与真正 LNA 全链；教学 HB 功率点不应为了追数值而无界扩张。
