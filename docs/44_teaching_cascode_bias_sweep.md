# Stage 03：公开 MOS1 cascode 首级 VCAS 小预算扫描

本实验只改变上管 M2 的栅极偏置 `VCAS`，固定 M1 的 `VBIAS=0.65 V`、两管 `W=300 um/L=100 nm`、输入 `LG=1 nH/LS=240 pH`、输出 `LD=1.688093 nH/RDAMP=150 ohm/CBLOCK=225.079 fF`、50 ohm 端口以及 8–12 GHz 的 161 点 SP/noise 网格。模型是公开人工 MOS1，理想无源没有 Q/SRF 或版图约束。目的仅为检查双管工作区与本机小信号响应对偏置的敏感性，不设置论文规格通过结论。

三个直接 Spectre 源运行分别为 `results/runs/teaching_lna/20260926T173201Z_e6afbeb0/`（0.85 V）、`20260926T164104Z_62c9f88f/`（0.95 V，沿用已审计旧结果）和 `20260926T173228Z_7ad352b4/`（1.05 V）。各自 0 errors/0 warnings、161 点 DC/SP/noise/工作点数据，`audit_teaching_lna` 通过。`summarize_teaching_cascode_bias.py` 拒绝不同器件/网络参数、重复偏置或频率网格错配，按原始数据重算后导出 `results/runs/teaching_cascode_bias_summaries/20260926T173523Z_c49cbb86/` 的 `bias_sweep.csv`、`metrics.json` 和哈希清单；该报告还能从三个源归档只读重建。

另将 `--vcas-v` 数值白名单接入公开 OA schematic 创建脚本和 runner。**新** 1.05 V OA cell `results/runs/teaching_oa/20260926T174324Z_476a26f3/` 的 `schCheck=(0 0)`、网表 VCAS、DC/SP/noise、双管工作点与 161 点 OCEAN 导出均通过只读审计；与上述 1.05 V 独立直接 Spectre 的交叉报告在 `results/runs/teaching_cascode_crosschecks/20260926T174613Z_ecf2da89/`。最大复数 S 差约 `7.23e-15`、噪声差约 `7.11e-15`、工作点字段差约 `3.33e-16`。错配到 0.95 V 直接运行时，交叉审计按参数拒绝。此项证明**公开 analogLib 教学电路**的 VCAS 参数已从 OCEAN 创建脚本传播至 Spectre，不是授权工艺 PCell/CDF 参数传播的证明；该重复 1.05 V 仿真也只作为数据通路交叉验收，不增加偏置扫描的独立参数点数。

| VCAS (V) | 最差 S11 (dB) | 最差 S21 (dB) | 最差 NF (dB) | 电源电流 (mA) | M1 VDS-VDSAT (V) | M2 VDS-VDSAT (V) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.85 | -10.054 | 6.487 | 2.201 | 4.829 | 0.00233 | 0.800 |
| 0.95 | -10.065 | 6.501 | 2.195 | 4.843 | 0.10174 | 0.700 |
| 1.05 | -10.077 | 6.515 | 2.190 | 4.858 | 0.20117 | 0.600 |

在这三个**选定样本**内，提高 VCAS 增加 M1 的 VDS 裕量，同时 M2 裕量减少，S21/NF 变化很小而电流略增。0.85 V 的 M1 仅有约 2.3 mV 裕量，名义 DC 虽在阈值上方，但不足以推断角落/摆幅条件下可靠饱和；1.05 V 对 M1 更宽松，却仍不能宣称最佳偏置。三点不能证明连续单调性或确定最优值。表中 K 仅是 8–12 GHz 采样网格结果，不代表带外、任意源/负载端接、PVT 或实际片上稳定性。三点均固定 `not_lna_result=true`、`spec_pass=null`，不得填入论文 Table IV/V 或 pass@1。

复核命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T173201Z_e6afbeb0
python -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T164104Z_62c9f88f
python -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T173228Z_7ad352b4
python -m orfadc.experiments.summarize_teaching_cascode_bias `
  results/runs/teaching_lna/20260926T173201Z_e6afbeb0 `
  results/runs/teaching_lna/20260926T164104Z_62c9f88f `
  results/runs/teaching_lna/20260926T173228Z_7ad352b4
```

下一步若继续路线 B，应在预先定义的 DC 裕量、NF、匹配和功耗边界下选择新候选，而不是无限加密同一偏置；真正的 Stage 1 仍需授权 PDK 的 CDF/PCell 几何传播、实际无源和三级功率/增益/噪声分配。无需重跑上述三个相同参数点。
