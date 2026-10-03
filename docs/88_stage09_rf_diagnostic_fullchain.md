# Stage 09: 既有授权 RF 三级的只读全链诊断

## 目的与来源

对 `docs/55_stage09_rf_default_device_probe.md` 的默认 RF 器件三级 OA 源，以及 `docs/57_stage09_rf_default_hb_compression_diagnostic.md` 的同电路 HB 扫描，建立一个**不发新仿真**的可重审诊断观察。`aggregate_pdk_rf_diagnostic_fullchain.py` 先分别重新审计 OA→DC/SP/noise 原始 PSFASCII 与七点 HB 原始相量、源清单和同一默认几何签名，再从小信号原始行按 Table III S1 的 **9–11 GHz** 带宽重新计算 81 点最差指标。HB 压缩仅为 10 GHz 单频插值。第一次聚合因参考平面/候选 schema 不符而在清单写入前失败，失败档保留；修正后的私有汇总 `results/runs/pdk_rf_diagnostic_fullchain/20260927T103033Z_127b9b3e/` 只读审计为 `verified_diagnostic_only`。

| S1 频带诊断指标 | 本电路原始档重算 |
| --- | ---: |
| 9–11 GHz 最差 S11 | -0.284 dB |
| 9–11 GHz 最差 S21 | -27.931 dB |
| 9–11 GHz 最差 NF | 22.314 dB |
| 9–11 GHz 增益纹波 | 7.329 dB |
| 10 GHz 诊断 IP1dB / OP1dB | -10.579 / -33.328 dBm |
| 供电电流 | 9.825 mA |

以项目 Stage 2 的 **-20 dB S11 诊断目标**和 S1 的增益/NF/IP1dB/电流限值计算，S11、增益、NF 的数值 violation 分别约为 19.716、52.931、17.314 dB；压缩点与电流的数值 violation 为 0。这**不是**论文 Table III 中新增了 S11 列，更不是规格通过：`fullchain_violations` 强制输出 `unverified_score`、`pass=false`，聚合档固定 `not_lna_result=true`、`spec_pass=null`、`physical_qualification=false`、`cdf_callback_validated=false`、`model_warning_resolved=false`。失配严重、理想无源未有 Q/k/SRF/EM 资格、现有 DRC 违规和五条模型配置警告仍未获工艺签核，且 HB 只在中心频率做了局部谐波核查。

本档**没有当前 agent candidate 身份**，不能送入 `AgentToolRegistry.fullchain_eval` 当成任意候选的结果，也不能喂给要求合格有源 LNA 的 `Refiner` 以解除其原始证据门禁。它用于证明同电路原始数据如何组成失败报告，并量化接下来的匹配/增益/NF 缺口；不是新优化样本、合格 LNA、Fig. 7 曲线或 Table IV/V 数值。独立审计重算源档并拒绝重哈希后的指标、来源和参考平面篡改；伪造 `spec_pass=true` 无法通过通用证据清单构建。下一步仍需对**新且明确的候选**完成参数→OA/网表→物理资格→DC/SP/noise/HB 同次绑定，再向 agent 开放真实 fullchain 工具。
