# Stage 09: 输入梯形网络候选的同源全链失败诊断

## 来源

本报告只读聚合 `docs/73_stage09_rf_ideal_ladder_search_and_probe.md` 的唯一授权 RF 默认器件加四元件**理想**输入梯形网络 DC/SP/noise 源档，以及 `docs/89_stage09_rf_ladder_hb_diagnostic.md` 的**同一梯形网表**六点 HB 扫描。`aggregate_pdk_rf_ladder_fullchain.py` 对源档、六个单点归档及其证据清单重新审计，核对输入网络、器件偏置、端口参考阻抗、候选 ID 与原始复数 S/noise/HB，而不是拼接两份未验真的指标文件。派生报告 `results/runs/pdk_rf_ladder_fullchain/20260927T111305Z_1748e1d0/` 再从源档只读重建为 `verified_diagnostic_only`；**未新发 Spectre 仿真**。

这是从现有 OA 导出网表副本派生的理想网络，不是新的匹配网络 OA schematic。它与 `docs/88_stage09_rf_diagnostic_fullchain.md` 中**没有输入梯形网络**的默认电路不同；两份报告的压缩点、S 参数和噪声不能交叉借用。

## S1 形状的局部诊断

按 Table III 的 S1 中心频率 10 GHz、20% 相对带宽，仅从原始 8–12 GHz/161 点迹线取 **9–11 GHz/81 点**；Stage 2 的 -20 dB S11 目标作为项目本地诊断阈值，**不是** Table III 新增列。HB 压缩仍只有 10 GHz 单频，不能解释成全带大信号性能。

| 指标 | 同候选原始档重算 |
| --- | ---: |
| 9–11 GHz 最差 S11 | -6.115 dB |
| 9–11 GHz 最差 S21 | -18.869 dB |
| 9–11 GHz 最差 S22 | -0.333 dB |
| 9–11 GHz 最差 NF / NFmin | 13.413 / 12.424 dB |
| 9–11 GHz 增益纹波 | 8.585 dB |
| 10 GHz 诊断 IP1dB / OP1dB | -20.458 / -33.445 dBm |
| 供电电流 | 9.825 mA |

按当前 `fullchain_violations` 的五项数值检查，S11、增益、NF 的 violation 分别约为 **13.885、43.869、8.413 dB**，IP1dB 和电流项为 0，五项和约 66.167。该函数**不计 S22 和纹波**，不能把这个和称为论文完整 FoM；S22 与纹波本身也明显不利。结果强制 `status=unverified_score`、`pass=false`、`spec_pass=null`，即使单频诊断 IP1dB 和电流低于各自限值也不能解除其它失败。

## 门禁与下一步

每个 HB 点的 Spectre 有五条既有 `SFE-1131` 模型配置警告；输入梯形电感/电容与其它无源未证明 Q/SRF/耦合/EM/PEX/合法几何，RF 器件的 CDF/PCell 参数传播及同候选 layout/DRC 也未获资格。现有结果固定 `physical_qualification=false`、`cdf_callback_validated=false`、`model_warning_resolved=false`、`not_lna_result=true`。不能把它放进论文 Table IV/V、当作 Fig. 7 原曲线，或送入真实 `AgentToolRegistry.fullchain_eval` 充当合格候选。

下一阶段应从授权工艺可实现的**有损**输入/级间/输出网络与合法有源几何出发，建立新且明确的 OA 候选、频带/带外和角落验证、同候选 SP/noise/HB 及物理资格证据。在这些门禁之前，诊断报告只能用于排序失败原因和校验数据管线。
