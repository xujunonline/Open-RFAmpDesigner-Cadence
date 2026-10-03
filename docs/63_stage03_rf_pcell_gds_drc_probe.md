# Stage 03：RF PCell GDS 与 DRC 诊断

## 目的与来源

续接 `docs/62_stage03_rf_pcell_geometry_probe.md` 中两个保存的用户设计库 layout cell。这次只做**已授权环境内**的 GDS 导出和 Calibre DRC 诊断，不触碰 PDK 或已有用户 OA cell；GDS、工艺 layer map、规则文件副本、DRC 数据库和原始日志均留在 Git 忽略的私有运行目录。公开仓库不携带工艺规则、模型或器件几何常数。

每次运行前核对 SSH 与宿主物理余量，仍按 2.66 GiB 下限执行。两个 GDS 输入来自此前已保存的默认及单参数 PCell 变体，不是新的 schematic sizing 候选，也没有 CDF 属性表单回调验证。

## 导出与失败记录

首次默认 cell 的 `strmout` 未显式绑定技术库；虽然进程返回 0，归档摘要只有 **0 个** polygon/rectangle/path，并有大量映射警告。档案保留于 `results/runs/pdk_geometry_stream/rf_pcell_default_20260927_01/`，不得作为版图或 DRC 输入，不能仅凭 `strmout` 退出码判定导出成功。

在两个**新的**归档中显式绑定授权技术库与对应 layer map 后，默认与变体 cell 各自导出非空 GDS，`strmout` 报告 0 errors、0 warnings；两份 GDS 摘要有同样数量的几何对象，但文件哈希不同。它们位于 `results/runs/pdk_geometry_stream/rf_pcell_default_20260927_02/` 和 `rf_pcell_wr3_20260927_01/`。这证明流片格式输出包含形状，不能据此判断层映射、工艺合法性或器件性能已获签核。

## DRC 诊断及结论

两个独立 Calibre 作业使用同一授权 DRC 源规则文件。运行时仅在私有远端作业目录复制规则文件、替换其输入 GDS 与顶层 cell 占位符，原规则文件不修改；没有把规则副本下载到公开仓库。作业和原始报告分别在 `results/runs/pdk_drc_probe/rf_pcell_default_20260927_01/`、`rf_pcell_wr3_20260927_01/`。

两次 Calibre 进程均正常完成，并执行相同的 2319 个 rulecheck；**两次均报告 46 组、61 个 DRC 结果**，非零规则分布也相同。报告还有运行期警告，涉及映射和单独器件 cell 的上下文。因此这里只能说“DRC 作业完成并发现违规”，**不能说 DRC 通过**；进程退出码 0 仅是作业完成。单器件 cell 以全芯片规则检查时，有些规则可能依赖周围电路或封装上下文，但在工艺负责人逐条审阅规则与版图前，不能自行豁免或把相同结果当成合格证明。

只读审计器 `src/orfadc/experiments/audit_pdk_rf_drc_probe.py` 检查：失败的空导出不得混用；有效 GDS 必须非空且零导出警告；DRC 来源哈希必须绑定对应 GDS；两份作业使用同一源规则文件；本地/远端脚本相同、Calibre 完成标志和报告结果总数可对账。它仅输出统计和资格布尔值，不输出私有规则内容。重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_drc_probe `
  results/runs/pdk_geometry_stream/rf_pcell_default_20260927_01 `
  results/runs/pdk_geometry_stream/rf_pcell_default_20260927_02 `
  results/runs/pdk_geometry_stream/rf_pcell_wr3_20260927_01 `
  results/runs/pdk_drc_probe/rf_pcell_default_20260927_01 `
  results/runs/pdk_drc_probe/rf_pcell_wr3_20260927_01
```

重审结论为 `drc_completed_with_violations`、`empty_stream_rejected=true`、`drc_pass=false`、`drc_context_qualified=false`、`cdf_callback_validated=false`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。定向测试见 `tests/test_pdk_rf_drc_probe.py`，包括 GDS、报告总数、输入绑定、脚本和虚假通过声明的篡改拒绝。

## 下一道门禁

1. 在授权交互式 Virtuoso 新 cell 中用 PDK 支持的属性表单作**合法**单参数更改，执行 Check and Save；导出同一候选的 schematic Spectre 网表，核对 CDF 派生量、模型参数及保存后的 PCell 几何。不要复用曾卡住的无图形 `vfoSetParam` 路径。
2. 请工艺/版图负责人在授权环境中逐条审阅 DRC 结果与运行警告，确认 layer map、规则适用层级、合法参数范围及所需外围上下文。需要修正时用新的 cell 和新的归档重跑，不改写本次原始报告；任何正式豁免须有可追溯依据。
3. 只有 CDF/网表/几何同候选传播及适用 DRC 通过后，再推进 EM/PEX、角落和 RF Q/k/SRF 筛选；同时处理已有 Spectre `SFE-1131` 模型配置警告。当前没有合格物理 MCR 或论文级 LNA fullchain。
