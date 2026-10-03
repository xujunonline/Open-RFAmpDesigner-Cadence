# Stage 08：授权螺旋 PCell 几何响应与 GDS 导出门禁

## 本轮要验证的事

`docs/74_stage08_spiral_turns_sensitivity.md` 只改变已保存 OA 网表副本的 `nr` 属性，不能证明该参数在 PCell 中生成了可用版图。本轮在授权环境**仅只读打开 PDK**，再在已有且由当前用户拥有的设计库中创建两个全新 layout cell：一个默认螺旋，一个只将低层 PCell 的字符串参数 `nr` 改为 `4`。没有修改 PDK、复用旧 cell 或覆盖旧证据。原始 OA、OCEAN、GDS、报告和规则路径都保存在 Git 忽略的私有运行目录。

这是 `dbCreateParamInstByMasterName` 的**低层放置实验**，不是 Virtuoso 属性表单或 CDF callback 验证；`nr=4` 的工艺合法范围仍未知，不能把版图生成等同 DRC 合格。两份 cell 也不是同候选 LNA schematic/layout 配对。

## OA 几何证据

只读 master 探针 `results/runs/pdk_spiral_layout/read_20260927_01/` 确认 layout/ivpcell 可打开，layout 有非空形状、子实例和三个端子，`nr` 等几何参数为字符串型。两个新用户 layout 档分别在 `default_20260927_01/` 和 `nr4_20260927_01/`；OCEAN 保存返回 `t`，远端脚本回读一致、OA 文件非空。默认与变体的已记录参数除 `nr=3→4` 外一致，实例边界框发生变化。

第一次跨进程只读重开 `read_saved_20260927_01/` 因未注册已有用户库，两个 cell 均报告 `opened=nil`；失败档保留，**不用于证明几何**。在新档 `read_saved_20260927_02/` 注册该已有库后，两份保存的 layout 均重新打开：每份一个螺旋实例，参数、实例边界框和核心线圈子实例的边界框与创建报告一致；两个核心边界框不同，OA 文件在失败及成功读回前后均逐字节不变。汇总 `results/runs/pdk_spiral_layout/summary_20260927_01/` 可从五份原始档重建；重哈希篡改脚本、OA、参数报告或资格位均被拒绝。

这证明低层 PCell 对这个参数**有几何响应**，但没有证明 CDF 初始化/回调、schematic 网表同候选传播、合法几何、DRC、EM/PEX、耦合或角落。

## GDS 导出与警告

先用 `strmout` 在全新作业目录导出默认 cell，因该目录缺少已授权的 `cds.lib` 库映射而报 `XSTRM-21`，未得到 GDS；失败档为 `results/runs/pdk_spiral_stream/20260927T060335Z_1c9a6555/`。修复为在对应用户 cell 的创建目录读取相同库映射、将输出写到独立新目录后，默认 cell 已生成非空 GDS，但有两条 `XSTRM-399` 空结构警告；首档 `20260927T060455Z_568c9501/` 保留为未验收诊断。后续在相同参数与显式技术库/layer map 下分别重新导出默认与 `nr=4`，归档为：

- 默认：`results/runs/pdk_spiral_stream/20260927T061000Z_c7862888/`。
- `nr=4`：`results/runs/pdk_spiral_stream/20260927T061020Z_42145c2a/`。
- 跨源汇总：`results/runs/pdk_spiral_stream/summary_20260927_01/`。

两份作业均返回 0，XStream 为 **0 errors、2 条 `XSTRM-399`**；GDS 均非空且哈希不同。XStream *摘要*（不是独立 GDS 形状解析）报告默认 `4775` 个 polygon、`6432` 个 rectangle；`nr=4` 报告 `6517` 和 `7342`。这支持“导出包含不同的几何”，不支持“层映射和所有 via 已正确导出”。

[Cadence 官方论坛](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/21950/maintaining-the-pcell-structure-in-a-gds/1309074)提醒 GDS 无法真正保留 PCell 的参数化语义，原始 OA 数据库应与导出文件一同归档。该通用说明**不能解释**本次两条空结构警告，也不代替本 PDK 的映射规范。

为追查警告，`results/runs/pdk_spiral_layout/via_hierarchy_20260927_01/` 的只读 OCEAN 层级遍历在两个保存的 OA cell 中各找到 91 个目标 via-array master 引用，合计 52 次引用指向零边界框、零形状、零子实例的空 master；探针前后 OA 字节一致。这说明 **OA 层级本身存在空变体**，但日志没有给出足够的稳定映射来证明恰好是它们对应两条 GDS 警告，也不能证明其为工艺允许的占位结构。授权目录未发现现成 via-map 文件；不能自行杜撰映射或忽略警告。

`audit_pdk_spiral_stream.py` 重新审计 OA 汇总、层级探针、两份 GDS/日志/摘要、运行前后 OA 与 `cds.lib`、技术库和 layer-map 来源，并保留 `drc_ready=false`、`drc_validated=false`、`physical_qualification=false`、`spec_pass=null`。公开 runner 从**私有已审计脚本**解析库名与路径，源码不嵌入商业模型、工艺目录或本机用户路径。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_spiral_pcell `
  results/runs/pdk_spiral_layout/summary_20260927_01
python -m orfadc.experiments.audit_pdk_spiral_stream `
  results/runs/pdk_spiral_stream/summary_20260927_01
```

## 下一道门禁

两份带警告 GDS 已进行**诊断性** Calibre DRC，发现大量违规，详见 `docs/76_stage08_spiral_drc_diagnostic.md`；这不是合格输入上的 DRC 验收。先在授权环境由工艺/版图负责人核对 PCell 空 via-array 是否为预期占位、是否需要官方 via-map，以及 `nr=4` 的合法范围；必要时在新的归档中重跑导出，要求 GDS 层次与 OA 几何完整对照。随后在合格输入上复验适用 Calibre DRC，并检查结果计数、适用层级及警告；作业退出 0 仍不等于零违规。之后还需同候选 schematic 网表/CDF、RF Q/SRF、耦合、EM/PEX 与角落验收。当前没有合格物理 MCR、三级 LNA 或论文 Table IV/V/Fig. 7 数值复现。
