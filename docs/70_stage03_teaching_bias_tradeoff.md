# Stage 03：固定匹配网络的公开 MOS1 偏置单因素复核

## 问题与协议

旧的公开 MOS1 单级阻尼匹配诊断在 10 GHz 有低驱动 HB 数据，但有效功率点没有夹住 1 dB 压缩点；继续加大输入功率又触发模型有效性警告，见 `docs/42_stage03_damped_teaching_lna.md`。本轮测试较低 VBIAS 是否能在保持同一 8–12 GHz 电路/无源网络下改善大信号实验的可行性。**先做 DC/SP/noise 门禁；小信号明显恶化则不追加 HB。**

沿用旧 0.65 V 档 `20260926T154709Z_0b5d75fe`，新建 VBIAS=0.55/0.60 V 两个独立直接 Spectre 档。三者均为公开 MOS1 教学模型，固定相同 161 点网格及 `RDAMP=150 Ω` 等其余电路参数；汇总器逐字节核对渲染网表除 VBIAS 外一致，并重审每份原始 PSFASCII/Touchstone/日志/清单。两个新 Spectre 日志均为 0 errors、0 warnings。

| VBIAS | 源 run_id | 最差 S11 | 最差 S21 | 最差 S22 | 最差 NF | 纹波 | 电源电流 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.55 V | `20260927T043928Z_362b406f` | -6.095 dB | 3.355 dB | -10.185 dB | 3.153 dB | 3.440 dB | 1.243 mA |
| 0.60 V | `20260927T043942Z_9e93d08d` | -8.624 dB | 5.689 dB | -10.163 dB | 2.235 dB | 3.363 dB | 2.797 mA |
| 0.65 V | `20260926T154709Z_0b5d75fe` | -10.132 dB | 7.119 dB | -10.134 dB | 1.750 dB | 3.322 dB | 4.973 mA |

三点汇总档为 `results/runs/teaching_bias_summaries/20260927T044111Z_72630a31/`，包含 `bias_sweep.csv`、JSON 与 SHA-256 清单。新增 `audit_teaching_bias_summary` 从三个原始 Spectre 档重算全部列并逐字节核对 CSV；若源 ID、指标或 CSV 在重算哈希后被篡改，仍拒绝通过。它不把文件哈希当成签名或工艺验证。

## 结论和下一步

降低偏置确实降低电流，但在**该固定匹配网络**下使 S11、最差增益和 NF 变差，纹波也未改善。不能由小信号结果推断较低偏置的 IP1dB/OP1dB；本轮**未执行新的 HB**，不填压缩点。继续在这条固定无源网络上仅调低偏置，不是通向合格 LNA 的优先路线。下一步需在合法 MOS 尺寸与有损可实现无源约束下联合重设匹配/级间网络，再对有希望的候选做有效功率范围内的 HB；公开 MOS1 不代表授权 PDK 或论文数值。

只读重审：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260927T043928Z_362b406f
python -m orfadc.experiments.audit_teaching_lna results/runs/teaching_lna/20260927T043942Z_9e93d08d
python -m orfadc.experiments.summarize_teaching_bias --audit-dir results/runs/teaching_bias_summaries/20260927T044111Z_72630a31
```

所有数据仍 `not_lna_result=true`、`spec_pass=null`，不是 Table IV/V 或合格 fullchain。
