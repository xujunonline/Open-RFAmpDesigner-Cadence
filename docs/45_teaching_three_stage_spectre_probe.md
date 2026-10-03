# Stage 09：公开 MOS1 三级结构 Spectre 探针

论文 Fig. 3 是单端 cascode 首级、两级差分共源、交叉中和电容和磁耦合谐振网络，不是前三阶段中已验证的单级教学电路。本实验先在**公开人工 MOS1** 模型上建立一个三级直接 Spectre 网表，测试拓扑连通、DC 工作区、SP/noise 和混合端口参考；不声称是作者的 PCell、MCR、布局后网表或完整论文复现。固定 10 GHz 附近的 8–12 GHz/161 点和 1.2 V 电源，尚未尝试论文的 30/50 GHz 及 10–80% 多规格。

## 结构与参考平面

| 论文结构要素 | 本探针实现 | 未验证的关键条件 |
| --- | --- | --- |
| 首级单端 cascode、源退化 | M1/M2，`LG=1 nH`、`LS=240 pH`，VCAS=1.05 V | 授权 PDK 器件/寄生、源/负载牵引、物理电感 |
| 后两级差分共源 | M3/M4 与 M5/M6；每级差分栅偏置、漏极负载和源电阻 | 论文尺寸、功率/增益分配、级间匹配 |
| 中和电容 | 每级 2 个 10 fF 交叉电容 | 此 MOS1 模型 `Cgd=0`，不构成真实中和效果证明 |
| 级间与输出 MCR | L12P/S、L23P/S、L3P/S 三对**理想互感**，`k=0.45` | 论文 MCR 电路、Q/SRF、布局耦合与 PEX |
| 1787 Ω || 62 fF 负载 | 浮动差分 `PORT2 r=1787 Ω` 与并联 `CL=62 fF` | 端口本身实现电阻负载；没有额外并联实物电阻/输出 balun |

输入 `PORT1` 的参考阻抗为 50 Ω，输出差分 `PORT2` 为 1787 Ω。Spectre Touchstone 头部是 `# Hz S RI R 50 1787`；Python 解析器现分别保留两个参考阻抗，四条复数 S 与 PSFASCII 的最大逐点差约 `1.3e-15`。因此这里的 S21 是**混合参考阻抗端口的波比**，不可当作 50→50 Ω 增益、差分电压增益或论文 Table IV 的同名数值。供电为 VDD_SRC 电流；M2 与 M3–M6 的漏电流之和同供电 KCL 近似一致，六管的名义 `VDS−VDSAT` 均为正。

## 实测与追溯

首个基线 `results/runs/teaching_three_stage/probe_7eecbf34a74a/` 在 Spectre 25.1 完成 DC/SP/noise，0 errors/0 warnings。远端执行的网表及公开模型下载件同本地模板逐字节相同。`audit_teaching_three_stage.py` 从 PSFASCII、Touchstone、六管 `dcOpInfo`、日志和公开网表重算指标并核对清单。随后用受限渲染器只改末级输出无源，得到两个独立实测归档：

- `20260926T180711Z_1a26f372`：在 1 nH 输出次级和 62 fF 负载旁增加 190 fF 理想电容。
- `20260926T181001Z_a2b462ac`：取消附加电容，把次级改为 4.1 nH。

一阶并联谐振估算为 `L≈1/((2π×10 GHz)^2×62 fF)≈4.09 nH`；对于 1 nH，则需要约 253 fF 总电容，即额外约 191 fF。这个估算只给初始点，实际耦合、晶体管和端口会移动峰值，不能替代 Spectre。三个原始运行分别有 161 点与证据清单；`summarize_teaching_three_stage.py` 拒绝重复候选，从源档重建 Git 忽略的 `results/runs/teaching_three_stage_summaries/20260926T181140Z_14ea3389/` 内 `passive_probe.csv`、JSON 及清单。

| 输出次级/附加电容 | 最差 S11 (dB) | 最差 S21 (dB) | 最差 S22 (dB) | 最差 NF (dB) | S21 纹波 (dB) | VDD 电流 (mA) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 nH / 0 fF | -10.08 | -12.18 | -0.17 | 8.12 | 16.43 | 14.88 |
| 1 nH / 190 fF | -10.08 | -6.94 | -0.51 | 8.12 | 13.37 | 14.88 |
| 4.1 nH / 0 fF | -10.08 | -1.84 | -2.08 | 8.12 | 11.95 | 14.88 |

这三个点显示理想末级被动修改能改变带内输出响应，但**没有一个**证明宽带匹配/增益合格；最差 S22 仍离 -10 dB 很远。采样 Rollett K 很大主要还与此教学模型极小的 S12 有关，不支持带外/任意端接/实物稳定性的结论。这三份小信号归档未运行 HB；后续仅对相同基线做了**低驱动单点**差分 HB 核验，见 `docs/47_stage09_three_stage_low_drive_hb.md`，仍没有压缩点、PVT、Q/SRF、版图或 fullchain 规格评分。全部结果 `not_lna_result=true`、`spec_pass=null`，不能填论文 Table IV/V 或 Fig. 7 原始曲线。

复核与下一步：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage results/runs/teaching_three_stage/probe_7eecbf34a74a
python -m orfadc.experiments.audit_teaching_three_stage results/runs/teaching_three_stage/20260926T180711Z_1a26f372
python -m orfadc.experiments.audit_teaching_three_stage results/runs/teaching_three_stage/20260926T181001Z_a2b462ac
python -m orfadc.experiments.summarize_teaching_three_stage `
  results/runs/teaching_three_stage/probe_7eecbf34a74a `
  results/runs/teaching_three_stage/20260926T180711Z_1a26f372 `
  results/runs/teaching_three_stage/20260926T181001Z_a2b462ac
```

此直接网表的**相同教学基线**现已移入独立 Virtuoso OA schematic 并完成 OCEAN/直接 Spectre 交叉验收，见 `docs/46_stage09_public_oa_three_stage.md`。下一步仍须定义真正的匹配/增益/噪声/DC 裕量和压缩点门槛，做受 Q/SRF 约束的级间与末级网络优化及同一三级电路的大信号分析。授权 PDK 的 CDF/PCell 参数传播需在允许的交互环境独立验收，不能由公开 MOS1 结构探针替代。
