# Stage 09：公开 MOS1 三级差分输出低驱动 HB

在 `docs/45_teaching_three_stage_spectre_probe.md`、`docs/46_stage09_public_oa_three_stage.md` 已核对的**相同三级教学拓扑**上，加入 10 GHz 单音 HB，先验证大信号结果的端口和功率定义。本记录不提供 IP1dB/OP1dB：没有高功率夹持点、没有合格宽带匹配，也没有工艺/无源物理性验收。

## 激励与功率参考

`render_teaching_three_stage_hb` 仅把 50 Ω `PORT1` 改为 `type=sine dbm=-70 freq=10G`，把浮动差分 1787 Ω `PORT2` 改为 `type=dc`，再加 `hb fundfreqs=[10G] maxharms=[7]`；DC/SP/noise 原分析与 47 个电路元件保持不变。输出并联 62 fF，因此端口**电阻**上的基波有功功率必须用 `PORT2:p` 电流计算，而不能把总输出电流或差分电压增益当交付功率。

HB 频域文件的基波电压/电流是峰值相量。令 `Vd=V(outp)-V(outn)`、`Ip=I(PORT2:p)`，本机原始结果在 **10 GHz 基波点**核对 `Ip≈Vd/1787 Ω`；交付功率为 `Pout=Re(Vd·conj(Ip))/2=|Vd|²/(2·1787 Ω)`，`Pout,dBm=10 log10(Pout/1 mW)`。输入 `PORT1 dbm` 指 50 Ω 端口可提供功率；小驱动 `Pout,dBm-Pin,dBm` 可同**混合 50/1787 Ω 参考**的 SP `20 log10|S21|` 比较。这不是 50→50 Ω 或纯电压增益。

## 原始证据

| 运行目录 | 作用 | 结论 |
| --- | --- | --- |
| `results/runs/teaching_three_stage_hb/0f785d08cc/` | 首次直接 Spectre 低驱动探针 | 0 errors/0 warnings；DC/SP/noise/HB 三种原始格式与混合参考 Touchstone 均已归档、只读审计 |
| `results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b/` | 一键 runner 在新目录重复同一点 | 原始网表/模型上传下载核对、全部分析和只读审计通过；不计入第二个优化样本 |

首次运行的差分输出基波功率约 `-66.58701676 dBm`，输入 `-70 dBm`，交付功率增益约 `3.41298324 dB`；同次 10 GHz SP S21 约 `3.41298842 dB`，差约 `-5.18e-6 dB`。端口电流相对校验误差约 `2.14e-16`。注意这是**10 GHz 单点**，而 8–12 GHz 基线最差混合 S21 仍为负且最差 S22 近 0 dB。`audit_teaching_three_stage_hb.py` 从原始 HB 相量、S/噪声迹线、六管工作点、日志、网表与哈希清单重算；重哈希改动端口电流的负例会被拒绝。两个归档均 `not_lna_result=true`、`spec_pass=null`。

本地受控运行与复核：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.run_teaching_three_stage_hb --input-dbm -70
python -m orfadc.experiments.audit_teaching_three_stage_hb `
  results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b
```

该记录形成时 runner 仅接受 `-100..-50 dBm`；现已扩展到 `-100..0 dBm`，仍维持宿主物理内存/SSH/来宾工具门禁，Spectre 有 warning 或原始数据缺失即保留失败档案。相同公开三级电路后续已得到**教学诊断级**压缩点，见 `docs/49_stage09_three_stage_hb_compression_diagnostic.md`；这不改变**合格 LNA** 的 IP1dB/OP1dB 未测状态。合格候选仍须复核谐波收敛、带外稳定性和 PDK/无源有效范围。
