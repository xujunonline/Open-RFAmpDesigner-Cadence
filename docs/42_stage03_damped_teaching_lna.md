# Stage 03/04/05：有损输出匹配的公开 MOS1 教学诊断

本实验沿用公开、人工设定的 Spectre MOS1 共源电路，用漏极电感并联电阻 `RDAMP` 降低理想输出匹配网络的有效 Q。目的是检验输出回波损耗能否从旧的窄带高 Q 峰值扩展至 8–12 GHz，并把同电路 DC/SP/noise 与 HB 原始运行严格配对。**这不是 TSMC PDK、论文三阶段 LNA、物理片上电感或 LNA 规格验收。**

## 电路与运行

新增白名单参数 `rdamp_ohm=100..10000`，接在 `vdd` 与 `drain` 之间，与 `LDD` 并联；不传参数时旧网表保持原样。SP 扫频可受控设置起止频率及间隔数。每个直接 Spectre 运行仍独立保存网表、日志、DC/SP/noise PSFASCII、Touchstone、CSV、指标和 SHA-256 清单，并由 `audit_teaching_lna.py` 从原始数据重算。`run_teaching_hb.py` 使用相同匹配参数与网格，HB 审计从记录参数重建网表。所有结果均在 Git 忽略的 `results/runs/`。

| RDAMP | LDD | CBLOCK | 8–12 GHz 最差 S11 | 最差 S21 | 最差 S22 | 最差 NF | 增益纹波 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 Ω | 2.652582 nH | 106.1033 fF | -9.968 dB | 11.640 dB | -4.104 dB | 1.339 dB | 3.171 dB |
| 250 Ω | 1.989437 nH | 159.1549 fF | -10.088 dB | 9.131 dB | -6.916 dB | 1.520 dB | 3.096 dB |
| 150 Ω | 1.688093 nH | 225.0791 fF | -10.132 dB | 7.119 dB | -10.134 dB | 1.750 dB | 3.322 dB |

前三行来自旧统一 0.1–20 GHz/200 点扫描，run_id 分别为 `20260926T154141Z_a701fd4d`、`20260926T154240Z_0678bae9`、`20260926T154319Z_621ad885`。150 Ω 另做 0.1–20 GHz/801 点加密运行 `20260926T154454Z_7b11ab9a` 和**恰好包含 8 与 12 GHz**的 161 点运行 `20260926T154709Z_0b5d75fe`；上表 150 Ω 行采用后者。两条带边：8 GHz 的 S11 -11.409 dB、S21 10.441 dB、S22 -10.134 dB、NF 0.817 dB；12 GHz 的 S11 -10.132 dB、S21 7.119 dB、S22 -15.357 dB、NF 1.750 dB。150 Ω 带内采样 K 最小 93.669、|Δ| 最大 0.0882；这是理想模型有限网格的稳定性诊断，不是所有端接/角落/频率的证明。

以教学自定阈值 -10 dB 输入/输出匹配看，150 Ω 点在采样网格上仅有约 0.13 dB 余量；纹波 3.322 dB，并未达更严的 3 dB 诊断阈值。电阻有损耗，增益和 NF 随阻尼加强而恶化。无源 Q、自谐振、寄生、版图、工艺角落和 50 GHz 模型适用性均未验证，不可将表格填入论文 Table IV/V。

## 同电路大信号证据

10 GHz、7 谐波、`RDAMP=150 Ω` 的四个有效 HB 点来自 `results/runs/teaching_hb/`：

| Pin | HB 功率增益 | 状态 |
| ---: | ---: | --- |
| -50 dBm | 9.257066 dB | 原始 HB 可重提取；与同次 SP S21=9.257073 dB 相差约 -0.000007 dB |
| -40 dBm | 9.257003 dB | 原始 HB 可重提取 |
| -20 dBm | 9.250050 dB | 未达 1 dB 压缩 |
| -10 dBm | 9.186415 dB | 未达 1 dB 压缩 |

对应 run_id 为 `20260926T154951Z_e7fbc293`、`20260926T155209Z_66a2dc1a`、`20260926T155030Z_4c4bf656`、`20260926T155058Z_fd2de058`。下一档 0 dBm 的 `20260926T155128Z_086a34c0` 虽有 Spectre 原始输出，但出现 CMI-2139/2144/2375/2377 模型有效性警告，故**不采用其 HB 指标**。四个有效点未夹住 1 dB 交点，`IP1dB=null`、`OP1dB=null`，不外推；汇总 `results/runs/teaching_matched_hb_summaries/20260926T155406Z_7e870a71/` 可从每个源运行只读重算。

`audit_teaching_matched_pair.py` 进一步把该汇总与 161 点小信号运行配对：先各自重审小信号及 HB 汇总，再检查所有四个有效点和一个警告点的真实网表均只能由小信号网表修改端口激励、输出端口模式及添加 HB 分析得到；记录的公共设计参数必须一致，10 GHz 原始 SP S21 差不超过 0.001 dB。警告点须有清单中的 SP 原始文件和与日志一致的模型警告。只读重审报告为 `results/runs/teaching_matched_pairs/20260926T155816Z_d73a694e/`，五点与源 10 GHz S21 的最大差为 0。此派生报告不改变任一原始归档；它证明**这组教学诊断同电路**，不产生有效压缩点或合格 LNA fullchain。

## Virtuoso OA/OCEAN 再现与独立核对

`run_teaching_oa.py --topology damped` 现用公开 `analogLib` MOS/电感/电阻/电容建全新 OA schematic；建图脚本只在该拓扑下选 `LD=1.68809309279457 nH`、`COUT=225.079079039277 fF`、并联 `RDAMP=150 Ω`。OCEAN 使用 8–12 GHz、`lin=160`（实测 161 点，包含两个带边），15 位 `ocnPrint` 导出复数 S 与 NF/NFmin/F/Fmin。首次脚本误用 SKILL 表达式式 `if`，运行 `20260926T161138Z_1901628d` 未保存；之后两个新 cell 的 RDAMP PLUS 因接线坐标错误分别得到 `schCheck=(0 2)`，运行 `20260926T161532Z_6620cf4e`、`20260926T161726Z_0dbecbd8` 保留为失败证据。只读端子诊断查明 `analogLib/res` PLUS 在实例原点、MINUS 在下方 0.375 单位；据此修正接线，而非复用失败 cell。

新运行 `results/runs/teaching_oa/20260926T162244Z_bf1bf86c/`：`schCheck=(0 0)`、保存 18 实例/9 网络；OA 网表中 `LD (net7 net5)` 与 `RDAMP (net7 net5)` 两端相同，M1 体端接地。经典 batch OCEAN/Spectre 完成 DC/SP-noise，日志 0 errors/0 warnings；161 点高精度 PSFXL 导出、指标、原始文件清单均由 `audit_teaching_oa.py` 重算通过。带内汇总最差 S11 -10.132 dB、S21 7.119 dB、S22 -10.134 dB、NF 1.750 dB，电源电流约 4.973 mA，与独立直接 Spectre 的数值一致。

`audit_teaching_damped_crosscheck.py` 对两个**不同执行**的源归档分别运行审计：OA schematic→OCEAN/PSFXL 和公开受控模板→直接 Spectre/PSFASCII。直接阻尼归档还须与记录参数渲染出的网表逐字节相等；OA 审计逐节点检查并联阻尼拓扑。然后逐频比较所有四个复数 S 迹线、NF/NFmin/F/Fmin，以及电流和带内统计。派生报告在 `results/runs/teaching_damped_crosschecks/20260926T162828Z_62e68cf3/`，可从源清单只读重建：161 点频率最大差 0 Hz、复数 S 最大差约 `7.39e-15`、噪声迹线最大差约 `7.11e-15`、供电电流差约 `1.21e-9 mA`。SHA-256 只是本地一致性检查，不是签名。

上述 OA/SP/noise 与 HB 属于相同**教学拓扑**，但 HB 来源是前述直接 Spectre 模板而非本次 OA 网表的 HB 派生；不能把三份独立作业误称一次 OA fullchain。理想 L/C、发热的阻尼电阻、工艺/温度角落、版图寄生、片上 Q/SRF 及合格压缩点仍未验收。依旧 `not_lna_result=true`、`spec_pass=null`。

复核入口（已有报告用 `audit_teaching_matched_pair_report` 只读重审；下列 CLI 创建新派生报告）：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_matched_pair `
  results/runs/teaching_lna/20260926T154709Z_0b5d75fe `
  results/runs/teaching_matched_hb_summaries/20260926T155406Z_7e870a71
python -m orfadc.experiments.audit_teaching_oa `
  results/runs/teaching_oa/20260926T162244Z_bf1bf86c
python -m orfadc.experiments.audit_teaching_damped_crosscheck `
  results/runs/teaching_oa/20260926T162244Z_bf1bf86c `
  results/runs/teaching_lna/20260926T154709Z_0b5d75fe
```

下一步仍优先解决授权工艺的 CDF/PCell 参数传播和实际可实现无源网络；在合格、稳定的 LNA 上重新做全带 SP/noise/功耗与夹持的压缩点。公开 MOS1 只服务于教学方法与后端可靠性检查。
