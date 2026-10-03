# 阶段 03：OA 共源级 v2 对照候选

2026-09-26，在本地授权 Cadence 环境中另建 v2 平面 schematic，保持 v1 的连接，仅将 M1 的 `w/Wfg` 从 `10u` 改为 `40u`、漏电阻 RD 从 `500 Ω` 改为 `100 Ω`；`l=80n`、`nf=4`、`VBIAS=0.65 V`、`VDD=1.1 V`、双 50 Ω 端口及其余器件不变。这是**原理图级诊断候选**，不是论文三阶段 LNA。新 cell 的 `schCheck=(0 0)`、`dbSave=t`，14 个实例、7 个网络；网表核对 `w=40u`、`r=100`。私有原理图脚本、网表、日志和结果仅在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/`。

OCEAN 使用已实机验证的经典 Spectre + batch + 运行根目录设置。v2 运行返回码 0、ADE 成功、Spectre 0 errors/5 条既有模型 `scalefactor` warnings/4 notices。v2 PSFXL 经只读 OCEAN/`ocnPrint` 导出 47 个 0.1-20 GHz 点，并由 `extract_ocean_oa.py` 写入 `v2_extracted_20260926_01/`。为取得器件工作点，同一 OA 生成网表另作一次**独立直接 Spectre** PSFASCII 运行，0 errors/5 warnings；其结果在 `v2_direct_extracted_20260926_01/`。两个运行不能合并为一次仿真，S11/S21/S22、NF 汇总值差约 `1e-5 dB` 或更小，是交叉检查而非严格同一性。

| 0.1-20 GHz 带内指标 | v1 OCEAN | v2 OCEAN | 观察 |
| --- | ---: | ---: | --- |
| 最差 S11 (dB) | -0.00123 | -0.00221 | 仍近乎全反射 |
| 最差 S21 (dB) | -7.794 | -2.512 | 提升约 5.28 dB，宽带最差仍为负 |
| 最差 S22 (dB) | -1.716 | -2.263 | 略改善，仍差 |
| S21 ripple (dB) | 0.417 | 3.485 | 明显恶化 |
| 最差 NF (dB) | 8.746 | 4.724 | 改善；不代表噪声匹配完成 |
| 最差 NFmin (dB) | 0.213 | 0.377 | 反而升高，不能代替 NF |
| 供电电流 (mA) | 0.581 | 2.153 | 增加约 1.57 mA |
| 供电功耗 (mW) | 0.639 | 2.368 | 增加约 1.73 mW |

v2 独立 PSFASCII 的 M1 工作点：`Id≈2.153 mA`、`VGS≈0.650 V`、`VDS≈0.885 V`、`VDSAT≈0.161 V`、`gm≈18.61 mS`、`gds≈0.795 mS`，因此 `VDS−VDSAT≈0.724 V`。这只验证该偏置点有漏源电压裕量，不保证所有工艺角/温度/大信号条件。网表中面积/周长等若干寄生参数没有随本次宽度修改明显变化；须在 PDK CDF/PCell 与 netlisting 机制下单独核对几何一致性，不能据此声称版图寄生准确。基于 S12 的采样网格稳定性检查得到 v2 最小 Rollett `K≈0.031<1`，因此不能宣称无条件稳定；详见 `docs/22_stage03_ideal_match_probe.md`。

按 `Z=50(1+Sii)/(1−Sii)` 从 v2 **直接 Spectre** 的 10 GHz S 参数换算（另一端口 50 Ω 终接）：`Zin≈5.24−j520 Ω`、`Zout≈92.2−j9.2 Ω`。该频点 `|S21|≈1.114`，约 `+0.94 dB`，但不能覆盖 0.1-20 GHz 带内最差值。输入虚部若仅用理想串联电感抵消，量级约 `8.3 nH`；这一数值不包含源退化、实际 Q、寄生自谐振、稳定性和噪声约束，**不是可直接使用的片上元件设计值**。

下一受控实验应先在复制的候选上引入源退化和输入/输出匹配的有限参数组合，用 DC/SP/noise 检查 S11、正增益、NF、功耗及稳定性，再把有前景的网络落实为新的 OA schematic。真实 LNA 的压缩点、Table III 规格、5 seeds、Agent 闭环均未完成；v1/v2 `circuit_class=active_common_source_smoke`、`not_lna_result=true`、`spec_pass=null` 保持不变。
