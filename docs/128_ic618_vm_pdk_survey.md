# 128 新虚拟机 IC618_rf 的工艺盘点（离线，2026-10-05）

## 1. 背景

- 原虚拟机目录：`RedHat_9_7_A_and_D_10T`。PDK 为 **TSMC 40 nm LP RF**（`crn40lp`，`toplevel.scs section=top_tt`，RF 管 `nmos_rf`，docs/121 V2-0）。docs/121–127 的全部 PDK 结果都基于它。
- 新虚拟机目录：`F:\IC618_rf`。需要确认改用它后可用的工艺。

## 2. 方法（只读，不开机，不用 Spectre）

- `IC618_rf.vmx`：客户机 CentOS 7 64 位，4 vCPU，8 GB 内存，NAT 网络，名称 IC618_rf（Cadence IC 6.1.8）。
- 对 18 个非空虚拟磁盘分片（`IC618-cl1-s0xx.vmdk`，共约 70 GB）做 `strings | grep` 文本扫描，只统计 PDK 名称、模型文件名、器件名、安装路径。
- 未挂载文件系统，所以只能证明"磁盘上存在这些文件/字符串"，不能证明 cds.lib 已注册或许可证可用；最终以开机后的 `bench pdk-inventory` 为准。

## 3. 结果

| 工艺 | 证据（磁盘字符串） | 与本项目的关系 |
|---|---|---|
| **TSMC 65 nm LP RF（`CRN65LP`，PDK v1.7a，IC61，2012-09-14）** | 路径 `/home/IC/Desktop/tsmc/tsmc65nm-virtuoso61OA/PDK_CRN65LP_v1.7a_Official_IC61_20120914…`；techfile `tsmcN65`（1p8m/1p9m 等金属方案）；模型 `crn65lp_2d5_lk_v1d7.scs`、`crn65lp_3d3_lk_v1d5.scs`、`../models/spectre/toplevel.scs`；统计/失配段 `stat_mis_rfmos_*`、`rfmvar`、`rfres`；RF 管 `nmos_rf`、`nmos_rf_lvt/hvt/mlvt`、`nmos_rf_6t`、`nmos_rf_25/33`、`nmos_rf_cas/diff/cross` 等；螺旋电感模型 `TIF-CRN65LP_1D5-spiral_sym_*` | **与论文同为 N65**（论文用 TSMC N65 后仿）；RF 管命名与 crn40lp 相同（`nmos_rf`），后端改动小；带 PDK 螺旋电感，可替代理想无源 |
| SMIC 65 nm LL RF（`smic65llrf_121825_2tm`） | `rf_mosfets.Cat`、`varactors.Cat`、`rf_resistors.Cat` | 备选 |
| SMIC 0.13 µm mixed-mode RF（`PDK_13mmrf_1P6M_30k/smic13mmrf_1233`） | `diff_ind_rf_pgs_psub` 等 | 节点太老，不适合 30–50 GHz |
| TSMC 0.18 µm RF（`tsmc18rf_pdk_v13d`） | 桌面上的压缩包 | 同上 |
| SMIC 0.18 µm（`smic18ee`、`smic18mm`） | 器件函数名 | 同上 |
| Cadence 通用 `gpdk090`、`gpdk045` | 大量字符串 | 教学 PDK，非 TSMC |

**结论：改用 IC618_rf 后，可用的 TSMC 工艺是 TSMC 65 nm LP RF（CRN65LP / tsmcN65，PDK v1.7a）**，即论文所用的 N65 节点。
另有 TSMC 0.18 µm RF，但不适合本项目的 mm-wave 频段。

## 4. 对项目的影响与下一步

1. 开机 IC618_rf，确认 IP 与登录方式；更新本地私有 `config/remote_cadence.local.yaml`（用户自行填写，不提交）。
2. `bench pdk-inventory`（只读，0 次 Spectre）：确认 cds.lib 中的库名、`toplevel.scs` 路径与 section 名（如 `top_tt`）、`nmos_rf` 参数名（`lr/wr/nr/multi`）与取值范围，写入 `config/model_paths.local.yaml`。
3. 若一致，PDK 流程（docs/120–127）可整体迁移到 N65：重新表征器件表（`pdk-characterize`、`-characterize3`），再按论文口径重跑 S1–S8。
4. CRN65LP 带螺旋电感模型（`spiral_sym_*`），可用于替代理想 Q 的匹配电感——这正是 docs/126 中 S7 的瓶颈所在。
5. 结果仍须注明"原理图级、无版图寄生"，与论文的后仿不同。

部分压缩包文件名显示来自论坛下载；PDK 的使用授权由用户自行确认。
