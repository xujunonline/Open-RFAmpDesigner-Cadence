# Stage 09：RF 默认器件三级的低驱动 HB 诊断

本页给 `docs/55_stage09_rf_default_device_probe.md` 的授权 RF 默认器件三级 OA 电路增加**同拓扑、同偏置**的大信号数据入口。它仍使用理想电感、互感和电容，没有物理 MCR、合格匹配或 PCell 几何验收；本次只有一个 -70 dBm 输入点，**不提供 IP1dB/OP1dB**，不能作为论文 Table IV/V 或合格 LNA fullchain 结果。

## 电路来源与仿真

以 `results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6/` 中已检查/保存的 OA 源网表为基准，在**新运行目录副本**中只把 50 Ω 输入端口设为 `type=sine dbm=-70 freq=10G`，把 1787 Ω 差分输出端口设为 `type=dc`，追加 DC、161 点 8–12 GHz SP/noise 与 10 GHz/7 谐波 HB。六管、偏置、理想无源和 62 fF 并联负载保持原样；这不是新建的 OA schematic，也没有改动 PDK 或原 OA cell。`src/orfadc/cadence/rf_low_drive_netlist.py` 以字节级派生和唯一端口行检查约束差异。

私有原始档案 `results/runs/pdk_three_stage_fixed/rf_default_hb_20260926T235443Z_9be214c7/` 保存 OA 源副本、派生网表、ADE 伴随文件、远端上传回读、当次 runner、Spectre 日志、DC/OP、SP/noise、混合 50/1787 Ω Touchstone、HB 频域/频率索引/时域 PSFASCII、指标、CSV 和哈希清单。Spectre 完成 **0 errors、5 warnings**；5 条均为此前已有的 `SFE-1131` 重复 `scalefactor` 配置警告，尚未取得工艺负责人解释，不能按无警告签核。

`src/orfadc/experiments/audit_pdk_rf_default_hb.py` 独立重审创建档和既有小信号档 `rf_default_sp_20260926T231333Z_19c5f59b/`，核对派生网表、远端回读、Spectre 实际读取路径、三种 HB 文件类型、Touchstone、六管工作点和原始端口相量。相同频点的四条复数 S、四条噪声轨迹、供电电流及六管工作点与独立小信号基线的数值差为 **0**；文件字节不同是运行头部信息所致，不把它称为同一次仿真。

| 10 GHz 指标 | 原始数据重算 |
| --- | ---: |
| 输入端口可提供功率 | -70.000000 dBm |
| 1787 Ω 差分端口基波交付功率 | -91.748649 dBm |
| HB 交付功率增益 | -21.748649 dB |
| 同次 SP S21 | -21.748727 dB |
| HB 增益减 SP S21 | +0.000078 dB |

功率由 10 GHz 的 `V(outp)-V(outn)` 与 `PORT2:p` 基波峰值相量算出，先核对 `I≈Vdiff/1787 Ω`，再用 `Re(Vdiff·conj(I))/2` 转 dBm。输入功率也从原始 `PORT1` 电压/电流反推，不单凭网表声明。小信号一致性只证明该低驱动点和端口定义连贯，不能推断高功率压缩、宽带稳定、物理匹配或论文结果。

## 复核与下一门槛

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_default_hb `
  results/runs/pdk_three_stage_fixed/rf_default_hb_20260926T235443Z_9be214c7 `
  --create-dir results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6 `
  --baseline-dir results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b
```

只有在授权 PDK 几何、无源耦合 Q/k/SRF、模型告警和匹配门禁落实后，才把同候选 HB 功率扫描及压缩点用于 LNA 规格判断。当前三级带内最差 S21/NF/匹配仍严重不合格；本页仅关闭“RF 默认器件三级是否能完成低驱动 HB 并与 SP 一致”的诊断问题。

后续对**同一不合格诊断电路**进行了单频功率扫描，结果与严格边界见 `docs/57_stage09_rf_default_hb_compression_diagnostic.md`；它仍不构成合格 LNA 压缩点。
