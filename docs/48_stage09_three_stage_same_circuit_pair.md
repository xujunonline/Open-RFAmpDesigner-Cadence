# Stage 09：三级 OA 小信号与低驱动 HB 同电路配对

`docs/46_stage09_public_oa_three_stage.md` 的 OA/OCEAN DC/SP/noise 与 `docs/47_stage09_three_stage_low_drive_hb.md` 的直接 Spectre -70 dBm HB 已各自独立审计。本项再核验它们能否作为**同一公开 MOS1 三级教学电路**的不同分析，而不是仅因指标接近就误并在一起。

`audit_teaching_three_stage_pair.py` 对两源归档及独立直接 Spectre 基线先做各自只读审计，然后逐个比较 47 个电路元件的名称、节点和参数。唯一允许的电路差异是：`PORT1` 加入 -70 dBm/10 GHz 激励，`PORT2` 由 `type=sine` 改为 `type=dc`，以及附加 7 谐波 HB 分析。两份归档使用相同的公开 MOS1 模型；OA 的 15 位导出与 HB 同次 SP 的四条复数 S 逐频对比，NF、NFmin、纹波和供电电流也逐项对照。HB 基波功率仍需与其同次 10 GHz S21 在 0.01 dB 内一致。

首次派生报告位于 Git 忽略的 `results/runs/teaching_three_stage_pairs/20260926T192301Z_64f6b886/`。它包含三个来源清单的 SHA-256、允许的网表差异、最大逐频复数 S 差约 `6.12e-15` 及 `compression_status=not_measured`。报告可从三份原始来源重新构建；测试覆盖不同 L3S/输出阻抗以及重哈希伪称“已测压缩点”的拒绝。`simulation_status=unknown` 表示派生报告本身没有新启动 Cadence，**不是**否定源档中的实测；`not_lna_result=true`、`spec_pass=null`，不生成 IP1dB、OP1dB 或论文表格数值。

本机复建命令：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage_pair `
  results/runs/teaching_three_stage_oa/20260926T184521Z_4561f7d5 `
  results/runs/teaching_three_stage_hb/20260926T190425Z_dc513e8b
```

下一门槛是同一**满足物理无源与稳定性条件的合格候选**完成多点 HB/PSS 夹持扫描，并贯通规格/候选/seed/timeout、原始数据和四工具评分。当前的教学拓扑在输出匹配及全带增益上失败，不能用低驱动配对代替 fullchain 验收。
