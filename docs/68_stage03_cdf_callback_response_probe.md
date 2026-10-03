# Stage 03：受控 CDF callback 调用与电响应对照

## 为什么继续探测

`docs/65_stage03_cdf_form_partial_propagation.md` 的属性表单脚本直接设置 `Wfg` 字段并调用 `hiFormDone`；随后网表的模型 `w/l/nf` 未变、九个寄生相关参数改变，`docs/66_stage03_form_spectre_pair.md` 又测得与原 v2 基线不同的 SP/noise 曲线。此过程**没有证明字段自身的 CDF callback 被触发**。[Cadence 的程序化参数更新说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/19224/how-to-use-skill-to-change-pcell-parameter-like-using-edit-instance-properties-to-change-parameter/1277215)指出，程序化赋值与交互式编辑的 callback 行为不能混同；[Cadence 关于实例 CDF 与初始化/顺序的讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/13227/a-question-regarding-ccschangecells-il/20248)也表明，不同 PDK 可能需要特定上下文和调用顺序。因此本次仅验证一个**显式调用**的受控探针，不冒称等效于真实用户编辑。

## 独立新 cell 与来源链

`src/orfadc/experiments/run_virtuoso_cdf_callback_probe.py` 从 `docs/65` 已保存的表单变体复制到另一个**全新用户库 schematic cell**；源 cell 只读，不写商业 PDK。它从新实例的 `cdfGetInstCDF` 取得 `Wfg` callback，在完整 Virtuoso/Xvfb 运行时中尝试执行，再 `schCheck`、保存。脚本不把 callback 原文写入公开代码或报告。原始运行：

| 步骤 | Git 忽略档案 | 核查结果 |
| --- | --- | --- |
| 显式 callback 探针 | `results/runs/virtuoso_cdf_callback_probe/20260927T034641Z_e4e5a696/` | callback 调用返回、`schCheck=(0 0)`、保存返回 `t`；源 OA 运行前后字节相同 |
| 独立 OCEAN 网表 | `results/runs/virtuoso_callback_netlist/20260927T034844Z_b2be7dd9/` | 重新读取的 OA 与探针保存件字节相同；Spectre 电路定义已归档 |
| 独立 Spectre DC/SP/noise | `results/runs/virtuoso_callback_spectre/20260927T035402Z_bd6a7d3d/` | 0 errors，仍有五条既有 `SFE-1131` 模型配置警告；原始 DC/SP/noise PSF、网表、日志保存 |
| 15 位 OCEAN 曲线导出 | `results/runs/virtuoso_callback_exports/20260927T035439Z_9afbc1ca/` | 47 点、12 条 S 参数/噪声实数迹线及 DC 电流报告 |

与前一表单变体相比，callback 前后私有报告中的 `Wfg/w/l/nf/fingers` CDF 值不变，实例的 `pd/ps/sa/sb` 四个寄生相关字段改变；独立网表也仅有这四个 MOS 参数改变，其他非 MOS 电路定义保持一致。**模型 `w` 未改变。**这说明 callback 在当前上下文中运行并产生部分可观察效果，但不能证明这些几何/寄生值正确或满足该 PDK 的约束。

在相同固定 OCEAN 分析设置下，callback 新 cell 与前一表单变体的 47 个同频采样点上，S11/S21/S12/S22 的实、虚部及 NF/NFmin/F/Fmin 的 **15 位导出数值全部相同**；导出的 DC 电流也相同。这只是当前电路、采样范围和导出精度下的观察，不是参数对所有频率、角落或版图条件“无影响”的证明。两次运行均保留既有模型警告，不能把 0 errors 当成模型质量验收。

`src/orfadc/experiments/audit_virtuoso_callback_chain.py` 与 `src/orfadc/experiments/audit_virtuoso_callback_spectre.py` 逐层重审既有表单/OA/网表链、callback 脚本和日志、源 OA 前后、独立网表、电路定义、Spectre 原始文件、导出来源 SHA-256 及 12 条逐点曲线。网表、OA、PSF、S12 导出或虚假 `spec_pass` 篡改均被拒绝。完整重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_virtuoso_callback_spectre `
  results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a `
  results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd `
  results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b `
  results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs `
  results/runs/virtuoso_form_spectre/20260927T031150Z_9fc4af44 `
  results/runs/virtuoso_form_spectre/20260927T031219Z_799a854f `
  results/runs/virtuoso_form_exports/20260927T031454Z_3d73accb `
  results/runs/virtuoso_form_exports/20260927T031517Z_d1026182 `
  results/runs/virtuoso_cdf_callback_probe/20260927T034641Z_e4e5a696 `
  results/runs/virtuoso_callback_netlist/20260927T034844Z_b2be7dd9 `
  results/runs/virtuoso_callback_spectre/20260927T035402Z_bd6a7d3d `
  results/runs/virtuoso_callback_exports/20260927T035439Z_9afbc1ca
```

审计状态刻意命名为 `callback_parasitic_change_without_sampled_response_delta`，并固定 `cdf_callback_validated=false`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。真实用户 GUI 输入、该 PDK 的 initProc/多 callback 顺序、模型宽度与每指宽的合法映射、同候选 layout/GDS/DRC、角落及模型警告都没有通过。下一步先在授权环境对**全新用户 cell**进行真正的表单字段交互编辑，并由工艺负责人核对其 OA、网表和 PCell 关系；不能把该 callback 探针直接纳入 LNA 搜索器。
