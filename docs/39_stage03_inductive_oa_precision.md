# Stage 03：源退化教学 OA 电路与 OCEAN 精度复核

## 本次新增的电路证据

路线 B 在原公开 MOS1 平面测试台之外，新建**独立** Virtuoso OA cell：`M1` 单管共源、50 Ω 输入/输出端口、输入隔直电容 5 pF、串联 `LG=1 nH`、栅偏置 0.65 V/100 kΩ、源退化 `LS=240 pH`、漏极 `LD=2 nH`、输出隔直电容 5 pF、电源 1.2 V。MOS1 的体端仍接地，源端经 `LS` 接地。拓扑取自本项目公开的直接 Spectre 教学网表，不来自论文作者的三级 LNA；L/C 均为理想元件，未证明片上 Q、自谐振或实现性。

可重建脚本为 `circuit/ocean/create_teaching_inductive_mos1_oa.ocn`，运行和导出复用 `run_teaching_mos1_oa.ocn`、`export_teaching_mos1_oa.ocn`。Python 入口加 `--topology inductive`，仍只接受仓库内固定脚本/模型、独占 cell 和运行目录，先过 2.66 GiB 宿主可用物理内存门禁。新 cell 的 `schCheck=(0 0)`、OA 生成网表、Spectre 0 errors/0 warnings、DC/SP-noise、47 点 PSFXL 导出和源文件清单均通过 `audit_teaching_oa`。审计器逐节点检查 `M1`、`LG/LS/LD`、端口、偏置及体端，不能仅靠器件名通过。

两条主要实机归档都在 Git 忽略目录：

| 归档 | 作用 | 结论 |
| --- | --- | --- |
| `results/runs/teaching_oa/20260926T144605Z_275c80ae/` | 首次电感 OA cell，旧六位 `ocnPrint` 导出；其 `high_precision_export/` 是**同一 Spectre 结果**的 15 位重导出，`direct_check/` 是同一 OA 网表的独立直接 Spectre PSFASCII 执行 | 三条来源分别保留，均不标 LNA pass；低精度 K 不可信 |
| `results/runs/teaching_oa/20260926T145835Z_23dab014/` | 更新后自动入口在另一个独立 OA cell 上默认导出 15 位 | 47 点、九项指标和采样 K 与高精度重导出相同；是新的单次 Spectre 运行 |

本机重跑命令（`schematic.cxt` 路径须按获授权主机实际安装位置填写）：

```powershell
$env:PYTHONPATH='src'
$context = Read-Host '授权 Cadence 主机上 schematic.cxt 的绝对路径'
py -m orfadc.experiments.run_teaching_oa --schematic-context $context --topology inductive
py -m orfadc.experiments.audit_teaching_oa results/runs/teaching_oa/20260926T145835Z_23dab014
py -m orfadc.experiments.audit_teaching_oa_crosscheck `
  results/runs/teaching_oa/20260926T144605Z_275c80ae/high_precision_export `
  results/runs/teaching_oa/20260926T144605Z_275c80ae/direct_check
```

## 为什么不能用六位 S 参数判断 K

Rollett 因子 `K=(1-|S11|²-|S22|²+|Δ|²)/(2|S12·S21|)`，`Δ=S11·S22-S12·S21`。该教学候选恰好在 K≈1 的边界附近；分子、分母的微小舍入会放大到 K。旧 OCEAN `ocnPrint` 默认 6 位有效数字：复数 S 与独立 PSFASCII 最大绝对差仅约 `5.13e-6`，但由旧导出计算的最小 K 约 `-7.021`。因此**不能**把这个 K 当成电路真实不稳定的证据。

[Cadence 官方社区引用的 OCEAN 手册](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/48506/how-to-get-values-of-sampling-points/1376994)列出 `ocnPrint` 的 `?precision`（默认 6）和 `?width` 选项；[Cadence 工程师说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/27297/how-to-increase-the-number-resolution-shown-by-ocean)指出可提高有效数字。当前导出模板采用 `aelPushSignifDigits(15)` 和 `?precision 15 ?width 24`，**本机实测**复数 S 与直接 PSFASCII 最大绝对差约 `7.23e-15`，NF 最大差约 `5.11e-15 dB`，频率最大差约 `3.81e-5 Hz`；两条独立路径算得的最小 K 都约 `1.00000748`。跨运行比较摘要为 `results/runs/teaching_oa/20260926T144605Z_275c80ae/crosscheck.json`，保存两份源清单 SHA-256 和逐频最大差；`audit_teaching_oa_crosscheck` 可只读重算。

这个修正**只改变数据导出精度，不是电路参数优化**。项目在 `metrics.json` 中记录 `ocn_precision_digits` 和 `stability_quality`：旧六位迹线为 `insufficient_export_precision`；高精度 K 虽在 47 点网格上略大于 1，仍为 `near_boundary_on_sampled_grid`。离散点不覆盖点间、带外、PVT、寄生、实际负载和大信号条件，也不能用于稳定性签核或论文 Fig. 7 判定。

## 性能、限制和下一步

高精度 OA 运行的自定义 8–12 GHz 频带仅有 **5 个采样点**：最差 S11 约 -10.521 dB、最差 S21 约 +8.177 dB、最差 S22 约 -0.0547 dB、最大 NF 约 1.188 dB、NFmin 约 0.0896 dB、ripple 约 3.286 dB、电源电流约 4.973 mA。它与旧直接 Spectre 教学电路的 200 点带内统计不能逐值当作同频率网格比较。输出匹配显然不足；输入匹配也未达到先前自定 -20 dB 教学目标。所有归档保持 `not_lna_result=true`、`spec_pass=null`。

下一步优先在**授权 PDK 的交互式 Virtuoso 环境**核对 CDF/PCell 宽度及寄生参数传播，再把可实现的输入/输出网络、宽带和带外稳定性、功耗、NF、压缩点接成真正 LNA 候选后端。公开 MOS1 电感 cell 可以继续用于工具/agent 接口教学，但不能填论文 Table IV/V 或作为 Stage 09 三级全链完成证据。
