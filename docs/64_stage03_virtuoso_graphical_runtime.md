# Stage 03：完整 Virtuoso 图形运行时与只读 CDF 复核

## 为什么做此探针

`docs/24_stage03_cdf_write_diagnostic.md` 中无图形 `vfoSetParam` 未能留下有效 OA；`docs/62_stage03_rf_pcell_geometry_probe.md` 的低层 PCell 放置也未调用 CDF 表单。为确定下一步是否具备可用的图形化运行环境，本轮在有界 Xvfb 下启动**完整 Virtuoso 的 `-nographE` 模式**。该模式使用实际 X display，不是之前失败的纯无图形参数写入路径。本轮只执行启动/退出与已验证的只读 CDF 查询，未打开或修改新的设计 cell，也没有调用 callback。

## 原始运行与修复

启动前检查宿主可用物理内存高于项目的 2.66 GiB 门槛、来宾 SSH 正常；通过环境配置定位 Xvfb，使用新的远端工作目录和显示编号，脚本退出时清理 Xvfb/Virtuoso 进程。`circuit/skill/virtuoso_gui_smoke.il` 仅打印两条 replay 标记并退出；`circuit/skill/run_virtuoso_gui_smoke.sh` 不打开 PDK 或用户 OA。自动入口为 `src/orfadc/experiments/run_virtuoso_gui_smoke.py`。

1. 第一次新 run `20260927T023052Z_b53a175a` 因项目配置的 `xvfb_path` 实际是**目录**而非 Xvfb 二进制，返回 98；失败日志保留。入口现先区分目录/文件并核查可执行文件。
2. 第二次新 run `20260927T023145Z_56250957` 的完整 Virtuoso 已启动并退出，然而首版解析器把 CIW 输入回显和输出各计一次，误报 `replay_incomplete`；原始日志不改写。解析器现只识别 CIW 的**输出**标记。
3. 第三次新 run `20260927T023222Z_0f857b59` 返回 `gui_replay_completed`。只读审计器 `src/orfadc/experiments/audit_virtuoso_gui_smoke.py` 从归档源码、哈希、启动日志、replay 输出和退出记录重审为 `gui_replay_verified`。探针结束后 SSH 检查无残留 Virtuoso/Xvfb 进程。

随后将此前成功的**只读** CDF 查询脚本用固定 SHA-256 锁定，仅把报告输出路径机械替换到新私有运行目录，使用同一完整 Virtuoso/Xvfb 模式运行；入口为 `src/orfadc/experiments/run_virtuoso_cdf_readonly.py`。新 run `20260927T023600Z_26d308a8` 正常退出，其 CDF 报告与 2026-09-26 的 OCEAN 只读报告**逐字节相同**。`src/orfadc/experiments/audit_virtuoso_cdf_readonly.py` 核对原脚本与派生脚本、launcher、日志、报告和旧报告字节，结论为 `gui_cdf_readonly_verified`。所有含授权库/器件信息的脚本、报告和原始日志仅在 Git 忽略的 `results/runs/virtuoso_gui_smoke/`、`results/runs/virtuoso_cdf_readonly/` 和既有私有归档中。

重审命令（在持有私有归档的本机）：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_virtuoso_gui_smoke `
  results/runs/virtuoso_gui_smoke/20260927T023222Z_0f857b59
python -m orfadc.experiments.audit_virtuoso_cdf_readonly `
  results/runs/virtuoso_cdf_readonly/20260927T023600Z_26d308a8 `
  results/runs/lna_stage03/private_schematic_core/probe_mos_cdf_v1_v2.ocn `
  results/runs/lna_stage03/private_schematic_core/mos_cdf_readonly_20260926_02_report.txt
```

## 严格边界与下一步

这只把“没有可用图形化 Cadence 运行时”这一运行环境疑点缩小：完整 Virtuoso 可以在受控 Xvfb 下启动并读取 CDF。`-nocdsinit` 的最小探针没有证明所有 PDK 表单初始化过程、属性表单 callback、schematic/网表几何传播或 DRC 可通过。Cadence 官方社区说明，程序化修改实例属性不自动执行交互式 CDF callback，且回调可能依赖有效 CDF 类型、表单状态与执行顺序，不能从只读报告推断行为；见 [程序化修改与属性表单区别](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/19224/how-to-use-skill-to-change-pcell-parameter-like-using-edit-instance-properties-to-change-parameter)和 [CDF callback 调用限制](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/37665/invoke-pcell-callback---simple-case-of-abinvokecdf-functions)。

下一步先在完整 Virtuoso 下**只读**识别该 PDK 支持的属性表单入口与初始化依赖，再在全新用户库诊断 cell 上做一项合法参数的交互式表单编辑、Check and Save；同一候选必须对照 CDF 派生属性、Spectre 网表、保存后 PCell 几何及适用 DRC 报告。此前两份 PCell layout 的 DRC 均有违规（`docs/63_stage03_rf_pcell_gds_drc_probe.md`），需工艺负责人定性。当前固定标记 `cdf_callback_validated=false`、`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`；不解锁论文级 LNA sizing。
