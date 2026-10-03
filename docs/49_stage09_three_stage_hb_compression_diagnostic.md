# Stage 09：公开三级教学电路的 HB 压缩点诊断

本记录承接 `docs/46_stage09_public_oa_three_stage.md`、`docs/47_stage09_three_stage_low_drive_hb.md` 和 `docs/48_stage09_three_stage_same_circuit_pair.md`。对象仍是公开 MOS1、理想互感/电感和交叉电容的三级**教学电路**，不是经授权 PDK、物理无源 Q/SRF、宽带匹配和角落验证的合格 LNA。10 GHz 功率扫描展示如何从同电路 Spectre HB 原始相量提取诊断级 IP1dB/OP1dB，不填论文 Table IV/V。

## 端口和原始数据

输入端为 50 Ω `PORT1`，`type=sine dbm=Pin freq=10G`；差分输出端为 1787 Ω `PORT2`，`type=dc`，并联 62 fF。所有点保持 7 谐波、8–12 GHz/161 点 SP/noise、相同 47 个电路元件与公开模型。`run_teaching_three_stage_hb.py` 对每点先作宿主 2.66 GiB 物理内存、SSH、Spectre 和来宾 Tools 门禁，新的运行目录独占保存网表、上传下载副本、日志、DC、SP、noise、HB PSFASCII、Touchstone、CSV、JSON 和 SHA-256 清单。Spectre 非零告警或文件不全不会产出有效点。

PSF HB 频域的基波相量是峰值。Spectre `PORT1:p` 的电流方向指向输入端口内部，因此输入源峰值相量 `Vs=V(in)-50*I(PORT1:p)`，可提供功率 `Pavs=|Vs|^2/(8*50)`；每点重算值必须与网表 `dbm` 在 0.01 dB 内一致。输出负载电阻电流 `I(PORT2:p)` 必须与 `Vdiff/1787` 一致；负载基波有功功率 `Pout=Re[Vdiff*conj(I)]/2`。功率增益为 `Pout,dBm-Pavs,dBm`，不可把总输出电流或电压增益混入。`-70 dBm` 低驱动点还须与同次混合 50/1787 Ω 参考的 SP S21 一致；高驱动允许压缩，不强制 HB 增益等于 S21。

## 扫描结果

十个**独立 Spectre 运行**被聚合到 `results/runs/teaching_three_stage_hb_sweeps/20260926T194808Z_2c6fec7e/`。下面是按输入功率升序的逐点摘要；完整数值与源 run ID 在 `power_sweep.csv`、`sweep_config.json` 和各源归档中。

| Pin (dBm) | 基波功率增益 (dB) | 相对同次 S21 (dB) |
| ---: | ---: | ---: |
| -70 | 3.41298 | -0.000005 |
| -50 | 3.41286 | -0.000127 |
| -40 | 3.41176 | -0.001232 |
| -30 | 3.40070 | -0.012288 |
| -20 | 3.28955 | -0.123440 |
| -15 | 2.98717 | -0.425819 |
| -13.5 | 2.55494 | -0.858047 |
| -13.2 | 2.43404 | -0.978948 |
| -12.5 | 2.09461 | -1.318379 |
| -10 | -0.02176 | -3.434750 |

前三点的平均低驱动功率增益为 `3.41253386 dB`，三点跨度约 `0.00123 dB`，低于提取器的 `0.2 dB` 线性参考容差。1 dB 下降被相邻 `-13.2/-12.5 dBm` 两点夹住，间隔 `0.7 dB`；按相邻点线性插值，**诊断级** `IP1dB≈-13.15565 dBm`、`OP1dB≈-10.74311 dBm`。插值不是在交点实际仿真的值，也不能用末位小数代表电路精度；更密扫描、谐波收敛、角落和真实无源模型尚未验收。

`audit_teaching_three_stage_hb_sweep.py` 对十点逐一运行各自的原始数据审计，要求相同模型、输出无源值、端口参考、频率和谐波数；四条复数 SP 必须跨点一致。它再重算 CSV、低驱动参考、夹点和报告，校验每个源 manifest 的 SHA-256。重哈希改写报告压缩值、重排输入功率或修改输入端口基波电流的负例测试均被拒绝。报告本身是派生档案，`simulation_status=unknown`，源点才是 `cadence_spectre` 实测；全部 `not_lna_result=true`、`spec_pass=null`。

只读重审：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage_hb_sweep `
  --audit-dir results/runs/teaching_three_stage_hb_sweeps/20260926T194808Z_2c6fec7e
```

该诊断关闭了**公开教学三级同电路压缩点提取方法**的小范围缺口，未关闭 Stage 09：仍缺授权 PDK CDF/PCell 参数传播、可实现并经 Q/SRF 限制的 MCR/宽带匹配、带外及角落稳定性，以及统一候选 fullchain 的规格评分。论文原始 TSMC N65 数值不可由本结果替代。

夹点附近 7/9/11 谐波数敏感性的独立实测见 `docs/50_stage09_three_stage_harmonic_sensitivity.md`；它不替代完整功率和工艺角落收敛。
