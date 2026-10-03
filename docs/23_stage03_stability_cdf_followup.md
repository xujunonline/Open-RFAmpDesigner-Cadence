# 阶段 03：S12 来源复核、加密扫频与 CDF 边界

2026-09-26 的本轮工作延续 `docs/22_stage03_ideal_match_probe.md`。所有含工艺模型、OA 数据、网表和原始日志的产物均留在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/`；下列数值是本地诊断结果，不是论文原始结果或已验收的 LNA 性能。

## OCEAN 路径的 S12 与稳定性

在不重跑 v1/v2 仿真的前提下，分别只读打开原有 PSFXL，按原运行逐一导出复数 S12。新文件与各自原有 S11/S21/S22、NF/NFmin、F/Fmin 导出合并在**新目录** `v1_export_with_s12_20260926_01/`、`v2_export_with_s12_20260926_01/`，原目录未覆盖。OCEAN 导出任务 `export_v1_v2_s12_20260926_01/` 返回成功；两个新目录各有 47 点。Python 解析器现要求 S12 的实部、虚部同时存在，所有曲线的频率网格及 `?resultsDir` 来源一致；含 S12 时若无显式 `resultsDir` 也拒绝。不同运行不能仅因频率相同就拼接。六位有效数字的 `ocnPrint` 输出会放大 K 计算中的消差误差。

| 原 OA 候选 | OCEAN 最小 K | 独立直接 Spectre 最小 K | OCEAN 最大 `|Delta|` | 采样网格无条件稳定 |
| --- | ---: | ---: | ---: | --- |
| v1 | 0.035106 | 0.035044 | 0.820632 | 否 |
| v2 | 0.030453 | 0.030521 | 0.770323 | 否 |

两路径 S12 的逐点复数最大绝对差约 `5e-8`；K 的小差异与输出精度/数值消差一致，但不能据此断言原始波形严格相同。`v1_ocean_extracted_stability_20260926_01/`、`v2_ocean_extracted_stability_20260926_01/` 保留新提取结果。两路径是独立运行，不能互相借用稳定性字段。`K<1` 只表示此充分条件无法证明任意被动源/负载下的无条件稳定，不等于已观察到 50 Ω 端接振荡。

## 理想网络加密扫频

基于 v2 的 OA 网表**复制件**，保持理想输入串联电感 `LG=8.3 nH`，仅改变理想源退化电感 `LS`。三次直接 Spectre 运行均有 DC、SP/noise、0 errors 和既有的 5 条模型警告；8–12 GHz 每次实际导出 202 点。`v3_dense_8_12_20260926_01/` 是 `LS=70 pH` 加密复核，另两次位于 `direct_ls150_dense_20260926_01/`、`direct_ls300_dense_20260926_01/`。下表的最差值均是该频带的采样结果，稳定性也仅指该网格。

| LS | 最差 S11 dB | 最差 S21 dB | S21 ripple dB | 最差 NF dB | 最小 K | 最大 `|Delta|` | 带内 K/Delta 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 70 pH | -0.557 | 7.221 | 9.459 | 1.100 | 0.450 | 0.726 | 不通过 |
| 150 pH | -1.028 | 6.599 | 7.123 | 1.128 | 0.900 | 0.556 | 不通过 |
| 300 pH | -1.567 | 5.353 | 4.609 | 1.234 | 1.688 | 0.432 | 仅带内采样点通过 |

对 `LS=300 pH` 的**同一参数、独立 0.1–20 GHz 粗网格**复核存于 `direct_ls300_wide_20260926_01/`，47 点、0 errors、5 warnings：最小 K `0.191`（约 0.447 GHz），最大 `|Delta|=0.770`，最差 S11 `-0.00226 dB`，最差 S21 `-8.403 dB`，S21 ripple `18.251 dB`，最差 NF `10.125 dB`。因此带内 K>1 **不能**推出带外稳定；该候选的输入匹配和宽带指标亦明显失败。粗网格仍可能漏掉带外尖峰，不能作全频、工艺角或温度签核。理想 8.3 nH 电感的 Q、自谐振、面积与可实现性均未验证，不能称作片上网络或正式 LNA 结果。

## CDF/PCell 诊断未闭环

对现有 v1/v2 OA 实例作只读 CDF/实例属性查询：两者的 W/Wfg 不同，其余若干几何寄生属性在导出网表中仍保持相同的默认值；查询同时显示相关 CDF callback 存在。这提示早前用 `dbCreateProp` 写参数的脚本**可能**绕开 callback，但无法仅凭这些输出确定正确的工艺几何值。[Cadence 社区关于程序化修改与 callback 的说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/30812/ultra-pcell-with-dbcreateparaminstbymastername)以及 [`vfoSetParam` 讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/56702/modify-pcell-parameter-due-to-skill-code/1388201)提供的是通用线索，并非此 PDK 的授权参数手册。

为验证 callback 路径曾尝试在**新名称** OA cell 上调用 `vfoSetParam`，任务 `create_flat_tb_v2_cdfprobe_20260926_01/` 因显示连接 I/O 错误中止，报告未生成；该新 cell 的 schematic 文件为空且有锁文件。不能判定 callback 已执行、也不能将此实验视作修复。不要覆盖、复用或删除失败 cell；先由授权管理员确认图形/Xvfb 会话、工艺 CDF 的安全编程接口，并在另一个新 cell 上按资源门禁作最小化验证。之后对宽度、指宽、结面积/周长、源漏电阻与生成网表逐项核对，才允许把尺寸扫描结果作为工艺有效的候选。

## 下一步验收门槛

1. 授权环境内解决 CDF 参数传播疑点：新 cell 的 callback/实例属性/网表互相一致，保留失败与成功日志；不得自行推导并写入商业工艺几何常数。
2. 先定义可实现的输入/输出网络约束和参考平面，再按目标带、低频及更高频、稠密网格检查 S11/S21/NF/K/Delta；必要时分析稳定圆、实际端接、偏置及工艺角。K/Delta 只是小信号二端口门禁。
3. 找到通过上述门禁的候选后，才建新的 OA LNA cell 并执行 OCEAN DC/SP/noise，再补 Cadence 大信号压缩点及完整 spec/candidate/seed/timeout 记录。在这之前阶段 03 仍是 partial，不生成 Table IV/V 的可比数值。
