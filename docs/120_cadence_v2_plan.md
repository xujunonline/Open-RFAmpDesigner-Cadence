# 120 Cadence 后端 v2 规划：PDK 器件 + OCEAN 重建 Stage-1 知识库

日期：2026-10-01。**状态：V2-0…V2-7（S1/S2/S4）已执行，结果见 docs/121。**前提：v1（Spectre 宏模型）已在真实 Spectre 25.1 上闭环（docs/119 §4），
网表↔引擎在 S2 上逐点一致（增益/S11/NF/NFmin 差 <1e-9 dB），并有独立 MNA 参考解算器固化为回归测试。

## 1. v1 → v2 的差别

| 层 | v1（已完成） | v2（本计划） |
|---|---|---|
| 晶体管 | `DeviceOP` 小信号宏模型（vccs+caps+噪声源），与代理知识库同源 | PDK nmos 实例（BSIM），偏置由 Spectre DC 求解 |
| Stage-1 知识库 | `repro/device.py` EKV 类代理曲线 | OCEAN 扫 (W, Vb) 得 Id、gm、gds、Cgs/Cgd/Cdb、NFmin、fT、A1dB，写成同一 `DeviceOP` 表 |
| 无源 | 理想 L/R/C + `mutual_inductor`，Q 恒定 | 先保持理想（Q 15/25）；可选 PDK 电感 PCell 或 EM 模型（v3） |
| 压缩 | 节点传函 + 器件限幅模型估计 | Spectre `hb` / `pss+pac` 扫输入功率求真实 IP1dB |
| 偏置网络 | 无（小信号） | 理想电流镜/偏置电阻 + 隔直电容，供电 1.2 V |
| 结论等级 | `not_lna_result=true`，验证引擎 | 仍为"示意 PDK 级"，版图寄生缺失；不得填论文实测位 |

## 2. 分阶段步骤（每步远程动作需你授权；括号内为预计 Spectre 次数与风险）

**V2-0 PDK 盘点（只读，1 次 ssh，无仿真）。** 列出虚拟机上可用的 PDK 名称、模型文件与 corner 段名，
写入**本地私有** `config/model_paths.local.yaml`（不提交、不打印路径）。论文用 TSMC N65；若只有教学 PDK（如 gpdk045/090），
v2 结果按"工艺不同、趋势级"标注。风险：无。

**V2-1 器件卡钩子（离线）。** `render_netlist(..., device="macro"|"pdk")`：`pdk` 时每级晶体管改写为
`M (d g s 0) <model> w= l= nf=` + 偏置源/隔直电容；`DeviceOP` 只用来给初值。单测：网表结构、ASCII、实例唯一。风险：无。

**V2-2 单管表征（约 2×(8 W × 12 Vb) ≈ 200 次 DC+AC+noise，打包成 1–2 个 OCEAN 作业）。** 输出 Stage-1 知识库
`results/repro/pdk_kb/<pdk>/device_table.json`，含与 `device.py` 相同字段；与代理曲线并排出图（gm/Id、fT、NFmin vs 电流密度）。
风险：许可证占用约 10–20 min。

**V2-3 引擎接 PDK 表（离线）。** `device.py` 支持 `TechTable` 插值（同一接口），代理模型保留为默认；
重跑 `bench smoke` 与 S2 设计，确认流程不变。风险：无。

**V2-4 交叉验证（约 3 次 sp+ac）。** 与 v1 相同的 `cadence-check`，但晶体管为 PDK 实例：比较 Spectre 与
"引擎 + PDK 表"的增益/NF/S11，预期差异来自小信号线性化与偏置，判据放宽（增益 ≤1 dB、NF ≤0.5 dB）。

**V2-5 真实压缩点（约 1 次 hb 功率扫，15–25 点）。** `hb` 扫 Pin，求 1 dB 压缩，与估计模型比较并校准
`HARD_CLIP_1DB` / `a1db_v`。

**V2-6 S2 全流程（Stage 4 走 PDK，Stage 2/3 仍用引擎；预计 10–30 次 Spectre）。**
`bench design --spec S2 --backend pdk`，记录多保真分工与等效时间。

**V2-7（可选）S1–S8 各 1 seed。** 约 100–300 次 Spectre，按远程预算与隔离规则执行（现见 CLAUDE.md 规则 2）。

## 3. 需要你决定的事项

1. 是否授权 V2-0 的只读 PDK 盘点（ssh 列目录，不跑仿真）。
2. 许可证/时间预算上限（建议 V2-2～V2-6 合计 ≤ 2 h 墙钟、≤ 400 次 Spectre）。
3. 若虚拟机上没有 65 nm PDK，是否接受用现有教学 PDK 做"工艺不同"的趋势验证。

（以上已决：v1 用原虚拟机上的 TSMC 40 nm LP RF；Spectre 上限先后提高到 550、约 1000；新虚拟机 IC618_rf 为 65 nm LP RF，见 docs/128。）

## 4. 已知的模型差异（v1 实测给出的量级）

- 第一级 Cdb 接源极（引擎）还是接地（物理漏-衬底结）：S2 中心频点增益 −0.44 dB、NF +0.26 dB，
  全带最大差增益 1.8 dB、NF 1.8 dB，S11 深谷由 −40 dB 变为 −23 dB（仍满足 ≤−10 dB）。
  `cadence-check` 现把它作为 `sensitivity_physical_cdb` 一并报告；v2 用 PDK 器件后该近似自然消失。
- IP1dB：引擎用 `Ig/(ωCgs)` 近似第一级 vgs，网表用真实节点电压，差 0.2–0.3 dB。
