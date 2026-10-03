# Stage 09：授权 RF 默认器件输入匹配的源数据约束

## 数据来源与参考平面

先分别只读重审 `docs/55_stage09_rf_default_device_probe.md` 的三级 RF 默认器件 OA/DC/SP-noise 档，以及 `docs/52_stage08_passive_quality_gate.md` 的默认 PDK 螺旋一端口档。前者的输入端口参考阻抗为 50 Ω，输出按原 SP 的 1787 Ω 参考端接；后者是另一独立一端口，不是该三级电路里的实物输入电感。源档都保留在 Git 忽略的 `results/runs/`，原始工艺网表不进入公开代码。

`src/orfadc/experiments/analyze_pdk_rf_input_match.py` 从原始 SP 的复数 S11 重算 `Zin=50(1+S11)/(1-S11)`。对当前**已经含原输入网络**的端口，在各频点只设想额外串联一个无损电感 `Ladd=-Im(Zin)/(2πf)`。这是一项代数估算，**没有新候选网表或 Spectre 运行**；测得的 S11 与估算值必须分开。

| 频率 | 源档 Zin | 各频点虚部消除所需额外理想 L | 固定 10 GHz 所需 L 后预测 S11 |
| ---: | ---: | ---: | ---: |
| 8 GHz | 106.73 - j658.09 Ω | 13.09 nH | -1.23 dB |
| 10 GHz | 115.52 - j512.04 Ω | 8.15 nH | -8.05 dB |
| 12 GHz | 113.22 - j409.64 Ω | 5.43 nH | -1.74 dB |

原电路的 S11 在 8/10/12 GHz 分别约 -0.21/-0.36/-0.54 dB。即便假设可添加 8.15 nH **理想无损**串联电感，10 GHz 输入实部仍约 115.5 Ω 而非 50 Ω，中心预测 S11 仅约 -8.05 dB；边带虚部也无法由一个固定 L 同时抵消。此推导只适用于该次 S 参数端接及未改变有源偏置/拓扑的条件，不能据此宣称任何实际匹配网络的性能。

已测默认 PDK 螺旋在 10 GHz 的一端口有效电感约 0.638 nH，8–12 GHz 最小 Q≈10.524；8.15 nH 是其约 12.77 倍，**不是**合法 PCell 选择、串接器件数或可实现版图推论。默认螺旋本身未过项目暂定 Q≥15 筛选，并有既有模型配置警告。单个样品不能代表该 PDK 的全部合法几何，也不能代替耦合系数、EM/PEX 或角落验证。

## 归档、复核与后续仿真

派生档 `results/runs/pdk_rf_input_match_estimates/20260927T045841Z_9acec9b5/` 记录三个源运行 ID/记录哈希、三频点复数阻抗、理想 L 与预测 S11；固定 `no_candidate_simulated=true`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。审计时先重新审计两份 Cadence 原始源档，再重新计算派生结果；8 个测试包含重算哈希后的虚假 -30 dB 预测和资格声明拒绝。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.analyze_pdk_rf_input_match `
  --audit-dir results/runs/pdk_rf_input_match_estimates/20260927T045841Z_9acec9b5
```

下一步不再把“调大现有 LG”当作完整输入匹配方案。先在**派生仿真网表**中设计并实跑含实部变换与多频峰值控制的受限输入网络，记录 S11/S21/NF/稳定性和实际元件数值；然后以授权 PDK 的 Q/SRF/几何及有损耦合数据筛除不可实现候选。只有重新建立可保存的用户 OA cell、同候选网表/版图/DRC 及合格 fullchain 后，才可能升级 Stage 03/09 的验收。现有代数估算不得作为 Fig. 7 或 Table IV/V 数据。
