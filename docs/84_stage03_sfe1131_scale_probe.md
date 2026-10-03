# Stage 03：授权模型重复缩放选项的只读定位

## 来源与方法

已审计的 OA 共源诊断 `20260927T081306Z_57cfbd7e` 在 Spectre 25.1 完成 DC/SP/noise 时有五条 `SFE-1131`：同一 TopCircuit 作用域的 `scalefactor` 被多次定义，Spectre 使用最后一个值。日志还说明**后续同类警告会被抑制**。这五条警告并非五个不同物理缺陷的证明，但也不能因为仿真 0 errors 就视作已解决。

`probe_sfe1131.py` 先验证原 agent trace、候选清单及派发前远端身份快照与**当前 SSH 配置**一致，再对该诊断的 OA 网表、PSFASCII、CSV 和证据清单重新审计，从已归档日志解析五条警告与最终生效值。它只通过 SSH 在授权来宾中读取日志所引用的模型文件对应行，提取数值并计算文件哈希；同一路径若在探针期间产生不同文件哈希则拒绝。不修改 PDK，不复制模型文件或原文。Spectre 日志的相对路径段先被规范化；输出仅保存源 trace/远端身份/清单/日志哈希、匿名路径哈希、模型文件哈希、行号和值，放在 Git 忽略的私有目录。

本机**最终来源绑定与同文件版本检查报告** `results/runs/model_scale_probe/20260927T100000Z_final/scale_probe.json` 显示：五个**已打印警告的后写入定义**均与日志中的有效缩放值一致，状态为 `observed_assignments_match_effective_value`；`further_occurrences_suppressed=true`。报告明确固定 `model_warning_resolved=false`、`pdk_qualification=false`、`not_lna_result=true`、`spec_pass=null`。首次尝试因日志路径包含合法 `../`、`./` 而在本地校验处拒绝，未生成报告；`20260927T093000Z_diagnostic`、`20260927T094000Z_diagnostic` 无派发端点绑定，`20260927T095000Z_bound` 尚无同文件版本检查，均保留为历史诊断，不能代替最终报告。定向 mock 测试覆盖值一致/冲突、路径规范化、报告脱敏、未知警告、伪造远端来源、SSH 配置变化和探针中模型文件版本变化。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.probe_sfe1131 `
  --run-dir results/runs/S1/seed0/S1_seed0_oa_diag/<已审计运行ID> `
  --trace-dir results/runs/agent_diagnostic/<原派发traceID> `
  --output-dir results/runs/model_scale_probe/<新的独占目录> `
  --config config/remote_cadence.local.yaml `
  --template results/runs/<私有OA模板目录>/netlist.scs `
  --template-sha256 <该模板SHA256>
```

## 结论边界

一致性仅覆盖 Spectre **实际打印出的五个后写入位置**与本次日志中的有效值。首条警告的先前定义、被抑制的更多位置、全部 include 分支、工艺角落/温度、器件适用范围与仿真准确性均未通过该报告验收。配置快照匹配也**不等于 SSH 主机密钥或实际端点已独立认证**。模型文件哈希使本次读取可定位，但没有公开模型原文，也不是工艺方签名。不能删除或自行改写 PDK 中的重复选项，更不能因一致性把已有 S 参数/NF/HB 诊断改称合格 LNA。

下一步应由授权 PDK/仿真负责人核对所用模型 include 顺序、角落与缩放语义，确认重复定义是否为预期、何种配置下允许以及是否影响器件/版图尺寸映射；同时继续同候选 CDF/PCell、匹配与 DRC 门禁。得到可追溯说明或修正后的新运行前，`SFE-1131` 保持未解决。

本轮新探针定向 `7 passed`，全量 Python 回归 `791 passed, 3 skipped`；均不包含新的 Spectre 运行。
