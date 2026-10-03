# 121 Cadence v2 实测：PDK RF 晶体管 + Spectre 的 S1/S2/S4 设计（2026-10-01）

按 docs/120 授权执行（只读 PDK 盘点 + Spectre 预算 ≤2 h / ≤400 次）。全部远程动作经 `RemoteRunner`，
在 Windows 宿主用 `scripts\run_job_queue.cmd`（读取 `scripts\jobs\queue.txt`，只接受 `orfadc.repro.bench` 子命令）执行。

**保密边界：** PDK 路径与器件表只存在于 git 忽略的 `config/model_paths.local.yaml`、`results/runs/`；
`results/windows_checks/` 也已加入 `.gitignore`（其中的设计 JSON 含由 PDK 表插值得到的器件参数）。本文只给汇总指标。

## 1. 步骤与用量

| 步骤 | 命令 | Spectre 次数 | 结果 |
|---|---|---|---|
| V2-0 PDK 盘点（只读） | `bench pdk-inventory`（2 轮） | 0（2 次 ssh） | 找到 TSMC 40 nm LP RF PDK（`crn40lp`，`toplevel.scs section=top_tt`，RF 管 `nmos_rf`，`lr/wr/nr/multi` 参数；模型带 0.9 shrink）；早先 ADE 网表的 include/实例写法一致 |
| V2-2 器件表征 | `bench pdk-characterize`（Vds=1.1 V 与 0.5 V 两张表） | 82 | 16 个宽度 × 9–13 个 Vgs：DC 扫描得 Id/gm/a1dB，2 端口 S 参数（5、30 GHz）得 gm、gds、Cgs、Cgd、Cdb、Rg、fT，噪声分析得 NFmin@30 GHz |
| V2-3 引擎接 PDK 表 | `device.set_device_provider(PdkProvider)` | 0 | 器件、偏置网格、VDD 都换成 PDK 表；级联管用低 Vds 表、CG 管宽度比改为 1.0 |
| V2-4/5 交叉检查 | `bench pdk-check --spec S2` | 4 | 见 §3 |
| V2-6/7 设计 | `bench design --spec S1/S2/S4 --backend pdk` | 21 | 全部通过，见 §2 |
| 合计 |  | **≈107 次，远程墙钟约 95 min** |  |

## 2. Spectre 判定的设计结果（rule 策略，seed 0）

内环（Stage 2/3）在"PDK 表驱动的两端口引擎"上搜索，Stage 4 全链评估由 Spectre 完成：
PDK `nmos_rf` 晶体管 + 理想无源/偏置（Q=15/25 的电感、理想耦合、理想偏置源与隔直），
IP1dB 由 HB 输入功率扫描（−50…−5 dBm，19 点）实测，功耗由 Spectre 直流工作点的各支路电流计算
（第一级单端 + 第二、三级差分对按两倍计）。

| 规格 | 通过 | 带内最小增益 (dB) | 纹波 (dB) | NF@fc (dB) | 带内 S11 最差 (dB) | IP1dB HB (dBm) | 实测电流 (mA) | Stage-4 Spectre 次数 |
|---|---|---|---|---|---|---|---|---|
| S1（10 GHz, 20%） | ✅ | 23.0 | 0.6 | 4.66 | −11.5 | −14.5 | 25.9 | 7 |
| S2（30 GHz, 20%） | ✅ | 26.3 | 2.0 | 3.53 | −11.8 | −15.5 | 25.5 | 3 |
| S4（30 GHz, 10%） | ✅ | 22.8 | 2.7 | 3.38 | −14.0 | −11.7 | 25.4 | 4 |

（三个规格均要求 25±3 dB、NF ≤ 5 dB、IP1dB ≥ −25 dBm、≤ 30 mA、S11 ≤ −10 dB。）

结论等级：**PDK 晶体管级（示意）**——器件来自真实 RF 模型，但电感/耦合/偏置为理想元件、无版图寄生，
仍不能填论文 Table IV 的实测位；与 v1（宏模型）相比，这是第一次由商用器件模型判定"满足规格"。

## 3. 引擎（PDK 表）与 Spectre（PDK 实例）的差异

| S2 同一设计 | 增益@fc | S11@fc | NF@fc | IP1dB | 说明 |
|---|---|---|---|---|---|
| 第 1 次（单张 Vds=1.1 V 表，CG 宽度比 0.45） | 引擎 26.7 / Spectre 13.3 | −31 / −16 | 3.9 / 9.2 | −24.3 / −5.9(HB) | 第一级被级联管"饿死"：CG 管太窄、Vgs 太大，CS 管 Vds 不足；由实测总电流推算第一级只有约 5 mA（计划 11 mA） |
| 第 2 次（低 Vds 表 + CG 宽度比 1.0） | 26.0 / 25.3 | −41 / −8.5 | 4.8 / 3.0 | −23.8 / −15.5(HB) | 中心增益差 <1 dB；引擎 NF 偏悲观约 1.7 dB；输入匹配与带内纹波差异仍大 |

剩余差异的来源（下一步）：

1. **输入匹配：** 表中 Cgs 由 Y11 虚部提取，含栅-衬底电容与 RF 管内部栅电阻的分布效应；引擎用"Rg + Cgs + gm·Ls"
   的集总模型，导致实部匹配点偏移。改进：直接用表里 30 GHz 的 Y 参数（而非集总 Cgs/Rg）构造第一级。
2. **噪声：** 引擎沿用 γ=1.1、δ/γ=2 的经典模型，比 PDK 噪声模型悲观；可用表中 NFmin 拟合 γ。
3. **压缩：** 引擎/网表的估计模型（gm 压缩 + 削顶）比 HB 实测悲观 8–10 dB；应以 HB 为准并重新标定 `HARD_CLIP_1DB`、`a1db_v`。

即便如此，设计循环在 1–2 次细化内用 Spectre 反馈收敛到合格设计，体现了论文"低保真内环 + 高保真终验"的分工。

## 4. 代码与测试

- `repro/pdk_v2.py`：盘点（`pdk_inventory.sh`）、表征（`characterize`）、`PdkTable`/`PdkProvider`、
  `render_pdk_netlist`（偏置 T、隔直、理想反相器 + 电容的中和、HB 扫描）、`PdkCadenceBackend`（测量支路电流与 HB IP1dB）。
- `repro/device.py`：`set_device_provider`/`vdd()`/`device_source()`；`circuit.cascode_device` 读取提供者的 `cascode_ratio`。
- `repro/tools.py`：Stage 4 若有实测电流，功耗约束用实测值（`power_ma_planned` 另存）。
- `bench`：`pdk-inventory`、`pdk-characterize [--vds]`、`pdk-check`、`design --backend pdk`。
- 测试 `tests/test_repro_pdk_v2.py`（8 项：盘点解析、版图选择、网表结构、Y 提取回环、HB 解析、提供者插值与恢复、级联低 Vds 表）；全量 748 passed。

## 5. 原始档

- 器件表：`results/runs/pdk_char/20261001T172426/`（Vds=1.1 V）、`20261001T180131/`（Vds=0.5 V）
- Spectre 设计运行：`results/runs/repro_cadence_pdk/<run>/simNNNNN/`（netlist、psf、metrics.json，含支路电流与 HB 扫描）
- 作业日志：`results/windows_checks/20261001T1751*_job`、`…180128_job`、`…182315_job`
