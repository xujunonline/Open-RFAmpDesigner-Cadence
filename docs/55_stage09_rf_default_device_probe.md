# Stage 09：授权 RF 器件默认参数三级探针

## 为什么另建电路

`docs/53_stage09_pdk_hybrid_three_stage.md` 的六管三级 OA 诊断使用授权 PDK 中的通用 MOS，并对实例直接写入尺寸属性，未核清 CDF/PCell 派生几何。已授权的器件库还包含专用 RF MOS 系列。因此本轮只读检查其 symbol、Spectre view、四端引脚与 CDF 参数，再在**用户设计库的全新 OA cell**中将六管换成该 RF 器件，六管**不写任何尺寸实例属性**，使用 CDF 默认参数。所有商业网表、CDF 报告、OA 文件和日志仅保存在 Git 忽略目录。

第一轮只读 OCEAN 探针因启动包装器寻找不存在的系统默认 Xvfb 而失败，未产生 CDF 报告；失败档案保留在 `results/runs/pdk_three_stage_fixed/rf_mos_readonly_20260926T230618Z_4f8a7148/`。核实项目配置的用户目录 Xvfb 可执行文件后，新归档 `rf_mos_readonly_20260926T230727Z_0c5b4441/` 返回 0，报告显示 RF 器件具备 symbol、Spectre 和版图相关 view，端子为 D/G/S/B，默认长度、指宽和指数及多项邻近/寄生参数由 CDF 给出；这些默认参数并不等于已经执行 callback、核验 PCell 合法几何或通过 DRC。

随后新 OA schematic 通过 `schCheck=(0 0)`、`dbSave=t`，58 个实例、26 个网络，生成六个一致默认 RF 模型的 Spectre 网表。原始创建脚本、Check and Save 报告、OA 文件和 netlist 在私有档案 `results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6/`。原有三级的电源、偏置、理想无源、50 Ω 输入和 1787 Ω || 62 fF 差分输出未改；此运行只是器件类别及其默认几何一同变化，**不是单变量尺寸实验**。未调用 CDF callback，也未验证物理 PCell、EM、角落或布局寄生。

## Spectre 实测与原始审计

该新 OA 网表又由独立 wrapper 直接运行 Spectre 25.1 的 DC、工作点和 8–12 GHz/161 点 SP/noise。返回 0 errors、5 条已知的模型配置重复警告 `SFE-1131`；原始档案为 `results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b/`。`src/orfadc/experiments/audit_pdk_rf_default_three_stage.py` 对创建档案与仿真档案双向核验：六个 MOS 的默认几何签名相同、创建脚本对 MOS 不添加属性、OA 源网表与远端执行网表逐字节一致，六管工作点有限且 `VDS>VDSAT`，供电电流与器件电流在 RF 宏模型的附加支路容差内一致。四个复数 S 参数与混合参考阻抗 Touchstone 的最大逐点差约 `2.42e-16`；NF/NFmin 与 F/Fmin 换算、频率网格、CSV/metrics 和 SHA-256 清单均复核通过。

| 8–12 GHz 采样指标 | 此 RF 默认器件三级 | 前述通用 MOS 三级 |
| --- | ---: | ---: |
| 最差 S11 | -0.207 dB | -0.035 dB |
| 最差 S21 | -33.924 dB | -58.680 dB |
| 最差 S22 | -0.199 dB | -0.172 dB |
| 增益纹波 | 13.322 dB | 14.876 dB |
| 最差 NF | 25.570 dB | 46.848 dB |
| 最差 NFmin | 16.323 dB | 29.034 dB |
| 供电电流 | 9.825 mA | 3.210 mA |

两电路的 MOS 模型及实际尺寸**同时**变化，不能把表中差异归因于“RF 器件类型更好”，更不能当作受控工艺器件 benchmark。两者仍采用理想耦合网络，匹配、增益、纹波和噪声均严重不合格。RF 默认器件的六管 DC 工作区只对这次偏置解成立；带内 sampled K/Δ 不代表带外、角落或大信号稳定。该运行没有 HB/P1dB，始终 `not_lna_result=true`、`spec_pass=null`、`physical_qualification=false`、`cdf_callback_validated=false`。

## 同一 OA 网表的内部 AC 定位

另起 Spectre AC 探针，在**同一 RF 默认器件 OA 网表**的输入节点并联一个理想 1 V 小信号源，保存 8–12 GHz/161 点内部复数节点电压。该激励改变源阻抗条件，只用于内部电压比，不能混用为端口 S21、NF 或压缩点。原始档案为 `results/runs/pdk_three_stage_fixed/rf_default_ac_20260926T232525Z_eff8ebae/`，`src/orfadc/experiments/audit_pdk_rf_default_ac_probe.py` 通过创建档案、OA 网表 SHA、远端快照、Spectre 日志、161 点 PSFASCII、CSV 和证据清单逐项复核。10 GHz 结果如下：

| 级间节点路径 | AC 电压比 |
| --- | ---: |
| 输入 → 首级输出 | +1.847 dB |
| 首级输出 → 第二级差分栅极 | -8.851 dB |
| 第二级差分栅极 → 第二级差分漏极 | +3.684 dB |
| 第二级差分漏极 → 第三级差分栅极 | -6.569 dB |
| 第三级差分栅极 → 第三级差分漏极 | +2.922 dB |
| 第三级差分漏极 → 输出差分端口 | -5.055 dB |
| 输入 → 输出差分端口总电压比 | -12.022 dB |

三个有源段在此偏置与理想源条件下均为正的电压传递，级间与输出耦合却有更大损耗。这给出**先验证并设计可实现无源网络**的工程方向；不能据此推断任一 `k` 值、器件尺寸或论文 MCR 的物理可行性，也不能把总电压比解释为 S21。当前输出匹配和噪声仍明显不合格。

审计器现额外要求 OA 创建报告中的 netlist 路径、Spectre wrapper 实际引用和日志中的 `Reading file` 来源完全一致，且同时检查伴随 `ade_e.scs`。伪造另一份 `input.scs` 路径的负例测试被拒绝；本页 SP、AC 两个原始档案在新检查下均通过只读重审。这提高了归档来源绑定强度，不替代模型授权、PCell 或物理资格验证。

## 可重审与下一门槛

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_pdk_rf_default_three_stage `
  results/runs/pdk_three_stage_fixed/rf_default_sp_20260926T231333Z_19c5f59b `
  --create-dir results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6
python -m orfadc.experiments.audit_pdk_rf_default_ac_probe `
  results/runs/pdk_three_stage_fixed/rf_default_ac_20260926T232525Z_eff8ebae `
  --create-dir results/runs/pdk_three_stage_fixed/rf_default_create_20260926T231047Z_38b59de6
python -m pytest tests/test_pdk_rf_default_three_stage.py -q
```

下一步以受控新 cell 核实可编程 RF 尺寸的 CDF 回调、PCell 与生成网表一致性；不能沿用通用 MOS 的尺寸字段或虚构 RF 几何公式。优先测量物理耦合器件的 Q/k/SRF、损耗及版图依赖，再处理输入/输出匹配、带外稳定、压缩点及同候选 fullchain。授权虚拟机目前没有就绪的用户 Virtuoso 图形会话；不原样重试此前失败的无图形 `vfoSetParam`。
