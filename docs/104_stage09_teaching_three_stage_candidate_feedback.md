# Stage 09：公开三级 RF 教学电路的一步候选反馈

## 目的与边界

本轮把既有的六 MOS 三级公开 MOS1 直接 Spectre 测试电路，接入受限 `Candidate`/`Spec`、独占运行目录、证据清单和 S1 带内观察。首次候选为输出耦合副边 `L3S=2.0 nH`、`CTUNE=0 fF`。根据 10 GHz 与输出负载的 62 fF，用 `L=1/((2πf)^2 C)` 给出一次 `4.085532 nH` 的**启发式**反馈。这个公式只提供第二次仿真的起点：真实副边含理想互感和其他电路负载，不等同于孤立 LC 谐振器，更不能保证匹配或规格通过。

电路使用公开简化 MOS1、理想互感和直接 Spectre 网表，**不是**授权 PDK 器件物理验收、Virtuoso OA 完整闭环、论文 MCR 或论文三级 LNA。只运行 DC、SP 和 SP-noise；没有在这两个候选上运行 HB/PSS 压缩点。因此两者始终 `not_lna_result=true`、`spec_pass=null`、`compression_status=not_measured`。不填 Table IV/V 或 Fig. 7。

输入端口参考阻抗 50 Ω；差分输出端口参考阻抗 1787 Ω，旁路负载电容 62 fF。下表 S21 是这两个不同参考阻抗之间的散射波比，不是 50→50 Ω 增益或内部差分电压增益。它与既有 `docs/45_teaching_three_stage_spectre_probe.md` 的全 8–12 GHz 最差值也不应直接比较：本表只统计 S1 的 9–11 GHz。

## 运行与证据

- 首候选私有归档：`results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_l3s2/20260927T180217Z_33e94f02/`。
- 第二候选私有归档：`results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_resonance/20260927T181057Z_e00d2e47/`。
- 两轮反馈记录：`results/runs/teaching_three_stage_feedback/20260927T181057Z_e080745d/`。其中 `proposal.json` 保存首轮清单哈希、原始观察和第二轮计划；`feedback_summary.json` 可只读重算。
- 每个候选目录保留本地/远端网表、公开模型副本、Spectre 日志、PSFASCII、Touchstone、`waveforms.csv`、`metrics.json`、`candidate.json` 和带哈希清单。两个 Spectre 作业均返回 0；第二份日志终结行为 0 errors、0 warnings。`metrics.json` 的 `ok_with_warnings` 是教学提取器保留的非资格状态，不表示 Spectre 有告警或设计达标。
- 来源审计先从原始文件重提取 161 个 8–12 GHz 点，再在 S1 的 9–11 GHz/81 点上形成最坏指标。它核对候选、规格、运行 ID、参数和每份原始文件哈希；反馈审计再次重算两侧观察，拒绝汇总/来源篡改。

| S1 9–11 GHz 指标 | `L3S=2.0 nH` | `L3S=4.085532 nH` | 解释 |
| --- | ---: | ---: | --- |
| 最差 S11 (dB, 越低越好) | -14.2209 | -14.2209 | 基本不变 |
| 最差 S21 (dB, 越高越好) | -1.2099 | 1.6772 | 提高 2.8872 dB，仍远低于 25 dB 目标 |
| 最差 S22 (dB, 越低越好) | -0.9481 | -2.0717 | 改善 1.1236 dB，仍严重失配 |
| 最差 NF (dB, 越低越好) | 5.6635 | 5.6635 | 几乎不变，仍高于 5 dB 目标 |
| S21 纹波 (dB, 越低越好) | 9.7223 | 8.4521 | 改善但仍很大 |
| 电源电流 (mA) | 14.8849 | 14.8849 | 未调有源偏置 |

这个对照只支持“**在此公开教学电路的单个受限候选上，副边 L 的一次反馈改善了带内最差 S21/S22**”。它不支持“宽带 LNA 已完成”“MCR 调谐已验证”“S1 通过”或“Refiner/EB 优于基线”。输入 S11 的相近值也不能推断端口匹配独立于负载：这里只是所测两点的事实。

`S22 > -10 dB` 是本项目反馈脚本采用的局部输出失配触发阈值，不是 `config/specs_table_iii.yaml` 中单列的论文任务约束。S1 表内要求的增益 25 dB、NF 上限 5 dB、电流预算 30 mA 和 IP1dB 下限 -25 dBm 分开判断；本轮增益/NF 不满足，电流虽低于预算但 IP1dB 缺测，因此绝无总体 pass。

## 可执行与恢复

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.observe_teaching_three_stage_candidate results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_l3s2/20260927T180217Z_33e94f02
python -m orfadc.experiments.run_teaching_three_stage_refinement --audit-trace results/runs/teaching_three_stage_feedback/20260927T181057Z_e080745d
python -m pytest -q --basetemp="results/runs/pytest_teach3_feedback_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_run_teaching_three_stage_refinement.py tests/test_teaching_three_stage.py tests/test_observe_teaching_three_stage_candidate.py
```

`run_teaching_three_stage_refinement --first-dir <新首候选目录>` 只适用于**新的**、已审计、未调谐、低于目标且输出失配的 S1 教学候选；每次运行会创建新的候选 ID/运行 ID。不要对上面已完成的 trace 再派发。此段记录创建时的不确定派发状态；后续新候选的 v3/v4 派发身份、干净远端结果恢复和第二轮只读收尾已经实现并实测，见 `docs/105_stage09_three_stage_remote_recovery.md`。本节两个旧候选没有事前持久化的远端计划，不能事后冒充可恢复协议；任何不确定状态仍禁止自动重派。

## 下一门禁

新候选已有事前持久化远端身份和干净原始档的不重派恢复；下一步是将该协议接入确定性 Manager 的 planned journal、补 pending 对账和终态失败/截断档隔离，之后才能安全调度三级 Searcher/Refiner。还需补同候选的真实压缩点/全带稳定性判定；软件流转不能提升电路资格。实际 LNA 还需授权 PDK 的 CDF/PCell 参数传播、合法且有损的无源耦合网络、适用 DRC/版图及模型警告核实、角落/EM/PEX，再执行统一参考平面的 fullchain。上述门禁未满足前，Stage 09/10/全项目继续 `partial`。

后续工作已另起**新** planned agent 双候选归档并补其第二轮同参数 HB 压缩诊断，见 `docs/106_stage10_three_stage_planned_agent.md`、`docs/107_stage09_teaching_agent_same_candidate_hb.md`；本文件所述的原始两档不因后续新样本而回填压缩点，物理与合格 LNA 门禁仍未通过。
