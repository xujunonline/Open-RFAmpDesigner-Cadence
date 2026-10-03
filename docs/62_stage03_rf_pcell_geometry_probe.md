# Stage 03：RF MOS 低层 PCell 几何响应诊断

## 与前次失败路径的区别

`docs/24_stage03_cdf_write_diagnostic.md` 的无图形 `vfoSetParam` 未完成，因此没有 CDF 回调验收。本次**没有再调用该函数**。在 `docs/61_stage03_rf_layout_readonly.md` 的只读视图基础上，先读取默认 `layout` 中子实例及 PCell 参数对象，再按照 [Cadence 官方 SKILL 论坛的参数类型说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/51577/setting-parameter-values-for-dbcreateparaminstbymastername/1383119)使用 `dbCreateParamInstByMasterName`，仅在已有**用户设计库**的两个全新 layout cell 放置默认与单参数变体。该 API 是低层 PCell 放置接口，**不是**Virtuoso 实例属性表单，也不会自动证明 CDF callback、schematic 或 DRC 通过。

## 原始档案与结果

1. 首次子实例元数据脚本在 `length()` 接收数据库对象而非列表时出错，随后 OCEAN 落入交互错误提示，命令到超时边界才退出；失败脚本、日志和状态保留在忽略目录 `results/runs/pdk_geometry_readonly/rf_instance_metadata_20260927_01/`。这属于探针 API 使用错误，不归因于 PDK 回调。第二次新脚本 `rf_instance_metadata_20260927_02/` 成功，只读确认默认 `layout` 有两层子实例，其 master/supermaster 关系可见。
2. 只读参数脚本 `results/runs/pdk_geometry_readonly/rf_pcell_params_20260927_01/` 返回 0，确认目标长度、单指宽度及指数参数在 PCell master 中均为 `string` 类型。具体默认值、子实例名称和几何尺寸留在私有报告，不写入公开方案的工艺参数表。
3. 两个**新的用户库** layout cell 分别以默认参数及一个显式 `string` 参数放置 RF PCell。`dbSave=t`；两份 OA 文件均非空，远端脚本与本地脚本、保存后的远端 OA 与归档 OA 均逐字节相同。私有来源为 `results/runs/pdk_geometry_instantiation/rf_pcell_default_20260927_01/` 与 `rf_pcell_wr3_20260927_01/`。这两个脚本没有 PDK 写操作，也没有调用 CDF callback。
4. 另用只读脚本重开两个保存的用户 layout cell，比较顶层与核心子实例边界框，归档于 `results/runs/pdk_geometry_readonly/rf_saved_children_20260927_01/`。显式参数变化后，master 与核心子实例几何均发生一致变化；控制参数保持不变。具体边界框和 PDK 几何值只保留在私有档案中。

`src/orfadc/experiments/audit_pdk_rf_pcell_geometry.py` 从三份成功档案重新核对脚本 SHA-256、远端回读、OA 字节、OCEAN 完成状态、参数报告和保存后核心几何；它拒绝 OA 回读、参数、子实例边界框、callback 状态或第二个显式参数的篡改。定向测试见 `tests/test_pdk_rf_pcell_geometry.py`。只读重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_pcell_geometry `
  results/runs/pdk_geometry_instantiation/rf_pcell_default_20260927_01 `
  results/runs/pdk_geometry_instantiation/rf_pcell_wr3_20260927_01 `
  results/runs/pdk_geometry_readonly/rf_saved_children_20260927_01
```

## 仍未通过的门禁

上述结果只证明**这个低层参数能改变本机授权 PDK 的 PCell 几何**。它没有证明该参数值符合工艺设计规则、面积/寄生由 CDF 正确派生、schematic 的同一候选生成一致的 Spectre 网表，也没有 DRC、EM、PEX、角落或器件频段资格。退出日志中的表单初始化警告仍需环境负责人检查，不能倒推以前中断原因。审计结论固定标记 `physical_qualification=false`、`cdf_callback_validated=false`、`drc_validated=false`、`spec_pass=null`、`not_lna_result=true`；这些是资格边界，不是仿真指标。

后续已对这两个保存 cell 进行 GDS/DRC 诊断，见 `docs/63_stage03_rf_pcell_gds_drc_probe.md`：非空 GDS 已导出，但两份 DRC 报告均有违规，故本节当时的 `drc_validated=false` 仍是正确的资格结论。下一步仍是授权交互式 Virtuoso 上的**新**诊断 cell：通过 PDK 支持的属性表单做单参数更改，Check and Save，导出 Spectre 网表，再与该候选 PCell 参数、几何及适用 DRC 报告逐项对照。证据齐全之前不得把低层 PCell 变体用于论文级 LNA 尺寸空间或宣称合格物理 MCR。
