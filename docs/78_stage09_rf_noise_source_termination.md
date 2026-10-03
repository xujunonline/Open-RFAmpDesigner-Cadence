# Stage 09：授权 RF 默认器件的噪声参数与源端接交叉验证

## 为什么做这一项

既有授权 PDK RF 默认器件三级 OA 电路见 `docs/55_stage09_rf_default_device_probe.md`。其 8–12 GHz 输入匹配、S21 和 NF 都不合格；继续凭理想电感搜索难以说明“噪声最优源阻抗”和“增益匹配”之间的约束。本轮**不改六管及无源拓扑**，先从原始 Cadence `sp.noise.sp` 读取未使用过的 `Gopt`、`Bopt`、`RN`、`Fmin`、`F`、`NF`，再把同一 OA 网表副本的输入端口电阻从 50 Ω 唯一改为 100 Ω，独立运行 Spectre DC/SP/noise，检验一个非基线源端接点的分析预测。

原 OA 创建档 `results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6/`、50 Ω 基线 `results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b/` 和 100 Ω 新档 `results/runs/pdk_rf_source_termination/20260927T071510Z_5e906f78/` 均在 Git 忽略的私有目录。新档保留派生网表、伴随文件、wrapper、远端回读、Spectre 日志、PSFASCII、混合参考阻抗 S2P、逐频预测 CSV、指标和证据清单；没有修改 PDK 或旧 OA cell。

## 公式和参考平面

Cadence 原始 PSFASCII 把 `Gopt/Bopt` 标为西门子、`RN` 标为欧姆；定义最优源导纳 `Yopt=Gopt+jBopt`。对实部为正的源导纳 `Ys=Gs+jBs`，使用线性噪声因子：

```text
F(Ys) = Fmin + (RN/Gs) |Ys-Yopt|^2
NF(Ys) = 10 log10 F(Ys)
Γopt = (1/Z0 - Yopt)/(1/Z0 + Yopt)
```

这里 `Z0=50 Ω` 是**原仿真输入参考阻抗**；`Ys=1/100 S` 的源反射系数是 `Γs=1/3`。固定输出端为其原 1787 Ω 端口参考阻抗，即 `ΓL=0`，由原 50 Ω 参考面的复数 S 参数预测**传输功率增益**：

```text
GT(Γs,0) = |S21|^2 (1-|Γs|^2) / |1-S11 Γs|^2
GT_dB = 10 log10 GT
```

Cadence 官方论坛给出 `Gopt/Bopt` 的源导纳与 `Γopt` 换算；[Cadence 噪声圆讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/46898/noise-circles-nc)还使用这些 PSF 噪声迹线。[Keysight 两端口噪声模型文档](https://edadownload.software.keysight.com/eedl/ads/2011_01/pdf/ccsrc.pdf)给出导纳形式的 `F` 方程；[Keysight RF 增益设计说明](https://www.keysight.com/content/dam/keysight/en/doc/gate/white-papers/5990-3356.pdf)给出含源/负载反射系数的 transducer gain 式。这里的 **Cadence 字段定义及数值成立范围仍以本次原始 Spectre 输出和实测交叉验证为准**。

## 独立 Spectre 验证

先用原 50 Ω 源代入原始 161 点 `Fmin/Gopt/Bopt/RN`，重算 `F` 的最大相对误差约 `8.59e-16`。这仅验证基线字段和单位。之后将同一源 OA 网表副本中的 `PORT1 r=50` 改为 `r=100`，其余电路行不变；新 S2P 头部明确为输入 `100 Ω`、输出 `1787 Ω`。两次 DC 原始文件的 76 个数值逐项相同，Spectre 新作业为 0 errors、5 条既有模型配置警告。

| 8–12 GHz/161 点指标 | 原 50 Ω 档 | 新 100 Ω 档 |
| --- | ---: | ---: |
| 最差 NF | 25.570 dB | 22.970 dB |
| 最差 S21 | -33.924 dB | -31.315 dB |

原档逐频预测新档 NF/S21，最大绝对差分别约 `4.62e-14 dB` 和 `1.44e-12 dB`。10 GHz 处预测/实测 NF≈`16.6757 dB`、传输增益≈`-19.0152 dB`；原档 `Γopt` 在 10 GHz 的幅度约 `0.958`。**推断**：噪声最优源点接近 Smith 圆边界；能否用有损、合法 PDK 无源器件在全带实现，尚无证据。把端口电阻直接改为 100 Ω，也不是一个接在外部 50 Ω 系统与 LNA 间的实际匹配网络。

`src/orfadc/cadence/noise_parameters.py` 实现单位、被动源导纳和公式校验；`run_pdk_rf_source_termination.py` 只接受该受控派生；`audit_pdk_rf_source_termination.py` 重审 OA 基线、端口单行差异、远端回读、0-error 日志、161 点噪声和 S2P、DC 一致性，并将 S11/S21/S12/S22 四条复数曲线逐频交叉核对，再重算预测及 CSV。重哈希篡改源网表、原始 S/noise、Touchstone S11、状态或摘要会被拒绝；定向测试 `12 passed`，全量回归 `732 passed, 3 skipped`。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_source_termination `
  results/runs/pdk_rf_source_termination/20260927T071510Z_5e906f78
python -m pytest tests/test_noise_parameters.py tests/test_pdk_rf_source_termination.py -q
```

## 仍未跨过的门禁

这是一点**小信号源端接**交叉验证，不是完整 source-pull 扫描、load-pull、大信号压缩点或物理宽带匹配；未解决输出 S22、带外稳定、实际无源损耗/Q/SRF/耦合、CDF/PCell 合法几何、GDS/DRC、模型警告和角落。`physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`。即使 100 Ω 指标改善，最差 NF 和 S21 仍严重不合格，不能填论文 Table IV/V 或 Fig. 7。下一步应利用此已校准的噪声参数与实测 PDK 无源约束一起设计**有损**输入网络，并同时处理级间/输出匹配；不能继续把无损目标导纳当作可制造候选。
