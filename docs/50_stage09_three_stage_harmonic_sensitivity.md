# Stage 09：三级教学 HB 的谐波阶数敏感性

`docs/49_stage09_three_stage_hb_compression_diagnostic.md` 的 7 谐波扫描在 10 GHz 的 1 dB 夹点为 `-13.2/-12.5 dBm`。这里**只**检查同一公开 MOS1 三级教学电路在该夹点附近对 HB 最大谐波数的敏感性，不重新宣称论文或合格 LNA 的 P1dB。

在每个输入功率分别运行 7、9、11 谐波，六个点各有独立 Spectre 原始 DC/SP/noise/HB、网表和日志，均为 0 errors/0 warnings。逐点审计从 `PORT1` 基波相量重算输入可提供功率，从 1787 Ω 差分端口电流重算交付功率；跨点核对公开模型、47 元件白名单渲染、50/1787 Ω 参考以及 161 点四条复数 SP。源 run ID 和 manifest SHA-256 位于派生报告 `results/runs/teaching_three_stage_harmonics/20260926T200221Z_c224bdf6/`。

| Pin (dBm) | 7 谐波增益 (dB) | 9 谐波增益 (dB) | 11 谐波增益 (dB) |
| ---: | ---: | ---: | ---: |
| -13.2 | 2.434041 | 2.429790 | 2.430847 |
| -12.5 | 2.094609 | 2.092383 | 2.091328 |

两个夹点上，7→9 谐波的最大功率增益差约 `0.00425 dB`，9→11 谐波约 `0.00106 dB`。以每个点同次 SP `S21` 作低驱动增益参考并在相邻夹点线性插值，7/9/11 谐波的诊断级输入交点分别约 `-13.15658/-13.16514/-13.16318 dBm`，最大差约 `0.00856 dBm`。这个参考方法与 `docs/49` 采用前三个 HB 低驱动点平均值的方法相差约 `0.001 dB`，故数值不应强行写成完全相同。

`audit_teaching_three_stage_harmonics.py` 从六个源档逐点重算、重建比较报告；重排谐波矩阵及重哈希改写敏感性结论的测试会失败。只读命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage_harmonics `
  --audit-dir results/runs/teaching_three_stage_harmonics/20260926T200221Z_c224bdf6
```

这仅支持“**此教学模型、10 GHz、这两个输入功率**上的 7/9/11 谐波结果对阶数不敏感”。不涵盖全功率/全频段、其它振荡支路、真实 PDK 模型、无源 Q/SRF、版图寄生、带外稳定性或生产级谐波收敛。全部源点和报告均 `not_lna_result=true`、`spec_pass=null`；合格 LNA 和论文数值门槛仍未关闭。
