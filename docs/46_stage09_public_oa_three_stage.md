# Stage 09：公开 MOS1 三级 Virtuoso OA/OCEAN 交叉验收

`docs/45_teaching_three_stage_spectre_probe.md` 的三级**直接 Spectre**网表现在有一个独立的公开 `analogLib` OA schematic 实现。这里只验收同一理想教学电路能经 Virtuoso schematic、经典 OCEAN 和 Spectre 跑通，不能把它当作作者 TSMC N65 三级宽带 LNA、物理 MCR、PDK PCell 或论文 fullchain。

## 可追溯结构

先在授权主机只读查询 `analogLib`：`mind` 符号有 `ind1`、`ind2`、`k` CDF 参数但无电气端子；四端 `xfmr` 另有 `n1/n2/m/k/pi/si`。本方案选择三只 `mind`，分别引用 L12P/S、L23P/S、L3P/S，避免凭空猜测符号端子。只读诊断脚本为 `circuit/ocean/inspect_teaching_coupler_symbols.ocn`，原始查询留在忽略目录 `results/runs/teaching_oa_symbol_probe/10fce29d43/`。

`circuit/ocean/create_teaching_three_stage_oa.ocn` 在全新教学库/cell 中放置首级 M1/M2 cascode、后级 M3/M4 与 M5/M6 差分共源、三对理想互感、四只 10 fF 交叉电容、单端 50 Ω 输入和差分 1787 Ω 输出端口，以及并联的 62 fF 负载电容。每个电气端子有短线和网络标签；地端通过 `analogLib/gnd` 连成 `gnd!`。`schCheck=(0 0)`、保存成功；报告为 64 个 OA 实例（包括 34 个地符号）、26 条网络。OA 导出的 Spectre 网表与公开直接模板的 **47 个电路元件**按名称、端子、参数逐个一致，含三条 `mutual_inductor coupling=0.45`。布局只是可检查的带标签教学 schematic，不是射频版图。

经典 OCEAN 使用 `circuit/ocean/run_teaching_mos1_oa.ocn` 对同一 OA cell 做 DC、8–12 GHz/161 点 SP/noise；`circuit/ocean/export_teaching_three_stage_oa.ocn` 以 15 位精度导出四条复数 S、NF/NFmin/F/Fmin、VDD 电流和六管各 8 个工作点字段。Spectre 25.1 日志为 0 errors/0 warnings/5 notices。

## 两份 OA 归档与独立基线

| 原始运行 | 用途 | 验证结果 |
| --- | --- | --- |
| `results/runs/teaching_three_stage_oa/df6db2c10a/` | 创建脚本、OCEAN 导出与审计器首次实机验收 | `schCheck=(0 0)`；OA/直接 Spectre 逐频交叉核验通过 |
| `results/runs/teaching_three_stage_oa/20260926T184521Z_4561f7d5/` | `run_teaching_three_stage_oa.py` 在另一个新 cell 上一键重复 | 创建→网表→DC/SP/noise→导出→审计全部完成 |
| `results/runs/teaching_three_stage/probe_7eecbf34a74a/` | 先前的独立直接 Spectre 基线 | PSFASCII/Touchstone、六管工作点和源归档已独立审计 |

两份 OA 运行与基线的 161 点复数 S 最大差约 `6.12e-15`，NF 最大差约 `1.24e-14 dB`，工作点最大绝对差约 `1.00e-14`；供电约 14.88488 mA。自动 OA 运行的带内最差混合参考 S11/S21/S22 约 -10.08/-12.18/-0.17 dB，最差 NF 约 8.12 dB，S21 纹波约 16.43 dB。两个 OA 运行是**同参数通路复验**，不能重复计为优化样本。审计器逐一校验 OA view、schCheck、47 元件网表、公开/远端脚本、模型、原始日志、PSF 导出、频率、六管工作点、源清单和 CSV/JSON；重哈希篡改 S21 或互感参数的测试均被拒绝。

可重复运行与只读复核（要求已经授权的 Cadence 主机、私有 SSH 配置以及保留在本机的直接基线归档）：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.run_teaching_three_stage_oa `
  --schematic-context /opt/eda/cadence/IC251/tools.lnx86/dfII/etc/context/64bit/schematic.cxt
python -m orfadc.experiments.audit_teaching_three_stage_oa `
  results/runs/teaching_three_stage_oa/20260926T184521Z_4561f7d5 `
  results/runs/teaching_three_stage/probe_7eecbf34a74a
```

运行目录与私有 SSH 配置均受 `.gitignore` 排除。公开仓库只保留自造 MOS1 模型与脚本；远端执行件下载后在本机证据清单中与公开源逐字节核对。此 OA/OCEAN 归档没有真实 Q/SRF、工艺寄生、PVT、三级压缩点或统一候选 `fullchain_eval`；独立的同拓扑**低驱动单点** HB 核验见 `docs/47_stage09_three_stage_low_drive_hb.md`，也不能代替压缩点。混合 50/1787 Ω S21 不能称作 50→50 Ω 增益。`not_lna_result=true`、`spec_pass=null` 保持不变。下一步是可实现的级间/输出匹配及稳定性门禁、同一合格三级候选的大信号扫描，再在授权 PDK 交互环境核验 CDF/PCell；此 OA 教学通过不能替代这些条件。
