# Stage 09：四元件理想输入梯形网络的全带搜索与 Spectre 核验

## 问题与证据范围

前一轮按 10 GHz 精确合成的两元件 L-match 虽有中心尖峰，8–12 GHz/161 点最差 S11 仅约 -0.245 dB。本轮固定同一授权 RF 默认器件三级 OA/Spectre 源档，仅研究输入端**理想、无损**网络的全频带实部变换。搜索使用经审计的复数 S11 和 50 Ω 参考阻抗推得输入负载；它本身没有运行新候选。只把搜索选中的一个候选接入既有 OA 网表**副本**，直接运行 Spectre DC、六管 OP、SP、noise。没有创建新 OA schematic，也没有物理无源、PCell/DRC、角落或同候选 HB/fullchain 验收。

私有原始证据（Git 忽略，不得上传 PDK 网表或模型）：

- OA 有源基线：`results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b/`；OA 创建：`rf_default_create_20260926T231047Z_38b59de6`。
- 默认 PDK 螺旋一端口：`results/runs/passive_quality_reference/20260926T205333Z_b96aea29/`。
- 可确定重放的搜索：`results/runs/pdk_rf_input_ladder_search/20260927T051628Z_23e709de/`。
- 唯一候选 Spectre 原始运行：`results/runs/pdk_rf_input_ladder/20260927T051926Z_93744611/`。

## 网络和搜索

从有源输入向 50 Ω 端口回看，节点 `in` 先并联 `C_inner`；其外串联 `L_inner`；中间节点再并联 `L_middle`；最后串联 `C_outer` 到 `PORT1`。输出端及六管偏置均不改。每一频率用基线 `Zload=50(1+S11)/(1-S11)` 和下式计算新端口反射：

```text
Z1 = 1/(1/Zload + j*w*C_inner)
Z2 = Z1 + j*w*L_inner
Z3 = 1/(1/Z2 + 1/(j*w*L_middle))
Zport = Z3 + 1/(j*w*C_outer)
S11 = (Zport-50)/(Zport+50)
objective = max_{8..12 GHz, 161 points} |S11|
```

`search_pdk_rf_input_ladder.py` 用固定种子 17，在 `C=10–1000 fF`、`L=0.1–10 nH` 的四维正数范围，做 12,288 次对数均匀抽样加 4,096 次围绕当前最优的有界局部扰动；这只是**有限预算的启发式搜索**，不保证全局最优。保存每 1,024 次最优值与完整预测波形；审计时重审 OA/螺旋源档并逐字节重放搜索。最优理想值约为 `C_outer=181.936 fF`、`C_inner=10 fF`、`L_middle=1.650 nH`、`L_inner=5.602 nH`；其中 `C_inner` 在下界。预测全带最差 S11 为 -6.115110 dB，基线 -0.207442 dB。`no_candidate_simulated=true` 只属于搜索档，不代表后续 Spectre 档。

## 唯一候选实测

| 8–12 GHz/161 点最差指标 | 原 OA 基线 | 理想两元件 L-match | 四元件梯形网络 |
| --- | ---: | ---: | ---: |
| S11 | -0.207 dB | -0.245 dB | **-6.115 dB** |
| S21 | -33.924 dB | -29.379 dB | **-25.796 dB** |
| S22 | -0.199 dB | -0.199 dB | **-0.199 dB** |
| NF | 25.570 dB | 21.039 dB | **17.500 dB** |
| 增益纹波 | 13.322 dB | 19.335 dB | **15.512 dB** |
| 电源电流 | 9.825 mA | 9.825 mA | **9.825 mA** |

新候选在 8/10/12 GHz 的实测 S11 分别约 `-6.284/-6.129/-6.138 dB`；相应 S21 约 `-16.720/-11.982/-25.796 dB`。**最差 S11 约 -6.12 dB，仍非合格宽带匹配**；最差增益为负、NF 很高，输出 S22 基本没变。采样 K/Δ 通过仅是这 161 点的数学判据，不是任意端接、带外或物理稳定性资格。

`audit_pdk_rf_input_ladder.py` 强制 OA 源、搜索档、派生网表、ADE 伴随文件、远端回读、Spectre 实际读取文件和 0 errors/5 条既有 `SFE-1131` 警告相互绑定。它从原始 PSFASCII 复数四 S、NF/NFmin/F/Fmin、DC/六管工作点和混合参考 Touchstone 重建 161 行与指标；网络方程对实测复数 S11 的最大逐频差约 `7.59e-8`。这个数验证**理想网络方程与仿真连线**，不验证 PDK 几何或物理网络。改写原始 S11、网表、报告数值、源 ID 或资格标记后即使重算清单哈希，审计仍应拒绝。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.search_pdk_rf_input_ladder `
  --audit-dir results/runs/pdk_rf_input_ladder_search/20260927T051628Z_23e709de
python -m orfadc.experiments.audit_pdk_rf_input_ladder `
  results/runs/pdk_rf_input_ladder/20260927T051926Z_93744611
```

## 下一门槛

选中的 `L_inner≈5.60 nH` 远高于**默认** PDK 螺旋在 10 GHz 的实测有效 `0.638 nH`，而默认器件的 8–12 GHz 最低 Q 约 `10.524`，未达到本项目教学 Q≥15 门槛。这不证明 5.60 nH 在工艺里绝对不存在，只说明本档**没有**支持该无损值的合法几何、损耗、SRF、耦合或面积证据。下一步先在授权 PDK 中获取合法可调几何的一端口 Q/SRF 与必要的耦合数据、处理模型警告和既有 DRC 违规；再以有损器件重跑网络及三级级间/输出匹配。只有同候选 OA、模型/角落、物理无源、稳定性、HB 和 fullchain 均验收，才可能将其视为 LNA 候选。本轮固定 `physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`，不可填论文 Table IV/V 或 Fig. 7。
