# Stage 08：带警告螺旋 GDS 的诊断性 Calibre DRC

## 目的与输入边界

`docs/75_stage08_spiral_pcell_gds_gate.md` 的默认及 `nr=4` 螺旋 layout cell 各导出一份非空且不同的 GDS，但每份都有两条 `XSTRM-399` 空结构警告，`drc_ready=false`。本次只为定位障碍，在已授权的私有环境对这两份**未具备合格输入资格**的 GDS 各运行一次 Calibre DRC。它不豁免导出警告，也不取代 OA/GDS 几何完整性、官方层映射、合法参数范围或适用规则范围审查。

Calibre 使用相同的授权源规则文件，只在每个私有作业目录中的规则副本替换规定的 GDS 路径和顶层 cell 占位符。源规则及工艺数据未修改，原始 GDS、规则副本、日志与结果数据库只保存在 Git 忽略的 `results/runs/` 下。公开 runner 为 `src/orfadc/experiments/run_pdk_spiral_drc.py`；源规则路径只在运行时从私有授权环境传入，公开代码与文档不包含它。

## 两次实际运行

| 变体 | 私有运行目录 | Calibre 退出码 | 执行 rulecheck | 违规组/结果 | 非零规则类别 |
| --- | --- | ---: | ---: | ---: | ---: |
| 默认 | `results/runs/pdk_spiral_drc/20260927T062725Z_9d6d0279/` | 0 | 2319 | 83/83 | 39 |
| `nr=4` | `results/runs/pdk_spiral_drc/20260927T062819Z_e91b6a15/` | 0 | 2319 | 85/85 | 41 |

两个非零规则类别在变体间不同。报告还记录运行警告。**退出码 0 仅说明作业完成，不表示 DRC 通过**；两份报告均有大量违规，而且输入 GDS 的空结构警告尚未定性。不能简单把 83→85 解释成仅由匝数变化引起的“新增两处版图错误”：类别/几何可能受导出完整性、参数合法性和规则上下文影响，需版图/工艺负责人查看私有原始报告并判定。

私有汇总位于 `results/runs/pdk_spiral_drc/summary_20260927_01/`。只读审计器 `audit_pdk_spiral_drc.py` 先重审上游 OA/GDS 汇总，再核对两份源 GDS、远端回读、脚本、规则源 SHA-256、Calibre 完成标记、报告各规则计数和摘要证据清单。重算摘要哈希不能掩盖原始输入、脚本、报告或资格位被更改。汇总固定 `drc_input_qualified=false`、`drc_context_qualified=false`、`drc_pass=false`、`physical_qualification=false`、`spec_pass=null`；这只是**可重审的失败诊断**，不是器件认证或 LNA 候选测量。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_spiral_stream `
  results/runs/pdk_spiral_stream/summary_20260927_01
python -m orfadc.experiments.audit_pdk_spiral_drc `
  results/runs/pdk_spiral_drc/summary_20260927_01
python -m pytest tests/test_pdk_spiral_drc.py -q
```

## 后续门禁

1. 请授权版图/工艺负责人在私有环境核查 91 个 via-array master 引用中的空变体、两条 GDS 导出警告、官方 layer/via map、`nr=4` 合法范围及本规则文件对该 cell 的适用性。不能自行删除违规、改 deck 或臆造豁免。
2. 在全新归档中修复或正式解释输入异常后，重新从 OA 导出 GDS，核对层级/图形，再运行适用 DRC 并要求**零未豁免违规**且解释全部运行警告。保留源与结果哈希。
3. 仍需同候选 schematic/CDF 网表、Q/SRF/耦合、EM/PEX/角落和实际 LNA fullchain。当前 Stage 08/09、论文 Table IV/V/Fig. 7 数值复现均未验收。
