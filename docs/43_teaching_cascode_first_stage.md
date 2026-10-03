# Stage 03：公开 MOS1 cascode 首级诊断

论文三阶段 LNA 的首级是单端 cascode。这里仅在前一轮**公开人工 MOS1** 共源教学电路上串接上管 M2，测试能否保留同一输入/输出网络并改善隔离与稳定性。M1 栅偏置 0.65 V，M2 栅偏置 `VCAS=0.95 V`，两管均为 `W=300 um/L=100 nm`；仍使用理想 `LG=1 nH`、`LS=240 pH`、`LD=1.688093 nH`、`RDAMP=150 ohm` 和 `CBLOCK=225.079 fF`。`run_teaching_lna.py --topology cascode` 仅在受控模板中增加 M2 与 VCAS，默认共源拓扑的网表字节不变；它不是作者 cascode 的工艺尺寸或实际 RF 版图。

## 实机证据

两次输入均采用 8–12 GHz、`lin=160`、161 点和 50 ohm 端口。已有共源参考 `results/runs/teaching_lna/20260926T154709Z_0b5d75fe/`。cascode 首次运行 `20260926T163857Z_5ed34331` 的 Spectre DC/SP/noise 实际完成、原始文件已归档，但 Python 来源白名单尚未接受新拓扑，故该 run 保持 `result_parse_failed`；只读重提取定位问题后修复代码，不回写旧归档。新独立运行 `results/runs/teaching_lna/20260926T164104Z_62c9f88f/` 得到 Spectre 0 errors/0 warnings、161 点 PSFASCII/Touchstone、`dcOpInfo` 和清单。`audit_teaching_lna.py` 从原始文件重算通过，并重建 cascode 网表逐字节核对记录参数。

| 8–12 GHz 采样带内指标 | 共源参考 | cascode 首级 | cascode 减共源 |
| --- | ---: | ---: | ---: |
| 最差 S11 | -10.132 dB | -10.065 dB | +0.067 dB |
| 最差 S21 | 7.119 dB | 6.501 dB | -0.618 dB |
| 最差 S22 | -10.134 dB | -10.259 dB | -0.125 dB |
| 最差 NF | 1.750 dB | 2.195 dB | +0.445 dB |
| 增益纹波 | 3.322 dB | 3.628 dB | +0.306 dB |
| 电源电流 | 4.973 mA | 4.843 mA | -0.129 mA |
| 最小采样 Rollett K | 93.67 | 34042.68 | 不作线性差值解释 |

10 GHz 原始 SP S21：共源约 9.257 dB，cascode 约 8.808 dB。cascode M1 的 `VDS-VDSAT≈0.102 V`，M2 约 `0.700 V`；两管电流分别约 4.84345/4.84383 mA。外部电源支路电流取 DC `VDD_SRC:p`，内部 MOS1 `ids` 的微小差异不替代 KCL/功耗来源。以上只是一个偏置与理想匹配网络的结果，不能推论 cascode 一般降低增益或 NF，更不能据巨大 K 值声称全频、全端接稳定；未覆盖点间、带外、PVT、实际电感 Q/SRF、封装和后仿。

`summarize_teaching_cascode.py` 先只读审计两份原始运行，拒绝除新增 M2/VCAS 外的设计参数或频率网格差异，再逐频比较复数 S 和 NF/NFmin；派生报告位于 Git 忽略的 `results/runs/teaching_cascode_comparisons/20260926T164244Z_d1cfcea6/`，含两份清单 SHA-256 和各指标差，可再次只读重建。测试含设计参数错配、频率网格错配及重哈希后报告篡改反例。该 cascode 结果始终 `not_lna_result=true`、`spec_pass=null`。

## Virtuoso OA 与独立 Spectre 交叉核验

`run_teaching_oa.py --topology cascode` 在全新公开教学 OA cell 中保留上述输入及阻尼输出网络，增添 M2、0.95 V 的 VCAS 和体端接地。实际运行 `results/runs/teaching_oa/20260926T165347Z_36f2fb06/` 保存了 `schCheck=(0 0)`、22 实例/11 网络、导出网表、OCEAN/Spectre 日志、PSFXL 原始结果和 15 位文本迹线；Spectre 报 0 errors/0 warnings。网表审计确认 M1 漏极连接 M2 源极、M2 漏极连接原阻尼输出、两管体端接地。`audit_teaching_oa` 从导出数据重算 161 点和各带内指标。首次直接 Spectre 的来源白名单失败归档没有被改写或替代为成功证据。

独立直接 Spectre 归档 `20260926T164104Z_62c9f88f` 与该 OA 运行各自有证据清单。交叉审计器在检查同一参数和频率网格后，逐点比较 S11/S21/S12/S22 的**复数值**及 NF/NFmin/F/Fmin：最大频率差 0 Hz，最大复数 S 差约 `6.95e-15`，最大噪声迹线差约 `7.99e-15`，供电电流差约 `8.0e-8 mA`。可只读重建的派生报告在 `results/runs/teaching_cascode_crosschecks/20260926T170013Z_465608ec/`；原有阻尼共源交叉报告也已按旧格式只读重建通过。此核验验证本机 OA/OCEAN 导出与独立直接 Spectre 的同一公开电路小信号数据一致，不是两个独立工艺模型或实物结果的验证。

OA 此次只跑 DC/SP/noise。上文 M1/M2 `VDS-VDSAT` 数字最初由独立直接 Spectre 的 PSFASCII `dcOpInfo` 重算。后续不重跑仿真，用 `circuit/ocean/inspect_teaching_cascode_op.ocn` 只读打开**原 OA PSF** 的 `dcOpInfo`，导出两管各自的 `id/vgs/vds/vdsat/gm/gds/cgs/cgd`。15 位探针保存在 Git 忽略的 `results/runs/teaching_oa_op_probes/probe_ca055755de69/`：远端 `dcOpInfo.info` 下载件与本地 OA 源归档 SHA-256 一致，16 个 OCEAN 数值与独立直接 Spectre 对应字段最大绝对差约 `5.0e-16`。Cadence `dcOpInfo` 的 OCEAN 读取方法参考 [Cadence 技术论坛示例](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/35538/transient-and-dc-operating-point-are-different/1346278)。

在探针之后，正式 `export_teaching_mos1_oa.ocn` 与 `run_teaching_oa.py` 已增加 cascode 专用工作点导出、PSF 来源绑定、证据清单和只读审计。原 PSF 的单独重导出 `results/runs/teaching_oa_op_probes/export_b98ebeb52e91/` 先确认该正式脚本可运行；再以**同参数但新 OA cell** 做一次端到端数据通路验收 `results/runs/teaching_oa/20260926T172320Z_0661fd2f/`，生成新的 161 点和工作点归档。它与直接 Spectre 的新交叉报告 `results/runs/teaching_cascode_crosschecks/20260926T172604Z_a41dd952/` 从两份清单重建，16 个工作点字段最大绝对差约 `5.0e-16`，复数 S/noise 差仍约 `6.95e-15`/`7.99e-15`。这次重跑只验收新增导出通路，**不是新的优化样本**，不应计入样本效率。先前教学 HB 也不能改称 OA cascode 的大信号结果；尚无多阶段器件 lookup。理想电感/电容未做 Q、SRF、PVT 或后仿约束，故 Stage 03 仍 partial、Stage 09 仍无三级 schematic/fullchain。

复核和重复实验入口：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_lna `
  results/runs/teaching_lna/20260926T164104Z_62c9f88f
python -m orfadc.experiments.summarize_teaching_cascode `
  results/runs/teaching_lna/20260926T154709Z_0b5d75fe `
  results/runs/teaching_lna/20260926T164104Z_62c9f88f
python -m orfadc.experiments.run_teaching_lna --topology cascode --vcas-v 0.95 `
  --ldd-nh 1.68809309279457 --cblock-ff 225.079079039277 --rdamp-ohm 150 `
  --sp-start-ghz 8 --sp-stop-ghz 12 --sp-intervals 160
python -m orfadc.experiments.audit_teaching_oa `
  results/runs/teaching_oa/20260926T172320Z_0661fd2f
python -m orfadc.experiments.audit_teaching_damped_crosscheck `
  results/runs/teaching_oa/20260926T172320Z_0661fd2f `
  results/runs/teaching_lna/20260926T164104Z_62c9f88f `
  --output-root results/runs/teaching_cascode_crosschecks
python -m orfadc.experiments.run_teaching_oa --topology cascode `
  --schematic-context /opt/eda/cadence/IC251/tools.lnx86/dfII/etc/context/64bit/schematic.cxt
```

下一步用受控偏置/输出网络扫描验证 cascode 的资源分配折中；论文后两级差分共源、中和电容、MCR、1787 ohm || 62 fF 负载和合格 fullchain 尚未实现。授权 PDK 的 CDF/PCell 几何传播门槛独立存在，不会被本次公开 MOS1 结果解除。
