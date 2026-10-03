# Stage 03：属性表单变体的同条件 Spectre 对照

## 问题与证据范围

`docs/65_stage03_cdf_form_partial_propagation.md` 已证明：复制 v2 schematic 后，在新用户 cell 的属性表单中只修改 `Wfg`，该字段在 OA 中持久化；独立导出的 Spectre 网表中，MOS 模型 `w/l/nf` 未变，而九个扩散/寄生相关参数变化。本次进一步问：**同样的 OCEAN 分析设置下，原 v2 与新 cell 是否产生可测的 DC/SP/noise 对照差异？**这仍是单级诊断电路，不是论文的三级 LNA。

## 原始运行

使用固定私有 OCEAN 来源脚本，仅替换设计 cell、结果目录和报告目的地。两次分析均由独立 OCEAN/Spectre 进程完成，并在运行前后下载 source OA 核对字节一致。公开 runner 为 `src/orfadc/experiments/run_virtuoso_form_spectre.py`，OCEAN 导出脚本为 `circuit/ocean/export_form_sp_noise.ocn`。原始档案均在 Git 忽略的 `results/runs/` 内：

| 用途 | run_id | 内容 |
| --- | --- | --- |
| 原 v2 基线 Spectre | `20260927T031150Z_9fc4af44` | `source_ocean.ocn`、渲染脚本、OA 前/后、`input.scs`、`ade_e.scs`、`spectre.out`、`dcOp.dc`、`sp.sp`、`sp.noise.sp`、日志、状态 |
| 新 cell Spectre | `20260927T031219Z_799a854f` | 与基线同类的独立原始文件 |
| 基线 15 位 OCEAN 导出 | `20260927T031454Z_3d73accb` | 12 条 S 参数/噪声迹线、DC 电流报告、脚本、日志、来源 SHA-256 和诊断摘要 |
| 新 cell 15 位 OCEAN 导出 | `20260927T031517Z_d1026182` | 与基线同类的独立导出 |

两次 Spectre 日志都报告 0 errors，也都保留五条既有 `SFE-1131` 模型配置警告；**0 errors 不消除警告**。导出均为 47 个同一频率采样点。前后 OA 字节相同，说明分析没有改写设计。基线与既有 v2 私有网表的电路定义段逐字节一致；变体与 `docs/65` 独立 OCEAN 导出的电路定义段逐字节一致。对比时不把仿真输出路径差异误认为电路变化。

## 从原始迹线重算的观察

同频点最大绝对差如下；这些是**两条曲线的差值**，不是达到目标规格的指标，也不是论文 Fig. 7 曲线：

| 量 | 最大绝对差 |
| --- | ---: |
| S11 | 0.02382 dB |
| S21 | 0.93897 dB |
| S22 | 0.10084 dB |
| NF | 0.49089 dB |
| NFmin | 0.30621 dB |

`src/orfadc/experiments/audit_virtuoso_form_spectre_pair.py` 先重审 `docs/65` 的 OA/读回/网表链，再核对两次分析脚本同源、原始电路定义、OA 不变、Spectre 日志、PSF 原始文件、导出源 SHA-256、15 位频率轴、诊断摘要及逐点差值。状态固定为 `same_condition_spectre_diagnostic_verified`，并明确 `cdf_callback_validated=false`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_virtuoso_form_spectre_pair `
  results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a `
  results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd `
  results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b `
  results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs `
  results/runs/virtuoso_form_spectre/20260927T031150Z_9fc4af44 `
  results/runs/virtuoso_form_spectre/20260927T031219Z_799a854f `
  results/runs/virtuoso_form_exports/20260927T031454Z_3d73accb `
  results/runs/virtuoso_form_exports/20260927T031517Z_d1026182
```

定向负例覆盖 PSF 原始文件、重算 SHA 后的 MOS/非 MOS 网表篡改、OA、导出曲线、摘要和伪造 `spec_pass=true`。该只读重审能核对已归档的来源与内部一致性，但不是对每个原始数值的外部签名或另一次独立实验。完整 PDK callback 顺序、`Wfg` 对模型宽度与扩散寄生的合法映射仍需授权工艺负责人判断；不能因 S21/NF 有差异就将此字段纳入优化搜索空间。

## 下一门禁

1. 在授权交互环境核对同一器件的真实用户编辑、CDF callback、PCell 几何与网表映射；明确模型 `w` 不变是否符合该 PDK 的指宽/总宽定义。
2. 对**同一候选**建立 layout/GDS/DRC 与 schematic/netlist 的可追溯关联，并由工艺负责人审阅现有非零违规，不自行豁免。
3. 核实五条既有模型警告的影响，再进行角落/温度与可实现匹配网络设计。只有合格 LNA 的 DC、S 参数、noise、功耗、压缩点及物理约束闭环才可推进 Stage 05/09 的 fullchain 验收。

商业 PDK 网表、模型、OA 和具体器件几何继续只留在 Git 忽略的私有档案；此文只给脱敏诊断结论。
