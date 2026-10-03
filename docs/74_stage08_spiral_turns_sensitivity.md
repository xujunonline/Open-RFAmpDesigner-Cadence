# Stage 08：授权 PDK 螺旋匝数属性的受控一端口敏感性

## 问题和边界

`docs/73_stage09_rf_ideal_ladder_search_and_probe.md` 的理想输入网络需要约 5.602 nH 的内串电感，而已测标准型 PDK 默认螺旋在 10 GHz 只有约 0.638 nH，且 8–12 GHz 最低 Q 约 10.524。为判断**同一模型、固定其他网表属性**时增加匝数的局部趋势，本轮从已审计的默认 OA 网表副本精确替换 `L1` 的 `nr=3` 为 `nr=4` 或 `nr=5`，其余模型、端口、扫频和伴随文件不变。新网表直接交 Spectre；**没有**新建或修改 OA schematic、PCell/layout，也没有调用 CDF 回调、做 DRC/EM/PEX 或证明 `nr=4/5` 为工艺合法值。这是模型属性敏感性，不是器件尺寸优化或物理资格。

私有原始档均位于 Git 忽略目录，不公开 PDK 网表/模型：

- 默认 OA 一端口源：`results/runs/passive_quality_reference/20260926T205333Z_b96aea29/`。
- `nr=4`：`results/runs/pdk_spiral_turns/20260927T053918Z_b08774a7/`。
- `nr=5`：`results/runs/pdk_spiral_turns/20260927T053955Z_6aa2d00e/`。

## 实测

三档都是 Spectre 的 0 errors、5 条既有 `SFE-1131` 模型配置警告；新两档在 0.5–30 GHz/591 点扫频中，原始复数 S11、网表来源、远端回读和指标均经独立审计。用 `Z=50(1+S11)/(1-S11)`、`Q=Im(Z)/Re(Z)` 和 `Leff=Im(Z)/(2πf)` 提取，不用 CDF 的标称电感代替实测。

| 固定其他属性的网表 `nr` | 10 GHz 有效电感 | 8–12 GHz 最低 Q | 观测自谐振 | 项目教学 Q≥15 筛选 |
| --- | ---: | ---: | ---: | --- |
| 默认 3 | 约 0.638 nH | 约 10.524 | 至 30 GHz 未见过零 | 未通过 |
| 4 | 约 1.274 nH | 约 8.219 | 约 29.524 GHz | 未通过 |
| 5 | 约 2.398 nH | 约 4.518 | 约 20.885 GHz | 未通过 |

这三个离散点只支持**本模型、这些属性组合**的局部趋势：增加 `nr` 提高 10 GHz 有效电感，同时显著降低带内最低 Q 并降低观测 SRF。即使 `nr=5` 仍远低于理想网络所需的 5.602 nH，Q 也更差；不以未经验证的更高匝数追逐该理想值。Q≥15 和 SRF≥1.2×12 GHz 是本项目的教学响应筛选，不是论文 Table II 或 PDK 设计规则。`response_screen_fail` 也不证明其他宽度、半径、层次、器件或合法几何必然失败。

`run_pdk_spiral_turns.py` 强制源档通过原始一端口审计、宿主剩余物理内存≥2.66 GiB、每次独立目录且只改一个 `nr` 字段；`audit_pdk_spiral_turns.py` 再次重审源档、验证派生网表与 Spectre 实际读取路径、0 errors/5 warnings、远端源快照、591 点原始 S11 与标准化 CSV。改写源 ID、网表、原始 SP、Q 报告或物理资格标记后，即使重算清单哈希也会被拒绝。审计输出始终 `physical_qualification=false`、`geometry_sweep_verified=false`、`cdf_callback_validated=false`、`not_lna_result=true`、`spec_pass=null`。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_spiral_turns `
  results/runs/pdk_spiral_turns/20260927T053918Z_b08774a7
python -m orfadc.experiments.audit_pdk_spiral_turns `
  results/runs/pdk_spiral_turns/20260927T053955Z_6aa2d00e
```

## 下一门槛

先取得 PDK 支持的合法几何/适用频段与 CDF/PCell 回调路径，在**新用户设计库 cell**做参数传播、版图响应和适用 DRC；随后对真实候选测 Q、SRF、耦合与角落。已有 RF MOS 单管低层 PCell 的 DRC 违规不能套用到本螺旋，也不能因本次 Spectre 成功推断螺旋 DRC 通过。只有通过上述门禁并把有损器件接入同候选三级 OA/fullchain，才能评价是否满足论文式 LNA 指标；本页不能填论文 Fig. 7 或 Table IV/V。
