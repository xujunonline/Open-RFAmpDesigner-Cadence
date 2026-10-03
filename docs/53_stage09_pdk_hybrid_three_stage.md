# Stage 09：授权 PDK 有源器件与理想无源三级诊断

## 范围与证据等级

本机授权 Cadence 环境中，在**用户设计库**新建六管三级 OA schematic：首级单端 cascode，第二、三级差分共源，三级之间及输出端使用理想互感、电感、电容和电阻。输入端口为 50 Ω，输出为 1787 Ω 差分端口并联 62 fF。它用于检查 Virtuoso schematic → Spectre netlist → DC/工作点/SP/noise → Python 审计的数据链，**不是论文 TSMC N65 电路，也不是合格 LNA**。模型、私有 OA cell、原始 PDK 网表、日志及伴随文件仅保存在本机 Git 忽略目录，不进入公开仓库或外部模型上下文。

首次和第二次新 cell 均因 MOS 端子引线相交而 `schCheck=(6 0)`，未生成可接受 netlist；失败产物原样保留。第三个新 cell 将 MOS 的 D/G/S/B 引线按符号真实端子方向独立引出，`schCheck=(0 0)`、`dbSave=t`，58 个 OA 实例、26 个网，`createNetlist` 完成且 netlisting 报 0 errors/0 warnings。生成的 Spectre 网表含六个授权 PDK MOS、三个理想 `mutual_inductor`、四个交叉中和电容。直接给 OA 实例写入宽度/指数字符串属性，**没有执行并验收 CDF callback 或 PCell 几何合法性**；网表宽度只是当前导出值，不能从中推断合法布局尺寸。

第一次直接 Spectre 作业实际完成 DC/SP/noise，但包装文件未请求 `oppoint` 导出，因而没有 `dcOpInfo.info`；归档状态保持 `simulation_or_download_failed`，不回填为成功。另起作业在 wrapper 中加入 `dcOpInfo info what=oppoint where=rawfile` 后，Spectre 25.1 返回 0 errors/5 warnings，产生 `dcOp.dc`、`dcOpInfo.info`、161 点 `sp.sp`/`sp.noise.sp` 和混合参考阻抗 S2P。五条警告均为已授权模型加载时的 `SFE-1131` 重复配置，应由 PDK/仿真环境负责人核对；不能称零警告。

## 独立审计结论

成功原始档案在本机私有路径 `results/runs/pdk_three_stage_fixed/20260926T221516Z_d20bd475/`；前次缺工作点的失败档案为 `20260926T221117Z_952b8087/`。`src/orfadc/experiments/audit_pdk_hybrid_three_stage.py` 从原始文件独立重算 161 行数据，并核验：

- OA 网表在运行前后 SHA-256 不变，下载的远端网表及 wrapper 与运行前快照逐字节一致；证据清单覆盖原始文件和标准化输出。
- 六个 BSIM4 工作点的 `Ids/gm/gds/VGS/VDS/VDSAT` 有效，`VDS>VDSAT`；M1/M2 电流一致，M2 至 M6 电流和与供电电流一致。这里的工作区判断仅限这次 DC 解，不证明 GHz 大信号、角落或版图有效。
- PSFASCII 与 Touchstone 的四个复数 S 参数逐点核对，最大差约 `2.30e-16`；NF/NFmin 的 dB 与 F/Fmin 的线性因子逐点一致。S2P 端口参考为输入 50 Ω、输出 1787 Ω，S21 不可当成 50→50 增益。
- 带内 8–12 GHz/161 点：最差 S11 约 `-0.035 dB`、最差 S21 约 `-58.680 dB`、最差 S22 约 `-0.172 dB`、增益纹波约 `14.876 dB`、最差 NF 约 `46.848 dB`、最差 NFmin 约 `29.034 dB`；供电约 `3.210 mA`、`3.531 mW`。数值是此**失败诊断电路**的实测值，不能填入论文 Table IV/V。
- 当前网格的最小 Rollett K 约 `1.47e6`，最大 `|Δ|` 约 `0.976`。这只说明该 161 点、理想无源、极低传输条件下的采样判据；不证明带外、功率、角落或实际版图无条件稳定。

报告必须保持 `not_lna_result=true`、`spec_pass=null`、`physical_qualification=false`、`cdf_callback_validated=false`。S11/S21/NF 已显著偏离 LNA 目标，不能因完整数据链、工作点或 sampled K 通过就宣称 Stage 09 完成。当前也没有此 PDK 三级的 HB/P1dB，同一次运行不是 fullchain。

## 级间衰减定位

在**相同 OA netlist**外部加一个并联于输入节点的理想 1 V AC 电压源，另起 8–12 GHz/161 点 Spectre AC 内部节点探针。该源会改变端口激励与源阻抗条件，因此下面是各内部节点的**电压传递比**，不是 S21，也不得与上段 dB 数值相加比较。10 GHz 原始复数节点电压计算为：

| 路径 | 10 GHz 电压比 |
| --- | ---: |
| 输入 → 首级输出 `d1` | -7.287 dB |
| `d1` → 第二级差分栅极 | -9.063 dB |
| 第二级差分栅极 → 第二级差分漏极 | -2.873 dB |
| 第二级差分漏极 → 第三级差分栅极 | -6.779 dB |
| 第三级差分栅极 → 第三级差分漏极 | -3.722 dB |
| 第三级差分漏极 → 输出差分端口 | -5.055 dB |
| 输入 → 输出差分端口，总电压比 | -34.778 dB |

衰减分布在首级、两个级间耦合、后级有源段和输出耦合，而非单一参考阻抗换算错误。只有一组 10 GHz AC 线性化工作点，不能据此直接确定每个无源值该如何调，也不能推断改变 CDF 几何后的趋势。完整 161 点 `ac.ac`、源网表/远端快照、运行日志、CSV、metrics 和清单在 Git 忽略路径 `results/runs/pdk_three_stage_fixed/ac_probe_20260926T223621Z_8c0ec8d8/`；独立审计器为 `src/orfadc/experiments/audit_pdk_hybrid_ac_probe.py`。

## 复核与下一门槛

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_hybrid_three_stage `
  results/runs/pdk_three_stage_fixed/20260926T221516Z_d20bd475
python -m orfadc.experiments.audit_pdk_hybrid_ac_probe `
  results/runs/pdk_three_stage_fixed/ac_probe_20260926T223621Z_8c0ec8d8
python -m pytest tests/test_pdk_hybrid_three_stage.py tests/test_pdk_hybrid_ac_probe.py -q
```

下一步先在授权环境中诊断三级的级间电压/电流传输和低 S21 的原因，并独立核验 MOS 参数经过 CDF/PCell 后的实际几何与工艺约束；再做受限无源 Q/SRF、耦合、宽带匹配与稳定性设计。只有在同一合格候选的 DC/SP/noise/压缩点、全频稳定性与文件来源全部通过后，才可调用 LNA fullchain 规格评估。不能用本次理想无源三级或此前公开 MOS1 教学三级替代该门槛。
