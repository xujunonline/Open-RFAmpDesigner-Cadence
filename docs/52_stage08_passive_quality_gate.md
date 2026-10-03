# Stage 08：一端口无源 Q/SRF 数据门禁

## 三层证据，不可混用

1. **公开 RLC 校准**：`circuit/spectre/teaching_inductor_quality.scs` 是 2 Ω 串联损耗、1 nH 理想电感和 100 fF 并联寄生的一端口教学模型。Cadence Spectre 在 0.5–30 GHz 的 591 点 SP 输出，经 PSFASCII/S1P 复数 S11 交叉核对及解析阻抗比较；审计档案在 Git 忽略的 `results/runs/passive_quality_reference/20260926T203114Z_60899fd6/`。解析阻抗最大相对差约 `3.82e-13`，PSF/S1P 最大复数差约 `2.48e-16`。8–12 GHz 最小 Q 约 `16.25`，模型自谐振约 `15.913 GHz`。这些数值**不是 PDK 电感**。
2. **授权 PDK 默认实例**：仅在本机获授权的工艺环境中，只读枚举螺旋器件的 CDF、引脚与 view，再在专用用户设计库建立一个**默认参数**一端口 OA schematic。`schCheck=(0 0)`，导出网表显示一个三端 PDK 螺旋器件：正端接 50 Ω PORT1，负端和衬底端接地。未修改 PDK 库、模型或 CDF，也未执行几何回调。该 OA 网表由独立控制文件追加 0.5–30 GHz/591 点 SP 后直接交 Spectre。前后源网表 SHA-256 相同，远端网表和控制文件回读与本地逐字节一致；原始运行、伴随 ADE 文件、日志、PSFASCII、CSV、指标和哈希清单留在 Git 忽略的 `results/runs/passive_quality_reference/20260926T205333Z_b96aea29/`。第一次未带完整来源快照的探针 `20260926T204943Z_b1870ec3` 单独保留，不冒充完全审计通过的档案。
3. **单点宽度属性敏感性**：CDF 只读检查显示 `w`、`nr`、`rad` 等参数存在回调，但没有直接暴露低/高值。另建全新用户库 OA 诊断 cell，给电感实例直接加字符串属性 `w=7u`，**未调用 CDF 回调**。`schCheck=(0 0)` 并成功网表化；与默认实例比较，除生成注释外仅电感行 `w=6u→7u`。同样的独立 591 点 Spectre SP 运行及文件哈希归档在 `results/runs/passive_quality_reference/20260926T211116Z_4bb251a3/`。两份源档各自重建并配对核验：频点一致，最大复数 S11 差约 `0.04082`。这只证明 OA 属性传到 netlist、模型对该参数敏感，不证明该属性已由 PDK 回调认可、PCell/layout 可实现或符合工艺规则。

一端口计算使用 `Z=50(1+S11)/(1-S11)`、`Q=Im(Z)/Re(Z)`、`Leff=Im(Z)/(2πf)`；自谐振只在扫频数据中寻找 `Im(Z)` 从正到非正的首次过零。Python 实现和拒绝条件见 `src/orfadc/cadence/passive_quality.py`；独立原始数据重建见 `src/orfadc/experiments/audit_pdk_inductor_oneport.py`。项目暂用 **Q≥15 且 SRF≥1.2×12 GHz** 的教学筛选阈值，它既不是论文 Table II 的参数，也不是该 PDK 的器件保证值。

## 默认 PDK 实例的实测结论

默认实例的第二次 Spectre 运行完成，**0 errors、5 warnings**；5 条均为 `SFE-1131`，涉及模型配置中的重复 `scalefactor`，最终值由最后一处定义决定。需要工艺/仿真环境负责人核实此模型配置，不能将“0 errors”写作“0 warnings”。591 点原始 S11 重算得到：8–12 GHz 最小一端口 Q 约 `10.524`；10 GHz 的有效电感约 `0.638 nH`；至 30 GHz 扫描上限未见电抗首次过零。`w=7u` 属性实例同为 0 errors/5 warnings，带内最小 Q 约 `10.515`，10 GHz 有效电感约 `0.649 nH`。两者在本项目教学 Q≥15 阈值下均为 `response_screen_fail`，不是论文 LNA 规格失败，也不说明其他合法几何一定失败。无观察过零仅是**当前模型、本次离散扫频**的 SRF 下界，不能推断真实器件 SRF 一定高于 30 GHz。

两份档案均强制记录 `physical_qualification=false`、`coupling_qualification=false`、`geometry_sweep_verified=false`、`not_lna_result=true`、`spec_pass=null`；属性变体还显式记录 `cdf_callback_validated=false`。它们没有二端口/耦合系数 k、MCR、EM、PEX、角落/温度、版图寄生、工艺频率适用性或真实三级 LNA 结果。CDF 中显示的默认 Q 参考频率不是本次 8–12 GHz 的测量，不能替代原始 SP。

## 第二种默认螺旋器件的独立筛选

另对授权库中的**对称型三端螺旋器件**做只读 symbol 引脚定位，报告在忽略目录 `results/runs/passive_quality_reference/alternate_spiral_pins_20260926T233354Z_371f7531/`；其端口坐标与已测标准型相同。随后仅在用户设计库建立一个新的默认参数一端口 OA cell，`schCheck=(0 0)`、`dbSave=t`、网表导出成功。独立 Spectre 运行及 OA、OCEAN 脚本回读、网表前后哈希、伴随文件、日志、591 点 PSFASCII/CSV 和证据清单位于 `results/runs/passive_quality_reference/sym_spiral_default_20260926T233706Z_8235bd93/`，既有标准型归档未覆盖。仿真 0 errors、5 条 `SFE-1131` 警告；`audit_pdk_inductor_oneport` 的原始数据重建及只读复核均通过。

该对称型默认实例在 8–12 GHz 的最小一端口 Q 约 **10.714**，10 GHz 有效电感约 **0.721 nH**；0.5–30 GHz 的离散数据未观察到电抗首次过零。它也未通过本项目 Q≥15 教学筛选。标准型默认实例的 Q≈10.524 与此不同，但这是**不同器件模型/默认结构**，不是保持其他条件不变的尺寸优化实验，也不能据约 0.19 的 Q 差异推断版图优劣。两者均没有 CDF 回调/PCell、实际耦合 k、EM/PEX 或角落验证；对称型一端口不能充当论文 MCR 或三级 LNA 结果。

## 可重审命令

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_passive_quality_reference `
  results/runs/passive_quality_reference/20260926T203114Z_60899fd6
python -m orfadc.experiments.audit_pdk_inductor_oneport `
  results/runs/passive_quality_reference/20260926T205333Z_b96aea29
python -m orfadc.experiments.audit_pdk_inductor_oneport `
  results/runs/passive_quality_reference/20260926T205333Z_b96aea29 `
  --compare-to results/runs/passive_quality_reference/20260926T211116Z_4bb251a3
python -m orfadc.experiments.audit_pdk_inductor_oneport `
  results/runs/passive_quality_reference/sym_spiral_default_20260926T233706Z_8235bd93
```

审计从原始 `sp.sp` 重算 591 行 CSV 和指标，检查 PDK 源网表/控制文件快照、运行状态、Spectre 完成与警告、SHA-256 清单，并拒绝重新哈希后的虚假筛选通过、物理资格声明和 CSV 数值篡改。私有网表、伴随文件、工艺路径和原始日志**不得进入公开 Git 提交**；公开代码不含工艺模型内容。

## 下一门槛

在授权环境中用**新的用户库诊断 cell**验证 CDF/PCell 初始化与合法几何修改是否真实传到 OA 实例、Spectre 网表和仿真响应；前次无图形 `vfoSetParam` 失败路径不应原样重试。之后才可选取满足设计频带、工艺规则、温度/角落和 Q/SRF 约束的电感，测量耦合 k、损耗和版图依赖；进一步验证级间/输出匹配与三级 LNA fullchain。缺少任一步都不能用本页的一端口数据替换论文物理 MCR 或 Fig. 7/Table IV/V。
