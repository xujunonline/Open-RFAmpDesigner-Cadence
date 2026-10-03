# Stage 09：RF 默认器件三级的 HB 压缩诊断

接续 `docs/56_stage09_rf_default_low_drive_hb.md`，对**同一个授权 PDK RF 默认器件三级 OA 源网表**建立 10 GHz 输入功率扫描。每点仅在新的网表副本上设置输入端口功率，输出仍为 1787 Ω 差分端口并联 62 fF；六管、偏置和理想无源网络不变。它是**严重失配、增益/NF 不合格的诊断电路**，不是合格 LNA，也不是论文 TSMC N65 结果。

## 原始扫描与来源

- 以已审计的 OA 创建档 `rf_default_create_20260926T231047Z_38b59de6/` 和独立小信号档 `rf_default_sp_20260926T231333Z_19c5f59b/` 为双基线。
- 7 个输入点为 -70、-60、-50、-30、-20、-11、-10 dBm；每一点都是独立 Spectre DC/SP-noise/HB 运行，7 谐波，0 errors、5 条同类 `SFE-1131` 模型配置警告。-70 dBm 沿用原始低驱动档，不重复计为新优化样本。
- `src/orfadc/cadence/rf_low_drive_netlist.py` 限制端口派生；`src/orfadc/experiments/audit_pdk_rf_default_hb.py` 对每点从原始 HB 相量重算输入可提供功率、差分电阻负载交付功率，并逐频比较该点 SP/noise 和独立基线。各点还保存 OA/派生源、远端回读、日志、工作点、三种 HB PSFASCII、Touchstone、CSV/JSON 与哈希清单，全部位于 Git 忽略的 `results/runs/pdk_three_stage_fixed/rf_default_hb_*/`。
- 整体归档 `results/runs/pdk_rf_hb_sweeps/20260927T002112Z_84e382b1/` 保存点 ID、各点清单哈希、`power_sweep.csv`、`metrics.json` 与整体清单。`audit_pdk_rf_default_hb_sweep.py` **重新审计每个源点**并重算插值；不以已有 JSON 数值代替 HB 原始数据。

| Pin (dBm) | Pout (dBm) | 相对线性增益压缩 (dB) |
| ---: | ---: | ---: |
| -70 | -91.74865 | -0.00003 |
| -60 | -81.74866 | -0.00002 |
| -50 | -71.74874 | 0.00006 |
| -30 | -51.75758 | 0.00890 |
| -20 | -41.83966 | 0.09098 |
| -11 | -33.63876 | 0.89008 |
| -10 | -32.89991 | 1.15122 |

前三点建立的线性参考增益约 **-21.748681 dB**，其离散远小于 `extract_p1db` 的 0.2 dB 容差。首次跨越 1 dB 的相邻实测点为 -11 与 -10 dBm，宽度 1 dB。按这两点之间的**线性插值**得到本电路的诊断级 **IP1dB≈-10.579 dBm、OP1dB≈-33.328 dBm**。这不是直接量到恰好 1 dB 的一个 Spectre 点；数值精度受扫频间距、HB 谐波阶数和模型影响。聚合器对未夹住或超过 2 dB 的粗夹持区间保留 null，不输出伪精确值。

## 使用限制

`not_lna_result=true`、`spec_pass=null`；所有线圈和互感仍为理想器件，RF MOS 尺寸只用默认 CDF 参数，没有回调/PCell、物理耦合 Q/k/SRF、EM/PEX 或角落验证。模型重复 `scalefactor` 警告未获工艺负责人解释。夹持点的 9/11 谐波**局部**敏感性已见 `docs/58_stage09_rf_default_harmonic_sensitivity.md`；功率参考平面误差、全功率/全频段谐波收敛和温度/工艺适用性仍未认证。因此只能说“在本次 Cadence 诊断设置下获得带原始证据的单频压缩趋势”，不能填入论文 Table IV/V 的 LNA IP1dB/OP1dB，也不能宣称 Stage 09/fullchain 已完成。

可只读重审整体报告：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_default_hb_sweep `
  --audit-dir results/runs/pdk_rf_hb_sweeps/20260927T002112Z_84e382b1 `
  --create-dir results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6 `
  --baseline-dir results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b
```

下一门槛是授权工艺无源与 RF 几何资格，以及匹配/噪声/稳定性合格的**新候选**。只有该新候选完成同电路、同参考平面的 SP/noise/DC/HB 和原始数据审计，才进入规格级 fullchain。
