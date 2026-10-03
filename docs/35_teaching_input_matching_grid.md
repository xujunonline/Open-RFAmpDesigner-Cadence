# 阶段 07 路线 B：NF/S11 输入匹配九点网格

2026-09-26。在 `docs/33_stage03_teaching_mos1_route_b.md` 的公开 MOS1 单管教学测试台上，以固定 `VBIAS=0.65 V`、`LDD=2 nH`、`CBLOCK=5 pF` 运行输入串联 `LGS` 与源退化 `LSS` 的 3×3 网格。电路、模型、MOS W/L、50 Ω 参考平面、8–12 GHz 诊断频带均保持不变。此项是**直接 Cadence Spectre 的教学方法验证**，不是论文的三级 LNA、授权 PDK 器件或 Table I 完整 Impedance Matching 工具。

## 目标与执行

按论文式 (1) 的现有 `stage2_cost()`，本次明确采用**自定教学目标** `NF_user=2.0 dB`、`NF_headroom=0.2 dB`，故带内最差 NF 约束为 `≤1.8 dB`；S11 约束沿用函数中的 `≤-20 dB`。`nf_violation=max(0,NF_worst-1.8)`、`s11_violation=max(0,S11_worst+20)`，`cost=1000(nf_violation+s11_violation)`。这是排候选的诊断 cost，不是论文 Table III S1–S10 的任何正式通过判定。

`run_teaching_lna.py` 现在只允许 `LGS=0.2..2 nH`、`LSS=100..500 pH` 的白名单数值变化，并把实际值写入 metrics；`audit_teaching_lna.py` 对照原始网表检查参数。`run_teaching_input_grid.py` 在目录创建前验证网格、最多 12 点和 NF 目标；每点独立做宿主物理内存门禁、SSH/Spectre DC/工作点/SP/noise、0-error/0-warning 检查、PSFASCII/Touchstone 提取及清单。只有逐点只读审计通过才计算 cost；一旦后端失败或资源门禁不满足即停止、记录 `incomplete`，绝不使用未验证指标。`audit_teaching_input_grid.py` 再从各点原始数据重算 CSV/JSON、cost 和最佳点；重新哈希伪造的摘要仍被拒绝。

实测归档：`results/runs/teaching_input_grids/20260926T132426Z_d1ac5f06/`。9/9 点完成、全部有独立原始网表/日志/PSFASCII/Touchstone/指标清单，整体 CSV/JSON/配置亦有哈希清单；只读审计返回 `status=verified, points=9`。下表的 S11、NF、S21 和纹波均是 8–12 GHz **41 个采样点**的汇总值，不代表连续频率保证。

| LGS nH | LSS pH | NF 最差 dB | S11 最差 dB | S21 最差 dB | 纹波 dB | 诊断 cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.7 | 180 | 0.841 | -6.448 | 9.799 | 2.127 | 13551.5 |
| 0.7 | 240 | 0.863 | -8.127 | 8.596 | 2.472 | 11873.4 |
| 0.7 | 300 | 0.897 | -9.041 | 7.532 | 2.716 | 10958.9 |
| 1.0 | 180 | 1.072 | -9.052 | 9.389 | 3.076 | 10947.6 |
| **1.0** | **240** | **1.151** | **-10.179** | **8.204** | **3.266** | **9821.0** |
| 1.0 | 300 | 1.239 | -9.539 | 7.162 | 3.388 | 10460.9 |
| 1.3 | 180 | 1.561 | -5.809 | 8.568 | 4.262 | 14191.0 |
| 1.3 | 240 | 1.682 | -6.359 | 7.500 | 4.221 | 13640.8 |
| 1.3 | 300 | 1.809 | -6.409 | 6.547 | 4.175 | 13600.0 |

最低 cost 是原始 `LGS=1 nH/LSS=240 pH`（网格内 `point_04`），且其 S11 violation 仍约 9.821 dB；**9 点没有一个满足 -20 dB 输入匹配门槛**。最后一行 NF 还比 1.8 dB 目标高约 0.0086 dB。增加 LSS 在某些行改善 S11 却降低 S21、提高 NF；增加 LGS 并非单调提升带内 S11。这是当前理想网络和模型/网格上的实测趋势，不能直接迁移至 PDK。供电电流九点均约 4.973 mA，输出匹配仍差（见 `docs/34_teaching_output_match_probe.md`）。0.1–20 GHz/200 点采样网格最小 K 约 `1.00000001..1.000073`、最大 `|Delta|≈0.999`，稳定性门限余量极小，不能据此签核连续频率、角落、大信号或片上无源网络。

后续多宽度表征使新版 `run_teaching_lna.py` 的候选快照增加 `wmos_um`。输入网格 runner 和审计器已同步：新网格固定并记录 `wmos_um=300.0`；审计器仍接受**已有**无此字段的九点历史归档，不回写旧清单。修复后用此前未扫过的 `LGS={0.85,1.15} nH`、`LSS={210,270} pH` 做 2×2/4 点真实 Spectre 回归，归档 `results/runs/teaching_input_grids/20260926T150741Z_8a0c5248/` 的每点原始结果及整体摘要均通过只读审计。新网格最低 cost 为 `point_01`（0.85 nH/270 pH）约 9845.0，最差 NF≈1.002 dB、S11≈-10.155 dB；S11 仍距 -20 dB 目标约 9.845 dB，采样 K≈1.00000014，不能称稳定匹配。四点运行只证明新版参数契约与仿真后端贯通，不是论文 Stage 2 的 PSO/全带合格结果。

只读复核优先，确有新实验目的才重跑：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_teaching_input_grid `
  results/runs/teaching_input_grids/20260926T132426Z_d1ac5f06
py -m orfadc.experiments.audit_teaching_input_grid `
  results/runs/teaching_input_grids/20260926T150741Z_8a0c5248
py -m orfadc.experiments.run_teaching_input_grid `
  --lgs-nh 0.7 1.0 1.3 --lss-ph 180 240 300 `
  --nf-user-db 2.0 --nf-headroom-db 0.2
```

## 未完成的论文门槛

这只覆盖单级输入理想电感的有限网格；论文 Stage 2 还涉及有源级资源分配、级间/输入阻抗、NF/S11 全带协同、合法的 k/L/R/C/Ls、PSO 和受控等预算基线。`AgentToolRegistry` 的 `impedance_matching` 仍不能把这张教学表当作合格 Cadence LNA 后端；`spec_pass=null`。下一步须在授权 PDK 中解决 CDF/PCell 与无源可实现性，再构建可实现宽带网络，扩大频率/角落/负载检查，完成论文式工具与 fullchain；路线 B 可继续低保真方法调试，但不可替代工艺验收。
