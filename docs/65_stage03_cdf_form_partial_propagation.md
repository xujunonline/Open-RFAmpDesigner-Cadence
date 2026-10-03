# Stage 03：属性表单单字段变化的部分传播

## 前提与探针顺序

续接 `docs/64_stage03_virtuoso_graphical_runtime.md`：完整 Virtuoso 可在受控 Xvfb 下运行，既有只读 CDF 报告与 OCEAN 逐字节一致。本轮先用不打开设计 cell 的 `circuit/skill/virtuoso_form_api_probe.il` 检查属性表单相关 SKILL 入口，五个所查接口在当前运行时均已加载；私有 run 为 `results/runs/virtuoso_gui_smoke/20260927T024415Z_58e134ca/`。接口存在不证明该 PDK 的 callback 可用。

随后在既有诊断 schematic 的**只读**窗口调用实例属性表单，所有原始尝试单独留档：

1. `20260927T024605Z_6420a646` 的首个脚本在循环结束后引用局部 `cellName`，日志含未绑定变量错误；进程返回 0、报告有末尾标记都不足以宣称窗口已打开。旧状态原样保留，审计器明确拒绝。
2. `20260927T024729Z_f792c706` 修复目标 cell 引用后，窗口已打开；`hiGetCurrentForm()` 因焦点不在表单返回 `nil`，仍不能据此否定表单。`20260927T024832Z_80f3a6f8` 又确认表单全局对象存在。
3. `20260927T024933Z_5988b692` 的报告显示表单全局对象及常见宽长字段可读，字段总数为 43。`src/orfadc/experiments/audit_virtuoso_form_readonly.py` 从只读脚本派生、CIW 日志及既有 OCEAN 报告重审为 `gui_form_readonly_verified`；没有改字段、调用 callback 或保存 OA。

## 两次新用户 cell 的写入实验

首先从默认器件在全新**用户设计库** cell 上创建单管，并尝试表单单字段设置。`results/runs/virtuoso_cdf_form_variant/20260927T025508Z_91ead4e8/` 的原始日志在打开表单时报告默认长度违反工艺下限；`schCheck` 有 8 项问题，保存返回未得到确认，状态为 `form_action_incomplete`。不能把进程返回 0 或字段赋值当成成功，不能复用该失败 cell。本报告不公开具体工艺下限或器件尺寸。

为排除无效默认单管的影响，第二次从此前已完成 schematic、OCEAN 和 Spectre 基线的 v2 cell **复制**到另一个全新用户 cell，再仅通过属性表单更改一个 `Wfg` 字段；目标值来自既有 v1/v2 私有 CDF 报告，不在公开代码或日志中写入工艺数值。`results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a/` 的表单动作返回、`schCheck=(0 0)` 和数据库保存均完成，OA 文件非空。这里采用 Cadence 记录的 `dbCopyCellView` 复制语义，原 v2 cell 只读，未覆盖；参见 [Cadence 的 cellview 复制示例](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/30719/saving-designs-in-virtual-memory-to-disk)。

`results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd/` 在**独立 OCEAN 进程**中只读重开保存后的 cell；`results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b/` 用另一独立 OCEAN 进程导出 Spectre 网表，不执行 Spectre。三份档案中的 OA 字节相同。实例 `Wfg` 的新值确实持久化，`w/l/nf` 与复制前 v2 基线一致；新网表的模型 `w/l/nf` 也不变，但 9 个扩散/寄生参数发生变化。这说明表单变化对网表**有部分影响**，同时没有证据证明模型总宽度按预期变化。不能简单标为“完全无效”或“CDF callback 通过”。

`src/orfadc/experiments/audit_virtuoso_form_chain.py` 固定检查来源脚本、单字段派生、保存/Check and Save 报告、CIW/OCEAN 无 SKILL 错误、三份 OA 字节、独立读回、Spectre 网表中的模型与寄生参数。审计结论为 `form_change_persisted_with_partial_model_propagation`，`model_width_changed=false`、`cdf_callback_validated=false`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。失败默认 cell、假通过的只读表单探针及网表/报告/OA 篡改都不能通过审计。重审命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_virtuoso_form_chain `
  results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a `
  results/runs/virtuoso_form_readback/20260927T030527Z_7fb44dfd `
  results/runs/virtuoso_form_netlist/20260927T030547Z_101cf69b `
  results/runs/lna_stage03/private_schematic_core/v2_raw_20260926_01/netlist.scs
```

## 尚未通过的门禁

同条件 Spectre DC/SP/noise 对照后来已完成，见 `docs/66_stage03_form_spectre_pair.md`；两条曲线有可测差异，但仍没有同候选 layout/DRC。表单字段的直接赋值加 `hiFormDone` 是否等价于该 PDK 的真实用户编辑，需要核对 callback 依赖及模型宽度/寄生的预期关系；[Cadence 关于程序化 CDF callback 的说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/37665/invoke-pcell-callback---simple-case-of-abinvokecdf-functions)指出表单状态、CDF 对象类型和回调顺序可能改变结果。OCEAN 启动还保留既有 PDK 表单初始化警告，应由授权环境负责人检查。工艺/版图负责人须判断 `Wfg` 与模型 `w`、寄生参数的合法关系；不能据当前部分传播将该尺寸参数纳入 LNA 搜索空间。此前两个 layout PCell 的 DRC 违规也未解决，见 `docs/63_stage03_rf_pcell_gds_drc_probe.md`。
