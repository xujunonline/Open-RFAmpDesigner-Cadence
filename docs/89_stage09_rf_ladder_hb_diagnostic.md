# Stage 09: 理想输入梯形网络的 HB 压缩诊断

## 来源与执行边界

在 `docs/73_stage09_rf_ideal_ladder_search_and_probe.md` 的已审计候选上，保持六个授权 PDK RF 默认 MOS、三级有源电路、四元件理想输入梯形网络、偏置及 50 Ω 输入/1787 Ω 差分输出参考端口不变，仅从该候选的 **Virtuoso OA 导出网表副本**派生 Spectre 驱动与分析。`run_pdk_rf_ladder_hb.py` 将输入端口的 10 GHz 激励设在 `match_out`，将差分输出端口设为直流端接，并追加 DC、8–12 GHz/161 点 SP/noise 与单频 HB。端口若误接网络内侧 `in`，就绕开匹配网络且可提供输入功率读数相差约 10 dB；第一次归档审计因该错误失败，修正提取参考平面后才通过。失败的计算尝试未删改原始 Spectre 档。

这不是在 Virtuoso 中创建的新匹配网络 OA cell，也没有确认 PDK CDF/PCell 参数传播。四个理想输入元件和其他理想无源尚无实际 Q/SRF、合法几何、EM/PEX 或 DRC 资格。每次 Spectre 为 0 errors、5 条既有 `SFE-1131` 模型配置警告；其含义仍需工艺负责人确认。全部原始网表、模型引用、PSFASCII、日志、Touchstone、指标和清单仅保存在 Git 忽略的 `results/runs/`，不发布商业模型。

## 六点实测与计算

七谐波、10 GHz、相同候选共六个独立 Spectre 驱动点。`audit_pdk_rf_ladder_hb.py` 对每点重新核对 OA 派生来源与远端执行网表、161 点四条复数 S 及 NF/F 与原小信号候选的一致性、六个 MOS 工作点、HB 输出负载电流/电压及端口可提供功率；-70/-50 dBm 的 HB 功率增益与同次 SP S21 差均小于 0.01 dB。各点真实输入功率从 `match_out` 端口的 HB 基波相量计算，非从理想发生器标称值代填。

| 输入可提供功率 (dBm) | HB 功率增益 (dB) | 对六点线性参考的压缩 (dB) |
| ---: | ---: | ---: |
| -70 | -11.9830 | -0.0034 |
| -50 | -11.9839 | -0.0025 |
| -40 | -11.9924 | 0.0059 |
| -30 | -12.0811 | 0.0946 |
| -21 | -12.8597 | 0.8733 |
| -20 | -13.0936 | 1.1072 |

用前三个驱动点拟合的诊断线性参考增益为 **-11.9864 dB**。-21/-20 dBm 两点以 1 dB 间距夹住 1 dB 压缩，按相邻实测点线性插值得 **IP1dB≈-20.458 dBm、OP1dB≈-33.445 dBm**。首份五点汇总把已有约 0.1 dB 压缩的 -30 dBm 纳入前三点，得到 IP1dB≈-20.332 dBm；增补 -40 dBm 后结果移动约 0.126 dB。五点报告保留为线性参考敏感性对照，六点报告是当前首选诊断值。这里的 OP1dB 是同一 1787 Ω 差分端口交付功率，不应与其它负载或参考平面的 OP1dB 混比。

六点首选私有汇总：`results/runs/pdk_rf_ladder_hb_sweeps/20260927T105441Z_1eb1a1c9/`；五点敏感性档：`results/runs/pdk_rf_ladder_hb_sweeps/20260927T105228Z_59b4ce47/`。汇总器重新审计每个源档，输出 CSV/JSON 与证据清单；重算审计必须再次与原始 HB/DC/SP/noise 核对。六个单点来源 ID 记录在私有 `sweep_config.json`，不靠文档数字替代原始证据。

## 不能推广的结论

该电路原小信号全 8–12 GHz 最差 S11≈-6.115 dB、S21≈-25.796 dB、NF≈17.500 dB，明显不是合格宽带 LNA；它与 `docs/88_stage09_rf_diagnostic_fullchain.md` 的**无输入梯形网络**候选不同，压缩点不能互换。单频七谐波 HB 尚未经过谐波阶数/功率步长/多频段/工艺角落全面收敛验证，也没有物理无源或后仿真证据。所有档固定 `not_lna_result=true`、`spec_pass=null`、`physical_qualification=false`、`cdf_callback_validated=false`；不得填论文 Table IV/V 或称作 Fig. 7 原曲线。下一门禁是授权有损无源和可合法配置的有源器件形成明确的新 OA 候选，并完成同候选 fullchain 与物理资格验证。
