# 阶段 03 路线 B：Spectre MOS1 教学电路诊断

2026-09-26。此节记录仓库内公开的 `circuit/spectre/teaching_mos1_lna.scs` 与**人为设定**的 Spectre MOS1 参数所构成的直接网表路线，验证无 PDK 情况下的 DC、S 参数、SP-noise、HB、原始数据提取和归档。后续另建的公开 Virtuoso OA schematic/OCEAN 闭环见 `docs/38_stage03_public_oa_closed_loop.md`，不应与本节的直接网表运行混为同一实验。两者都不是 TSMC/其他工艺模型或论文三级宽带 LNA；路线 A 的 PDK CDF/PCell 几何传播、可实现匹配及合格 LNA 门槛不因路线 B 通过而关闭。

## 电路、运行与证据

- 单管共源、源退化理想电感、输入串联理想电感、漏极理想电感、输入/输出隔直电容及两个 50 Ω 端口；独立 Spectre 模型写在网表中，没有 `include`/PDK。MOS1 是教学级 Shichman-Hodges 模型，**不能**据此估计真实 10 GHz 工艺性能。
- `run_teaching_lna.py` 仅允许此仓库固定网表、`VBIAS=0.50..0.70 V`，先过宿主 2.66 GiB 可用物理内存门禁，再以 SSH 运行 Spectre 25.1。每个独占目录保存网表、日志、DC/SP/noise PSFASCII、Touchstone、CSV、metrics 和 SHA-256 清单。0-error/0-warning 日志才产生指标；有告警时仍归档原始文件，但状态为 `model_validity_warning`，不提供指标。
- `audit_teaching_lna.py` 只读核对清单、记录的偏置与网表/DC、0-warning 日志、PSFASCII 重算指标、CSV 及 Touchstone 复数 S 参数。SHA-256 是内部一致性检查，不是防有权限者整体重写的签名。
- 新版网表增加 `dcOpInfo info what=oppoint where=rawfile`；新归档还核对 `M1` 的 `Id/VGS/VDS/gm/gds/Cgs/Cgd` 与 DC。四个有该文件的新 run 导出固定 W/L 的单器件教学表征 CSV，详情见 `docs/30_stage06_lookup_contract.md`；它不等于三级 `active_sizing` lookup。旧归档没有 `dcOpInfo.info`，只按原有原始数据契约审计，不回填工作点字段。
- `run_teaching_hb.py` 的 50 Ω 输出端作为真实负载；用 HB 基波峰值相量计算 `Re(V1*conj(I1))/2`，并与同次 SP 精确频点的 S21 比较。HB 基频被限定在 0.1 GHz 的 SP 网格上。HB 结果若有 Spectre 告警，不能用于压缩点。
- `audit_teaching_hb.py` 只读检查每个成功 HB 点的证据清单、输入音调/偏置/50 Ω 输出端、0-warning 日志，从原始 HB/SP 重算基波功率和小信号 S21，再与归档指标逐字段比较；新旧 -50 dBm 点均通过。旧点缺少 `vbias_v` 元数据时仅允许该旧网表固定的 0.65 V，不能为新版点推断偏置。

只读审核命令（原始归档在 Git 忽略目录）：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T125521Z_924925d3
py -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T125529Z_403c64b4
py -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T125404Z_7ed0e9c8
py -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260926T125538Z_cc3e6f49
py -m orfadc.experiments.audit_teaching_hb results/runs/teaching_hb/20260926T130005Z_d4c61b78
```

新的受限运行入口：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.run_teaching_lna --vbias-v 0.65
py -m orfadc.experiments.run_teaching_hb --input-dbm -50 --vbias-v 0.65
py -m orfadc.experiments.run_teaching_hb_sweep --vbias-v 0.65 --powers-dbm -60 -50 -40 -20 -10 -5 0
py -m orfadc.experiments.summarize_teaching_bias `
  results/runs/teaching_lna/20260926T125521Z_924925d3 `
  results/runs/teaching_lna/20260926T125529Z_403c64b4 `
  results/runs/teaching_lna/20260926T125404Z_7ed0e9c8 `
  results/runs/teaching_lna/20260926T125538Z_cc3e6f49
```

不要用这些命令循环创建无意义归档；先确认 VM 资源、模型告警和实验目的。

## 实测与边界

下表为 8–12 GHz 自定义诊断频带的**采样带内最差值**，不是论文 Table III 规格评估。四个含工作点的偏置 run 使用同一含精确 10 GHz 的 200 点 SP 网格，原始数据经 `summarize_teaching_bias.py` 审计后汇总于 `results/runs/teaching_bias_summaries/20260926T130033Z_4a3ec4a1/`；其 CSV/JSON/清单不包含商业模型。首次 0.65 V 成功 run `20260926T122913Z_44d6a4da` 使用旧 101 点网格；增加工作点分析之前的 200 点归档也保留但不混入下表。

| 偏置 | 归档 run_id | S11 最差 dB | S21 最差 dB | S22 最差 dB | NF 最差 dB | 电流 mA | 采样点 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.50 V | `20260926T125521Z_924925d3` | -3.113 | -0.266 | -0.006 | 3.440 | 0.311 | 200 |
| 0.55 V | `20260926T125529Z_403c64b4` | -6.101 | 4.429 | -0.018 | 2.054 | 1.243 | 200 |
| 0.65 V | `20260926T125404Z_7ed0e9c8` | -10.179 | 8.204 | -0.055 | 1.151 | 4.973 | 200 |
| 0.70 V | `20260926T125538Z_cc3e6f49` | -10.427 | 9.183 | -0.076 | 0.945 | 7.770 | 200 |

这些点日志均为 0 errors/0 warnings，200 点 PSFASCII、CSV 和 Touchstone 审计通过。趋势符合该教学模型中提高偏置使电流与小信号增益上升、噪声系数下降的现象，但既不能迁移为 PDK 数值，也不能宣称满足论文增益、输出匹配、纹波或稳定性要求。旧 0.65 V 数据只读审计通过；其 0.1–20 GHz 采样 K 最小约 1.000007，仅是离散网格现象，不能据此证明无条件稳定。汇总清单证明 CSV/JSON 内部一致，引用的源清单摘要便于追溯；它不是对整个实验档案的数字签名。

10 GHz、-50 dBm、7 谐波的 0.65 V 单点 `20260926T123325Z_09007e7e` 给出输出约 -39.9213 dBm、功率增益 10.078732 dB；与同次 S21 10.078738 dB 相差约 -0.000006 dB，50 Ω 电压/电流交叉核对通过。最初的 0.65 V 七点扫描 `20260926T123436Z_26675574` 在添加模型告警门禁**之前**生成，0 dBm 点有严重 CMI 告警；其 `unbracketed` 摘要不能视作有效高功率曲线或压缩点。后续单点 `20260926T123653Z_32ff33c7` 将 0 dBm 正确标为 `model_validity_warning`，不输出指标。

加工作点分析后的 -50 dBm 新单点 `20260926T130005Z_d4c61b78` 再次得到 10.078732 dB 功率增益、HB 与 SP 相差约 `-6.4e-6 dB`，并将 `dcOpInfo.info` 连同 HB 原始数据纳入清单；它仍只是低功率交叉核验。

0.50 V 的新扫描 `20260926T124255Z_fd2e7223` 在 -60/-50/-40 dBm 完成 3 点，到 -20 dBm 出现 `CMI-2139/2144/2375/2377`，状态 `incomplete`、`compression=null`，未再运行 -10/-5/0 dBm。告警涉及结电流模型限值及氧化层电压，Spectre 明示结果可能不准确；即使某些警告只在 HB 迭代过程中出现，也必须在核明物理状态与模型适用性前拒绝该功率点。不得为凑出 IP1dB 而调高模型破坏电压或删掉警告。

## 下一门槛

1. 在有授权 PDK/Virtuoso 的交互环境核实 CDF 初始化、参数回调、实例属性和 netlist 几何一致性，勿重试已失败的无图形写入方式。
2. 选择能实现的输入/输出匹配和器件拓扑；在足够宽的带内/带外网格检查稳定性、S 参数、NF 与功耗。
3. 仅在模型有效、低功率 HB/SP 一致、压缩交点被实际功率点夹住且谐波/步长收敛后报告 LNA IP1dB/OP1dB；此前 `spec_pass=null`，不能填写论文 Table IV/V。
