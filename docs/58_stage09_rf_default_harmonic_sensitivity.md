# Stage 09：RF 默认器件三级的 HB 谐波阶数敏感性

接续 `docs/57_stage09_rf_default_hb_compression_diagnostic.md` 的 7 谐波、7 输入功率扫描。本次只在其 10 GHz、-11/-10 dBm 的 1 dB 夹点附近补跑 9/11 谐波各两点；原有 7 谐波两点不重复仿真。六点均对应**同一个授权 PDK RF 默认器件三级 OA 源网表**，只在受控副本中改变端口功率与 HB 阶数。理想无源、偏置和六管连接保持不变。

每个新增点为独立 Spectre DC/SP-noise/HB 运行，日志 0 errors、5 条既有 `SFE-1131` 模型配置警告。逐点审计从原始 HB 基波相量重算输入可提供功率和差分 1787 Ω 电阻负载交付功率，核对 OA 来源、网表派生/远端回读、SP/noise 基线、六管工作点、CSV/JSON 与 SHA-256 清单。聚合报告 `results/runs/pdk_rf_harmonics/20260927T004019Z_b943aa87/` 存六个源 run ID、清单摘要和比较矩阵，审计器再次逐点核验原始档案后重算报告；报告本身不是新的仿真运行。

| Pin (dBm) | 7 谐波增益 (dB) | 9 谐波增益 (dB) | 11 谐波增益 (dB) |
| ---: | ---: | ---: | ---: |
| -11 | -22.638761595 | -22.638792688 | -22.638795510 |
| -10 | -22.899905197 | -22.899962282 | -22.899968666 |

同一功率下 7→9 阶最大差约 `5.71e-5 dB`，9→11 阶最大差约 `6.38e-6 dB`。以每点同次 SP `S21`（约 `-21.748727 dB`）为小信号参考，在 -11/-10 dBm 两点间插值，7/9/11 阶的**局部诊断级**输入 1 dB 交点分别约 `-10.578908/-10.579069/-10.579085 dBm`，相对 7 阶的最大变化约 `0.000178 dBm`。该参考与 `docs/57` 用前三个低驱动 HB 点平均值所得 `-10.579083 dBm` 不同，不能将两种计算无说明地混合。插值不等于在交点直接运行 Spectre。

只读重审：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_default_harmonics `
  --audit-dir results/runs/pdk_rf_harmonics/20260927T004019Z_b943aa87 `
  --create-dir results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6 `
  --baseline-dir results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b
```

结论只适用于这个**严重失配、不合格**电路的 10 GHz、两个输入功率点、7/9/11 阶设置。9/11 阶没有重新跑完整低驱动线性参考；未检验全功率/全频段谐波收敛、非基波端口功率、功率参考平面误差、角落或模型有效范围。理想线圈/互感未通过 Q/k/SRF 或 EM/PEX 资格，RF MOS 的 CDF/PCell 合法几何未验证，模型警告也待授权工艺负责人解释。全部源点和报告保持 `not_lna_result=true`、`spec_pass=null`；不得填入论文 Table IV/V 的 LNA 压缩点。
