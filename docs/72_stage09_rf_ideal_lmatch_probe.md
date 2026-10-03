# Stage 09：授权 RF 默认器件的理想两元件输入匹配实测

## 为什么做这次仿真

`docs/71_stage09_rf_input_match_estimate.md` 从已审计的三级 RF 默认器件复数 S11 发现：10 GHz 输入约 `115.5-j512 Ω`，仅加一个串联电感即使消去虚部，仍无法把实部变为 50 Ω。为核验阻抗变换方程及 Spectre 接线，从该**既有 OA 网表副本**推导一个中心频点两元件 L-match。它不是新 Virtuoso schematic，不是 PDK 可实现网络，更不是论文 MCR。

原输入端看到的导纳写成 `Y=G+jB`。选择并联电感后的目标虚部 `B'=-sqrt(G/50-G²)`，使 `Re(1/(G+jB'))=50 Ω`；取 `Lsh=1/[ω(B-B')]`，再用串联电容 `Cs=1/[ω Im(1/(G+jB'))]` 消掉余下的正电抗。所有值由**同一源档的 10 GHz S11**算出，因此中心频点深陷是设计条件，不是盲测成功。算得理想并联电感约 **3.369 nH**、理想串联电容约 **46.578 fF**。

`src/orfadc/experiments/run_pdk_rf_input_lmatch.py` 先重审原 RF 默认器件 OA/Spectre 档、检查宿主物理内存，再仅将端口正端改接新节点并加入这两个理想元件；六管、偏置、其余被动网络、ADE 伴随文件与 1787 Ω 输出参考平面保持不变。派生网表、wrapper、远端回读、Spectre 日志和原始 PSFASCII/Touchstone 保留在 Git 忽略档 `results/runs/pdk_rf_input_lmatch/20260927T050226Z_8ebc767d/`。Spectre 完成 0 errors、5 条既有 `SFE-1131` 模型配置警告。

## 实测与独立重审

| 8–12 GHz/161 点指标 | 原 OA 基线 | 理想 L-match 派生 Spectre |
| --- | ---: | ---: |
| 最差 S11 | 约 -0.207 dB | **-0.245 dB** |
| 最差 S21 | 约 -33.924 dB | **-29.379 dB** |
| 最差 S22 | 约 -0.199 dB | **-0.199 dB** |
| 最差 NF | 约 25.570 dB | **21.039 dB** |
| 增益纹波 | 约 13.322 dB | **19.335 dB** |
| 电源电流 | 约 9.825 mA | **9.825 mA** |

新电路的 8、10、12 GHz S11 分别约 `-0.245/-143.989/-1.750 dB`。10 GHz 的极深数值只表明理想、无损且按同一基线数据调谐的中心点近似抵消；它并非工艺鲁棒余量，不能用单点替代最差 S11。NF 和最差 S21 虽改善，仍远离论文式 LNA 规格，输出匹配也未解决。采样稳定性只能说明这 161 点上的 K/Δ 计算，不覆盖其他端接、角落或带外。

`src/orfadc/experiments/audit_pdk_rf_input_lmatch.py` 重新审计 OA 基线，强制派生网表与其只有端口改接及两元件差异、ADE 与远端快照一致，并由日志核验真正加载了派生网表。它从原始 DC、六管工作点、复数四 S、NF/NFmin/F/Fmin 与混合参考 Touchstone 重建 CSV/指标；还用原 OA 的 161 点 S11 和理想网络方程逐点预测新 S11，最大复数差约 **6.32e-8**。这验证了理想网络等效和本次仿真连线，不验证真实无源的 Q、SRF、面积、耦合或版图。假造网表、原始 S11 样本、报告数值、源 ID、资格状态后重算哈希的负例均被拒绝。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_input_lmatch `
  results/runs/pdk_rf_input_lmatch/20260927T050226Z_8ebc767d
```

## 结论和下一门槛

一个按中心频点精确合成的无损 L-match 仍不能满足 8–12 GHz 宽带匹配，且最差增益/NF、输出端及物理无源都不合格。不能用 `S11(10 GHz)` 或高采样 K 单独给 candidate 判 pass。下一步是**实测**多频峰值/实部变换的受限输入和级间网络，并在授权 PDK 合法几何、Q/SRF、实际耦合、损耗及模型警告门禁下筛选；只有重新保存的用户 OA 电路、同候选 DRC/角落和有效 HB/fullchain 才可进入合格 LNA 验收。本实验始终 `physical_qualification=false`、`not_lna_result=true`、`spec_pass=null`，不得填论文 Table IV/V 或 Fig. 7。
