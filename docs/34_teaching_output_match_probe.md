# 路线 B：理想输出匹配的单频成功与宽带失败

2026-09-26。在公开 MOS1 单管共源教学电路上，以 10 GHz 为中心做一个受控的**输出端**匹配诊断。它不是论文 Table I 的完整 Impedance Matching 工具（论文 Stage 2 还要求输入 NF/S11 和级间匹配），也不是可制造的片上网络或合格 LNA。所有网表使用人为 MOS1 参数和理想 L/C，直接由 Spectre 25.1 仿真；没有商业 PDK 或 Virtuoso schematic。

## 分析起点

固定 `VBIAS=0.65 V`、输入/输出参考端口各 50 Ω。原始基线 `20260926T125404Z_7ed0e9c8` 在 10 GHz 的复数 `S22≈0.7100+j0.6951`，折算端口输出阻抗 `Zout=50(1+S22)/(1-S22)≈1.12+j122.53 Ω`。基线漏极理想电感 2 nH，漏极到输出端口的串联隔直电容 5 pF。

`ideal_shunt_l_series_c_output_match()` 从**实测 S22** 出发，令 `ω=2πf`、`Zsh=Zout+j/(ωCbase)`，拟合 `1/Zsh=1/Rparallel-j/(ωL)`。本点得到 `Rparallel≈14.10 kΩ`、反推 `L≈2.001 nH`，与输入的 2 nH 相符。使并联 R/L 在 10 GHz 的实部为 50 Ω，取 `X=Rparallel·sqrt(50/(Rparallel-50))`、`Lnew=X/ω`，再令串联 `Cnew` 抵消并联支路虚部。解析建议为 `LDD≈13.3886 nH`、`CBLOCK≈18.9866 fF`。该公式只适用于此假设拓扑、这一参考平面及单频；源退化和反馈改变有效输出电阻，所以直接把裸 `1/gds` 当作端口电阻会给出不同结果。若观测 S22 不能拟合正的并联 R/L，函数会拒绝输出建议。

`run_teaching_lna.py` 现在仅对白名单 `VBIAS=0.50..0.70 V`、`LDD=1..16 nH`、`CBLOCK=15..5000 fF` 做数值替换；逐 run 仍检查宿主 2.66 GiB 物理余量、Spectre 0-error/0-warning、PSFASCII/Touchstone/CSV/清单。`audit_teaching_lna.py` 核对归档参数与实际网表、DC/器件工作点、RF 指标和 S 参数复数。基线与三个新候选均有独立原始文件且只读审计通过；旧基线 SHA-256 与新版 runner 默认渲染网表一致。`summarize_teaching_matching.py` 只接受同偏置、同网表其余部分、同频率网格的运行，生成 `results/runs/teaching_match_summaries/20260926T131528Z_9bedf7e2/` 的 CSV/JSON/清单。

## 实测对照

下表前两项是**10 GHz 单点**，后三项是 **8–12 GHz 41 个采样点**的最差值；S 参数 dB 均以 50 Ω 为参考。完整 SP 为 0.1–20 GHz/200 点。

| LDD / CBLOCK | run_id | S22@10 dB | S21@10 dB | S11 带内最差 dB | S22 带内最差 dB | S21 带内最差 dB | S21 纹波 dB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 nH / 5000 fF | `20260926T125404Z_7ed0e9c8` | -0.056 | 10.079 | -10.179 | -0.055 | 8.204 | 3.266 |
| 9.4 nH / 27 fF | `20260926T130932Z_c7592de3` | -9.439 | 28.511 | -7.881 | -0.192 | 16.731 | 11.779 |
| 13.2 nH / 19.5 fF | `20260926T131055Z_5992d4c6` | -17.670 | 28.960 | -6.316 | -0.205 | 17.004 | 12.121 |
| 13.3886 nH / 18.9866 fF | `20260926T131323Z_2ab5cf5e` | -31.228 | 29.032 | -6.104 | -0.191 | 16.715 | 12.324 |

最后一行带边更能说明失败：8/10/12 GHz 的 S22 分别约 `-0.191/-31.228/-0.617 dB`，S11 分别约 `-8.306/-6.113/-7.090 dB`，S21 分别约 `16.715/29.032/17.850 dB`。虽然中心输出匹配显著改善，带边几乎完全反射、输入匹配恶化且增益峰值尖锐。四 run 的最差 NF 均约 1.151 dB、供电约 4.973 mA；这仅是固定教学模型和参考平面下的观察，不代表输出匹配不影响真实 LNA 噪声。完整 0.1–20 GHz 采样网格的最小 K 约 1.000007、最大 `|Delta|≈0.998987`；它们非常贴近门限，不能证明连续频率、工艺角落、大信号或负载变化下的稳定性。

复核命令：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T131323Z_2ab5cf5e
py -m orfadc.experiments.summarize_teaching_matching `
  results/runs/teaching_lna/20260926T125404Z_7ed0e9c8 `
  results/runs/teaching_lna/20260926T130932Z_c7592de3 `
  results/runs/teaching_lna/20260926T131055Z_5992d4c6 `
  results/runs/teaching_lna/20260926T131323Z_2ab5cf5e
```

## 后续门槛

1. 真正的宽带输入/输出匹配需要优化 8–12 GHz 全带及带外稳定性，同时计入实际电感 Q、自谐振、面积、损耗和寄生；13.4 nH 的理想电感不可直接当成片上可用元件。
2. 加上授权 PDK/Virtuoso 的 CDF/PCell 几何验证和可信模型后，在同一电路拓扑/参考平面重做多频点 S11/S21/S22/NF/K/Delta。只有合格候选才进入 HB/IP1dB、fullchain、agent 的 accepted 门禁。
3. 路线 B 如继续探索，应明确设定较低保真度的教学目标，用约束优化而非最大化 10 GHz 峰值；不得把本次中心频点成功填入论文 Table IV/V 或 Fig. 7 原始曲线。
