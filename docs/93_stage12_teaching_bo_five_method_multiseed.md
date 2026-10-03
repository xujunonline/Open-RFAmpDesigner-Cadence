# Stage 12: 教学 BO 与五方法同预算比较

## 本轮完成的范围

在公开 MOS1 共源教学电路上，新增基于 `scikit-optimize 0.10.2` 的 GP/EI `ask/tell` BO 控制器。只改变输入匹配诊断的 `LGS`、`LSS`，固定偏置、MOS 宽度、负载电感和隔直电容。每个 seed 的前两点使用与 random 基线相同的确定性样本，再由 GP/EI 提议后两点。搜索空间 `LGS=0.7..1.3 nH`、`LSS=180..320 pH`，目标仍为既有 Stage 2 的 NF/S11 cost。此目标尚未满足输入匹配，也不代表 LNA 规格通过。

五个 seed 为 1、2、3、4、17；每个四次**新的** Cadence Spectre DC/SP/noise 调用，合计 20 点。每个点保留网表、日志、波形和指标，并由 `audit_teaching_lna.py` 重算。`audit_teaching_matching_bo.py` 固定依赖版本，重放 GP/EI 提案、每点原始数据和最优轨迹，五份搜索档均返回 `verified`。BO 搜索档位于 Git 忽略的 `results/runs/teaching_matching_bo/`，run ID 依次为：

| seed | BO run ID | 最终最佳教学 cost |
| ---: | --- | ---: |
| 1 | `20260927T123532Z_a5f7f7c0` | 10186.060 |
| 2 | `20260927T123547Z_27b47d3b` | 10675.712 |
| 3 | `20260927T123603Z_0099c02f` | 9090.144 |
| 4 | `20260927T123624Z_1c086c54` | 10604.703 |
| 17 | `20260927T123441Z_720e0596` | 10432.950 |

`summarize_teaching_stage2_five_methods.py` 从已审计的四方法 80 点报告 `20260927T101428Z_4e5d538c` 和上述 BO 20 点重新追溯每个原始档，检查相同 seed、电路、目标、范围、预算和 BO/random 前两点一致性。五方法报告 `results/runs/teaching_stage2_five_methods/20260927T123913Z_9d77a726/` 有逐 seed、逐评估 CSV、指标 JSON 和证据清单；只读重建返回 `verified`。重哈希后修改摘要、CSV 或源档引用的测试均拒绝。

图档 `results/runs/teaching_stage2_plots/20260927T124542Z_aac7e263/teaching_stage2_five_methods.png` 展示五个 seed 的逐评估 mean-best 诊断 cost；生成器先重审 100 点来源，审计器重绘 PNG 并逐字节比较。图像明确标注教学电路与非论文 Fig. 10，不能作为论文样本效率结论。

BO 控制器及五方法报告的隔离依赖焦点回归为 `6 passed`，图像生成/篡改焦点回归为 `4 passed`。默认环境全量回归 `857 passed, 6 skipped`；图像用例在该次全量测试收集之后新增，已单独执行。各测试的私有基准档缺失时会跳过实档重审，因此迁移机器应先确认相关归档存在。

| 方法 | 五 seed 最终最佳教学 cost 均值 |
| --- | ---: |
| Random | 10312.32 |
| PSO | 10306.77 |
| SA | 10124.70 |
| GA | 9719.90 |
| BO | 10197.91 |

## 环境和重放

`scikit-optimize` 是本项目选用的 Python BO 库，不是论文写到的 `scikit-opt`/`sko`，两者不可混称。其 `Optimizer` 支持 GP/EI 的顺序 `ask/tell`；详见[官方 Optimizer 文档](https://scikit-optimize.readthedocs.io/en/latest/modules/optimizer.html)。本次隔离版本为 `scikit-optimize 0.10.2`、`scikit-learn 1.9.1`、`numpy 2.5.3`、`scipy 1.18.1`，版本被写入每份搜索配置。依赖安装于 Git 忽略的 `results/runs/bo_vendor/`，没有复制到公开源代码或改动全局 Python。该库本地包元数据声明 BSD 3-clause；见 `third_party_notes/README.md`。在另一台机器复核时，应在独立虚拟环境安装并核对上述版本，不应依赖此机器的私有 vendor 目录。

可选依赖版本记录在 `config/requirements_bo.txt`。它只用于本教学 BO；安装前先核对 Python/平台兼容性、实验室的第三方包政策和各包许可证。不要把 `results/runs/bo_vendor/` 提交到仓库。

在仓库根目录，已有隔离依赖的本机审计示例：

```powershell
$env:PYTHONPATH='results/runs/bo_vendor;src'
python -m orfadc.experiments.audit_teaching_matching_bo results/runs/teaching_matching_bo/20260927T123441Z_720e0596
python -m orfadc.experiments.summarize_teaching_stage2_five_methods --audit-dir results/runs/teaching_stage2_five_methods/20260927T123913Z_9d77a726
python -m orfadc.plots.plot_teaching_stage2_five_methods --audit-dir results/runs/teaching_stage2_plots/20260927T124542Z_aac7e263
```

新实验必须连接**获授权的本机 Cadence 环境**，使用 Git 忽略的 SSH/PDK 配置；不要公开商业模型、日志和原始结果。可运行 `python -m orfadc.experiments.run_teaching_matching_bo --seed 17 --budget 4` 创建新私有搜索档；这会重新消耗四次真实仿真，不是审计命令。

## 结论边界和下一步

五 seed、每法四点仅足以验证控制流、预算与证据链，不能比较算法普遍优劣、真实样本效率、延迟或成本。其电路是公开教学 MOS1，`not_lna_result=true`、`spec_pass=null`；本报告不是论文 Fig. 10 或 Table IV/V/VI，不产生 `pass@1`。GA/PSO/SA 为本项目受限教学实现，BO 使用的库也不是论文的 `scikit-opt`。Stage 12 仍为 `partial`。

后续先解决合格授权 PDK LNA 的 CDF/PCell 几何、DRC/无源 Q/k/SRF、匹配/稳定/增益/NF 与同候选大信号 fullchain；然后才能在相同真实设计域重复 GA/BO/PSO/SA 和 multi-agent 消融。没有合格后端时必须保持 unavailable，不能把本次教学分数迁移为论文结果。
