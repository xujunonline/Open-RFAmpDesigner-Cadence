# Stage 03：公开 MOS1 的 Virtuoso/OCEAN 闭环

## 目标与边界

本项把路线 B 从直接 Spectre 网表推进到 **Virtuoso OA schematic → OCEAN 生成 Spectre 网表 → Spectre DC/SP-noise → OCEAN 从 PSFXL 导出 → Python 重算与证据审计**。它使用 `analogLib/nmos4` 和仓库内人为定义的 MOS1 教学模型，完全不使用商业 PDK。电路是单管共源诊断测试台，既非论文三级 LNA，也未满足本项目的稳定、输入/输出匹配和大信号压缩要求。

| 证据 | 结论 |
| --- | --- |
| 新 OA cell 的 `schCheck=(0 0)`、`dbSave=t` | 14 个器件、7 条网络；只是该公开教学 cell 的 schematic 检查 |
| OCEAN batch + Spectre 25.1 | DC、0.1–20 GHz SP/noise；ADE 报成功，Spectre 0 errors/0 warnings/4 notices |
| OCEAN PSFXL 导出 | 同一 resultsDir 的 S11/S21/S12/S22 实/虚部、NF/NFmin、F/Fmin、VDD 电流，共 47 个频点 |
| Python 原始数据复核 | 8–12 GHz 带内仅 5 个采样点；CSV/指标、网表模型、日志、文件大小/SHA-256 均由只读审计器检查 |
| 复现边界 | `model_kind=teaching_model`、`not_lna_result=true`、`spec_pass=null`；不能用于 Table IV/V、Fig. 7 原始数值 |

归档：`results/runs/teaching_oa/teaching_oa_public_template_v1_20260926/`（Git 忽略，仅本机保留）。此 run 使用本仓库 `circuit/ocean/create_teaching_mos1_oa.ocn`、`run_teaching_mos1_oa.ocn`、`export_teaching_mos1_oa.ocn` 和 `circuit/spectre/teaching_mos1_model.scs`；它是与早期一次性脚本不同的新 cell/新运行。随后 `run_teaching_oa.py` 在第三个独立 cell 上一条命令完成全部流程，归档 `results/runs/teaching_oa/20260926T143425Z_8ed4ffa0/` 再次只读审计通过。早期归档 `results/runs/teaching_oa/run_teaching_flat_tb_v1_20260926_01/` 也已按扩充后的清单重新审计，旧清单保留为 `evidence_manifest_v1.json`。三次运行的 47 点网格、九项带内汇总和采样稳定性记录相同；不把“相同”推及 PDK 或其他模型。

本次 8–12 GHz 自定义诊断带内，最差 S11 ≈ -0.00048 dB、最差 S21 ≈ +1.788 dB、最差 S22 ≈ -9.578 dB、最大 NF ≈ 4.174 dB、NFmin ≈ 0.059 dB，供电电流 ≈ 1.239 mA，ripple ≈ 1.154 dB。这些数字只描述此教学电路与五个采样点。`minimum_k=null`、`unconditionally_stable_on_sampled_grid=false`，因此既未证明全带无条件稳定，也不能把正 S21 误作 LNA 验收。

## 在另一台授权 Cadence 主机上重建

自动入口（在本机已实跑并审计，context 路径须由该主机的授权 Cadence 安装确定；不要复制本机安装路径到其他主机）：

```powershell
$env:PYTHONPATH='src'
$context = Read-Host '授权 Cadence 主机上 schematic.cxt 的绝对路径'
py -m orfadc.experiments.run_teaching_oa --schematic-context $context
```

入口在创建目录前检查至少 2.66 GiB 宿主**可用物理内存**，仅上传四个仓库内公开输入，使用独占远端目录和 OA cell。阶段失败时保留本地指标、已取得的日志和清单；成功才由同一入口调用 `audit_teaching_oa`。本机实测运行前/后宿主余量约 3.14/3.15 GiB，结束后无遗留 OCEAN/Spectre 进程。这只是一次短时验收，不覆盖长时/并行扫描。远端配置继续放在 Git 忽略的 `config/remote_cadence.local.yaml`，输出只进 Git 忽略的 `results/runs/teaching_oa/`。

下列手工步骤解释入口所执行的动作，便于换主机排障：

1. 在授权、可写的个人目录下为 `orfadc_teaching_mos1` 指定库目录和**未占用的** cell 名。准备含 `analogLib` 的 `cds.lib`；不要指向商业 PDK 库。先确认 `ocean`、`spectre`、schematic context 可用，以及主机内存和许可状态。
2. 在独占运行目录放入 `teaching_mos1_model.scs` 和三份 `.ocn`。设置 `ORFADC_TEACHING_LIB_DIR`、`ORFADC_TEACHING_CELL`、`ORFADC_SCHEMATIC_CONTEXT`；从该目录执行 `ocean -nograph -restore create_teaching_mos1_oa.ocn`。必须得到 `check_return=(0 0)` 和 `save_return=t`。脚本拒绝覆盖已有 cell。
3. 同一目录执行 `ocean -nograph -restore run_teaching_mos1_oa.ocn`，检查 `teaching_flat_tb_run_report.txt`、ADE 成功、生成网表中 M1 的 `n_teach w=300u l=100n` 以及 Spectre 0 error/0 warning。ADE 使用基础 `Spectre`、batch 模式，避免旧环境中高性能许可证等待。该设置只证明本机当时成功，非许可证通用方案。
4. 新建 `ocnprint/`，将 `ORFADC_TEACHING_RESULTS_PSF` 指向此运行的 `results/psf`，在 `ocnprint/` 中执行 `ocean -nograph -restore ../export_teaching_mos1_oa.ocn`。将导出报告同时保留为 `ocean_export_report.txt` 和 `ocnprint/report.txt`；保留全部 12 条迹线。PSFXL 本身不由 PSFASCII 解析器读取，使用 OCEAN `ocnPrint` 导出后再读。
5. 下载 OA view、伴随网表、公开模型、OCEAN/Spectre 日志、DC/SP/noise 原始文件和迹线至独立的 Git 忽略目录。使用 `extract_ocean_oa --teaching-model --low-ghz 8 --high-ghz 12 --supply-voltage-v 1.2` 生成 CSV/JSON；再用 `write_evidence_manifest` 登记原始文件及 `ocnprint/report.txt`，最后执行 `audit_teaching_oa`。下载失败、缺少原始文件、来源目录不一致或指标不能从迹线重算时不得宣称通过。

本机只读验收命令：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_teaching_oa results/runs/teaching_oa/teaching_oa_public_template_v1_20260926
py -m orfadc.experiments.audit_teaching_oa results/runs/teaching_oa/20260926T143425Z_8ed4ffa0
```

审计器验证清单的大小/SHA-256、报告电流、公开模型与被加载路径、Check and Save 结果、OA 生成网表的拓扑和参数、Spectre 日志、同一 OCEAN resultsDir，以及由导出迹线重新计算的全部指标和每行 CSV。SHA-256 只证明内部归档一致性，不是防止有权限者整体改写的数字签名。PSFXL 原始文件已归档，但通用解析器不直接重算其二进制数据；迹线与 PSFXL 的绑定依靠 OCEAN 导出结果目录记录，仍有进一步独立交叉验证空间。

后续 `export_teaching_mos1_oa.ocn` 已提高为 15 位导出。上述三份平面拓扑归档是在修改前用默认六位导出生成的，历史清单未回写；其 S/NF 数值可作低精度教学观察，**采样 K 不应用于近边界稳定性结论**。新的电感拓扑、高精度导出与独立直接 Spectre 核验见 `docs/39_stage03_inductive_oa_precision.md`。

## 下一步

该公开 OA 验证使“无 PDK 时能否跑通 Virtuoso/OCEAN”已有肯定证据；它**没有**解决路线 A 的 CDF/PCell 参数传播。后续应优先在授权的交互式工艺环境核对回调前后实例属性与生成网表，再设计有物理无源约束的源退化和宽带匹配，检查带内/带外稳定性与噪声。达到这些门槛后，才可把真正 LNA 的 SP/noise/HB 接入 `fullchain_eval` 和多智能体候选循环。
