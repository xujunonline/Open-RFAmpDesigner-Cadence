# RF 指标与来源契约（v1）

本页规定本项目自动评分所需的最小语义，不是论文原始数据。`config/metrics_v1.schema.json` 已提供可机读结果 envelope，`src/orfadc/metric_contract.py` 在被动 runner、OA 教学提取及三级教学探针写入前作运行时语义校验。新实测被动结果见 `results/runs/rf_smoke/passive_noise/20260926T014327Z_bbaff6d2/`；更早的 run 不追溯改写，其中即使写有 `schema_version=1` 也可能缺少后来补入的必填字段。共源诊断已有 Cadence HB/P1dB 数据链，三级公开模型仅有低驱动 HB；**合格有源 LNA** 的 fullchain、压缩点以及 spec/candidate/seed/timeout 端到端记录仍未实现，阶段 01 保持 partial。

| 字段 | 单位/含义 | 当前规则 |
| --- | --- | --- |
| `frequency_band_ghz.low/high` | GHz | 正、有限、递增；整个目标带必须由仿真频率网格覆盖。 |
| `s11_db`、`s22_db` | `20 log10(abs(S11/S22))`，dB | 各自参考端口阻抗下的带内最大值（最差回波）；必须记录端口阻抗，不能把混合参考的 S22 当 50 Ω 回波。 |
| `s21_db` | `20 log10(abs(S21))`，dB | 带内最小值；只在同一输入/输出端口定义和参考阻抗下比较。50/1787 Ω 混合参考的 S21 不等于 50→50 Ω 增益或纯差分电压增益。 |
| `ripple_db` | dB | 带内 `max(S21_dB)-min(S21_dB)`。 |
| `nf_db`、`nfmin_db` | dB | NF 是指定源阻抗条件下的噪声系数；NFmin 是最优源噪声匹配的独立结果，不能由 NF 推断。线性 `F` 转 dB 用 `10 log10(F)`。 |
| `power_ma` | mA | 从供电支路 DC 电流提取，必须记录电源、电流方向及参考条件；不是直流功耗 mW。 |
| `ip1db_dbm`、`op1db_dbm` | dBm | 输入/输出参考平面分别定义；现无真实有源压缩点，保持缺测，不能相互代替。 |
| `stability.minimum_k`、`maximum_delta_abs` | 无量纲 | 直接 Spectre PSFASCII 与补充 S12 的 OCEAN `ocnPrint` 路径均可计算采样网格 `K`、`|Δ|`；`K>1` 且 `|Δ|<1` 在全部采样点成立才标 `unconditionally_stable_on_sampled_grid=true`。缺 S12 则为 null；这不替代带外/角落检查，也不是论文 Table III 的原始规格。 |

频带汇总使用实际扫频点，并在两端以 **log(f)-dB 线性插值** 取得边界值。频带超出已仿真范围、频率非正/不递增、指标非有限时直接拒绝。插值不替代足够密集的 RF 扫频：带内两点之间可能存在未采到的尖峰/谷值；高 Q 网络要提高频率分辨率并做收敛检查。

`simulation_status` 描述 Spectre 是否成功；`spec_pass` 描述规格是否经完整指标验证。`status` 是运行/解析流水线状态，不能与 `spec_pass` 混用。`source`、`circuit_class`、`not_lna_result`、`run_id` 和原始日志共同构成来源链。被动测试必须保留 `circuit_class=passive_twoport`、`not_lna_result=true`、`spec_pass=null`；即使仿真成功也不能作为 LNA 通过。`fullchain_violations` 只允许带 `source=cadence_spectre`、`simulation_status=ok`、`circuit_class=active_lna`、`not_lna_result=false` 且所有必需指标齐全的结果进入已验证评分。这些 JSON 字段本身不能证明运行真实性；未来候选 backend 必须依据独立 run_id 和原始产物构造，不得直接信任 agent 提交的标记。

被动 noise runner 的后续新运行会同时把已解析 S2P 的带内 S11/S21/S22/ripple 与 NF/NFmin 写入 `metrics.json`，但仍强制 `spec_pass=null`。已有带哈希清单的历史运行不追溯改写；只读重算旧 S2P 不能被表述为旧 `metrics.json` 原本包含这些指标。

v1 运行时还要求 `spec_pass=true` 时存在 `spec`、`candidate`、`seed`、`timeout_seconds`、`metrics`、`units`、`reference_planes` 和 `analysis`；候选的 spec ID 与 seed 必须对应，analysis 至少记录 DC、S 参数、noise 与 compression。**即使 `spec_pass=null`，只要携带非空 `candidate` 或 `spec`，也必须同时携带另一方、匹配的 spec ID/seed 和正 timeout**；避免失败候选脱离来源链。`s11_db`、`s21_db`、`nf_db`、`ip1db_dbm`、`power_ma` 的单位必须明确，`fullchain_violations` 复核五项指标确实满足规格。`reference_planes` 兼容旧的共同 `z0_ohm`，新增互斥的 `input_z0_ohm`/`output_z0_ohm` 表达混合参考；`port_reference_ohm` 如存在，须有正、有限的输入/输出数值，且与 `reference_planes` 一致。三级公开教学旧归档仅有 `port_reference_ohm`，不回填或重新声称它们原本带有新的字段。两个被动 runner 的新成功记录显式写入 analysis、单位、50 Ω 参考平面和超时，将不适用的 spec/candidate/seed/violation 写为 null。JSON Schema 表达字段形状和来源条件；跨字段数值关系由 Python 校验，不能仅凭 JSON Schema 或 agent 声称通过。没有**合格 LNA**压缩点的共源/三级教学 run 与没有有源器件的被动 run 均保持 `spec_pass=null`。

远程 runner 现在在 SSH 命令内使用 GNU `timeout` 限定子进程，OCEAN 超时时尝试下载日志。2026-09-26 的一次 OA testbench 仿真在许可证等待阶段超过 300 秒，原 runner 的本地超时留下远端 Spectre；该次进程已针对性结束，日志保存在本地忽略目录。新 timeout 命令已有单元测试和远端 `sleep` 小测试；后续 v4 OCEAN 在远端限时返回，检查未见孤儿进程，但这只覆盖该次超时场景，不能视为所有 Cadence 子进程清理的全面验收。

当前 OA 共源 smoke 有两条独立可核验的数据路径：同一 OA 网表的直接 Spectre PSFASCII 提取，以及经典 + batch OCEAN v5 的 PSFXL 经 `ocnPrint` 导出。后者由 `src/orfadc/cadence/ocean_ascii.py` 检查 47 点的复数 S 参数、NF/NFmin 与 F/Fmin 一致性，再由 `src/orfadc/experiments/extract_ocean_oa.py` 检查成功日志并写出标准化 CSV/JSON。其 `raw_format` 和 `source_run_kind` 与直接路径不同，均不具备 LNA 规格通过所需的压缩点、匹配和正增益。详情见 `docs/20_stage03_active_smoke.md`。

理想无源 v3 的直接 Spectre 探索增加了受限的 `source_run_kind`，不得标为 OA schematic。`src/orfadc/cadence/stability_metrics.py` 基于复数 S11/S21/S12/S22 做采样网格 Rollett K/Δ 检查。现已只读补充导出既有 v1/v2 PSFXL 中的 OCEAN S12，并重新提取各自的稳定性；解析器要求全部曲线的频率与 `resultsDir` 一致，不能将直接 Spectre 或其他 OCEAN 运行的 S12 暗中拼接。`ocnPrint` 精度限制及具体结果见 `docs/23_stage03_stability_cdf_followup.md`。

压缩点的离线提取函数 `extract_p1db` 已接入真实**单管共源诊断** Cadence HB 九点功率扫描，细网格 1 dB 交点和原始数据见 `docs/32_stage04_hb_diagnostic.md`；这不是合格 LNA 结果。输入为同一参考平面下、输入功率严格递增的 `pin_dbm`/`pout_dbm` 行；前至少两点的 `Pout-Pin` 必须在给定容差内建立线性增益基准 `G0`。随后求第一个满足 `G0-(Pout-Pin)=1 dB` 的相邻采样区间，并在功率 dBm 轴上线性插值得 IP1dB 和 OP1dB。没有夹住 1 dB 时返回 `unbracketed` 和 null，不作外推；输出功率倒退时返回 `quality_warning`，即使可计算交点也不得自动判为规格通过。三级公开 MOS1 的 -70 dBm 单点 HB 只验证 1787 Ω 差分端口交付功率与同次 SP S21 相符，见 `docs/47_stage09_three_stage_low_drive_hb.md`；它没有线性基准/高功率夹持，IP1dB/OP1dB 保持缺测。合格 LNA 仍须固定参考平面、同一电路、多点夹持、模型告警和频率/步长核验。

真实被动 S 参数证据见 `docs/14_ideal_twoport_rf_smoke.md`；真实被动 NF/NFmin 证据见 `docs/17_noise_data_pipeline.md`。论文 Table III 的 IP1dB 与正文 OP1dB 口径冲突仍按 `docs/audits/2026-09-25_issue_register.md` 的 A08 保留，不擅自合并。
