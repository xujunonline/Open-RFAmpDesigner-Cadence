# Stage 09：首级理想耦合系数单因子敏感性

## 实验问题

授权 PDK 六管加理想无源三级诊断在 8–12 GHz 的最差 S21 约 -58.68 dB。内部 AC 探针显示 10 GHz 首级输出到第二级差分栅极约 -9.06 dB。为区分级间耦合损耗与后级增益问题，只对理想互感 `K12` 做一次单因子变化。本实验**不是**论文的物理 MCR 设计，也不是合格 LNA 参数优化。

基线为 `docs/53_stage09_pdk_hybrid_three_stage.md` 中已审计的 Virtuoso OA 网表。新运行使用该 OA 网表的私有副本，仅将 `K12` 的 `coupling=0.45` 改为 `0.8`；它是**直接 Spectre 派生网表**，不是新的 Virtuoso schematic，也没有 PDK 几何回调。其余六管、偏置、无源值、50 Ω 输入与 1787 Ω || 62 fF 差分输出不变。`K12=0.8` 未经物理变压器、版图、EM、Q、SRF 或工艺角验证。

## 真实运行与审计

运行前检查 SSH、Spectre、VMware Tools 及宿主可用物理内存；源 OA 网表 SHA-256 前后相同。派生网表、ADE 伴随文件和 SP/AC 两个 wrapper 均上传后逐字节回读。SP wrapper 做 DC、六管工作点、8–12 GHz/161 点混合参考阻抗 SP/noise；AC wrapper 独立添加并联理想 1 V 输入源，只用于内部节点电压比，**不用于 S 参数或噪声计算**。两次 Spectre 各为 0 errors、5 条既有 `SFE-1131` 模型配置警告。

私有原始档案为 `results/runs/pdk_three_stage_fixed/k12_0p8_20260926T225054Z_1f400b40/`。`src/orfadc/experiments/audit_pdk_k12_sensitivity.py` 首先独立复核两个基线档案，再强制检查派生网表与 OA 源**恰好一处** K12 字符串变化、ADE 伴随文件相同、远端回读一致、日志告警类型、六管 DC 工作点与供电 KCL。161 点四个复数 S 参数对 Touchstone 最大差约 `2.48e-16`；NF/NFmin 的 dB 与 F/Fmin 逐点换算一致；SP/AC 扫频网格一致。CSV、metrics.json 和原始文件由 SHA-256 清单绑定，可只读重审。

| 指标 | OA 基线，K12=0.45 | 单因子派生，K12=0.8 | 解释 |
| --- | ---: | ---: | --- |
| 10 GHz S21 | -44.319 dB | -39.460 dB | 改善约 4.860 dB；混合参考端口 S21 |
| 8–12 GHz 最差 S21 | -58.680 dB | -53.932 dB | 仍严重不合格 |
| 8–12 GHz 最差 NF | 46.848 dB | 42.104 dB | 仍严重不合格 |
| 10 GHz 首级耦合电压比 | -9.063 dB | -4.146 dB | 改善约 4.917 dB；不是 S21 |
| 10 GHz 输入到输出总电压比 | -34.778 dB | -29.918 dB | AC 外加理想源条件下改善约 4.860 dB |
| 供电电流 | 3.210 mA | 3.210 mA | DC 偏置保持一致 |

这个一因素对照表明首级理想耦合影响传输和噪声结果。它**不证明** `k=0.8` 在授权工艺中可实现，也不说明单靠提高耦合就能让设计通过输入/输出匹配、增益、纹波、NF、线性度或稳定性门禁。电压比是在并联理想 AC 源条件下测得，不能与 S21 当成同一种增益。派生运行始终 `not_lna_result=true`、`spec_pass=null`、`physical_qualification=false`、`cdf_callback_validated=false`；没有此 PDK 三级的 HB/P1dB。

## 可重审命令与下一步

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_k12_sensitivity `
  results/runs/pdk_three_stage_fixed/k12_0p8_20260926T225054Z_1f400b40 `
  --baseline-sp results/runs/pdk_three_stage_fixed/20260926T221516Z_d20bd475 `
  --baseline-ac results/runs/pdk_three_stage_fixed/ac_probe_20260926T223621Z_8c0ec8d8
python -m pytest tests/test_pdk_k12_sensitivity.py -q
```

下一门槛是：在授权环境用新设计单元核清 MOS CDF/PCell 参数与生成几何，再建立有实际损耗与频率依赖的耦合器件模型，测其 Q、k、SRF、面积和角落；随后才可以对可实现的级间和输入/输出匹配做受控搜索，并在同一候选上执行 SP/noise/大信号压缩点。当前虚拟机只观察到登录界面的 Xorg，没有已就绪的用户 Virtuoso 图形会话；不重复此前失败的无图形 `vfoSetParam` 路径。若暂时无法做交互式 CDF 核验，阶段 03/09 的工艺几何门禁保持未通过，其他纯 Python 和公开教学路径可独立继续。
