# 阶段 03：理想匹配网络探索与稳定性警示

2026-09-26，在 v2 的 **OA 生成网表复制件**上，人工加入理想 `LS=70 pH` 源退化电感和 `LG=8.3 nH` 输入串联电感，其余实例/偏置保持 v2。此 v3 只经**直接 Spectre** 运行，不存在对应 Virtuoso schematic、片上电感 PCell、Q/自谐振或版图后仿真。网表和全部原始结果在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/v3_direct_match_probe_20260926_01/`；`source_run_kind=oa_netlist_derivative_ideal_matching_direct_spectre`、`not_lna_result=true`、`spec_pass=null`。Spectre 0 errors、5 条既有 PDK 模型警告；PSFASCII 的 DC、SP、noise 共 47 点经独立提取器解析。

v2 的 10 GHz `Zin≈5.24−j520 Ω` 是理想元件的粗略起点。v3 的 10 GHz `Zin≈36.2+j3.05 Ω`，`S11≈−15.72 dB`，`S21≈+16.62 dB`，NF 约 `0.331 dB`。**单点改善不代表宽带设计成功。**

| 统计带宽 | 关键 v3 结果 | 问题 |
| --- | --- | --- |
| 8-12 GHz | 最差 S11 `−0.605 dB`；最差 S21 `+7.45 dB`；S21 ripple `9.18 dB`；最差 NF `1.10 dB` | 中心频点很好，带边匹配差，起伏过大；带内实际采样点仅 5 个，需加密扫频。 |
| 0.1-20 GHz | 最差 S11 `−0.00222 dB`；最差 S21 `−8.55 dB`；ripple `25.17 dB`；最差 NF `10.25 dB` | 仅在窄频附近形成尖峰，宽带性能反而比 v2 差。 |

新增 `src/orfadc/cadence/stability_metrics.py`，对每个采样频点按 `Δ=S11·S22−S12·S21`、`K=(1−|S11|²−|S22|²+|Δ|²)/(2|S12·S21|)` 计算两端口无条件稳定的常用充分条件 `K>1` 且 `|Δ|<1`。当 `S12·S21=0` 时将 K 标为不可判定，不擅自判通过。对 v1/v2/v3 的独立直接 Spectre 数据重新提取，0.1-20 GHz 最小 K 分别约 `0.035`、`0.031`、`0.096`；v3 在 10 GHz 的 `K≈0.56`、`|Δ|≈0.675`。**K<1 只表示不能从该条件证明无条件稳定，不等于在当前 50 Ω 终接下已观察到振荡**；但在改变源/负载匹配前必须进一步检查稳定圆、实际端接、低频/带外范围和偏置/工艺角。

v3 的 M1 DC 工作点与 v2 基本一致，供电约 `2.153 mA`，说明当前变化主要来自理想无源网络。8.3 nH 在 10 GHz 的片上 Q、自谐振和面积没有验证，不能按理想 Spectre 元件直接映射到 PDK 电感。另有 v2 网表几何寄生字段未随宽度明显变化的疑点，仍须查 CDF/PCell。有限的加密与带外复核现已完成，发现 `LS=300 pH` 虽使 8–12 GHz 采样点 K>1，0.1–20 GHz 仍有 K<1，且匹配、ripple 不合格；详见 `docs/23_stage03_stability_cdf_followup.md`。不能把 v3 或其理想派生候选纳入论文 Table IV/V 数值比较。
