# 论文到结果的双向追踪

状态缩写：`V` 有原始实测证据，`T` 纯 Python 测试覆盖，`S` 骨架或模板，`X` 缺失，`B` 当前外部条件受阻。证据为 2026-09-25 本地快照。论文原件定位见 `2026-09-25_paper_claims_matrix.md`。

| 论文/任务 | 规格和数据契约 | 工具/代理 | Cadence 输入 | 原始数据 -> 标准化 | 结果/文档 | 状态与断链 |
| --- | --- | --- | --- | --- | --- | --- |
| Table III S1-S10 | `config/specs_table_iii.yaml`, `schemas.Spec` | `run_spec.py` | 无 | dry-run candidates JSON | `results/runs/S1/seed0/` | T；只生成候选，不仿真。 |
| Table II Stage 2 | `config/variable_ranges_table_ii.yaml` | `impedance_matching.py` | `run_sparam.ocn` 是注释模板 | 无真实关键级 NF/S11 | `stage2_cost()` | T/S；参数到仿真断开。 |
| Table II Stage 3 / Eq. (3) | 同上 | `band_planning.py` | 无 MCR 网表 | 无模型校准数据 | 低保真评分接口 | S/X；论文公式 (3)、SA、Cadence 校准缺失。 |
| Table I Active sizing | `power_ratio_list`, `power_ma` | `active_sizing.py` | 无 PDK lookup 表征 testbench | 无器件数据库 | `lookup_status=missing` | T/S；功率比例不能变成真实 W/VGS。 |
| Table I Fullchain | `SimResult`, `fullchain_violations` | `fullchain_eval.py` | `run_fullchain.ocn` 是模板 | 无完整 PSF/CSV | 明确 `not_implemented` | S/X；禁止 pass。 |
| 被动二端口方法验证 | `circuit/spectre/ideal_twoport.scs` | `run_ideal_twoport.py` | 50 ohm 端口、RLC、`sp` | `ideal_twoport.s2p` + `sp_test.sp` -> `sparams.csv` | `metrics.json`, `docs/14` | V；47 点，S21 复数最大差约 1.5e-16。新一次 SSH 超时未复验。 |
| Noise/NF/NFmin | 本地 `noise_metrics.py` 有单位/频率/缺测合同 | `extract_noise.py` 仅规范化已有 PSFASCII | `run_noise.ocn` 是模板，另有未验证的 SP-noise 网表 | 人工样例 -> CSV，尚无真实 noise 原始数据 | `docs/17_noise_data_pipeline.md` | T/S/X；不能报告 LNA NF 或 NFmin。 |
| IP1dB/OP1dB | `SimResult` 字段已有 | 无压缩点提取 | `run_compression.ocn` 是模板 | 无 | 文档计划 | X；论文 IP/OP 歧义须单独处理。 |
| Manager/Searcher/Refiner | `Candidate`, `Spec` | 三个 Python 类 | 不直接调用 Cadence | 无 agent observation | `run_spec.py` 仅 dry-run | S；Refiner 已防止缺测接受，队列与预算未闭环。 |
| KB/EB 与 RAG | `JsonlMemory` | 仅 JSONL 读写 | 无 | 无真实历史设计记录 | `docs/agent_system/` | S；无检索/经验验证。 |
| Table IV/V/VI-like | `sweep_settings.yaml` | baseline/experiment 模块占位 | 无 10x5 运行 | 无 | 无真实表 | X。 |
| Fig. 7-11-like | 图文件模块仅 docstring | plot 模块占位 | 无多任务数据 | 无 | 无真实图 | X。 |

2026-09-25 后续复验补记：被动二端口的新 runner 在 `results/runs/rf_smoke/ideal_twoport/20260925T152506Z_273884f2/` 实际完成 Spectre 47 点并归档；原表中的“新一次 SSH 超时未复验”只描述审查当时的失败 run，不再是当前状态。OCEAN 环境复验亦为 `ok`。这不补齐 LNA/noise/压缩点断链。

2026-09-26 再次轻负载复验补记：SSH/Tools/SCP 和二端口 `sp` 在 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/` 成功。前一日短时恢复后的复发仍保留为 A09 观察项；不能据此反推 noise/LNA 已闭环。

## 数据流校验

现有唯一闭环为：`ideal_twoport.scs` -> 远程 Spectre `sp` -> `s2p`/PSFASCII -> Touchstone parser -> `sparams.csv`/汇总 -> `metrics.json`。这条链不经过 Virtuoso schematic，也不经过 LNA 工具中间件或 agent。`metrics.json` 中标明 `not_lna_result=true`；审查修复后新增 `spec_pass=null`，每次运行独立归档。

反向追溯：论文 Table III 的 `S1` 可追溯至 YAML 与 dry-run 候选，但到真实 Cadence LNA 仿真为止链条尚未建立。论文 Fig. 7 的曲线不能从本项目当前 `results/` 反向追溯，因此任何标为 Fig.7-like 的未来图都必须使用新的真实运行 ID 和原始频响文件。
