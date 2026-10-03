# Stage 09：三级教学电路的宽频采样稳定性

本记录对 `docs/45_teaching_three_stage_spectre_probe.md` 的**同一公开 MOS1 三级基线**增加 0.1–20.1 GHz/401 点 SP/noise 网格，仅改 Spectre 的 SP 扫频行；MOS1 模型、47 个元件、偏置、50/1787 Ω 混合参考端口及 1787 Ω || 62 fF 输出负载不变。新直接 Spectre 原始档案为 `results/runs/teaching_three_stage/20260926T201404Z_b301241a/`。它经宿主 2.66 GiB 物理门禁、SSH/来宾 Tools、Spectre 0 errors/0 warnings、网表/模型上传下载字节核验、PSFASCII/Touchstone 复数 S 与噪声/工作点重提取和 SHA-256 清单审计。原 8–12 GHz/161 点档案与宽频档案在 8、10、12 GHz 的四条复数 S 最大差小于 `1.2e-15`。

Rollett 判据使用复数 S 参数：`Δ=S11*S22-S12*S21`，`K=(1-|S11|²-|S22|²+|Δ|²)/(2|S12*S21|)`。对测得的**401 个离散频点**，均有 `K>1` 且 `|Δ|<1`；全网格最小 K 约 `2.50e7`（9.7 GHz），最大 |Δ| 约 `0.9989896`（0.1 GHz）。带内最大 |Δ| 约 `0.30598`。低频处 `1-|Δ|` 仅约 `0.00101`，不能忽略裕量，也不能由离散采样推断连续频域、任意源/负载、工艺角落、大信号或布局后的稳定性。

同一宽频源档按 8–12 GHz 带边重算，最差 S11 约 `-10.08 dB`、最差 S21 约 `-12.18 dB`、最差 S22 约 `-0.17 dB`、增益纹波约 `16.43 dB`、NF 约 `8.12 dB`。因此，**采样 K/Δ 通过不等于 LNA 规格通过**；输出匹配、增益、纹波和噪声均表明该基线仍是教学探针。理想互感、电感与无损电容没有物理 Q/SRF、耦合布局或 PEX 验证。

只读复核：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage `
  results/runs/teaching_three_stage/20260926T201404Z_b301241a
```

旧 161 点档案的重审、两网格共享频点的跨归档数值对照和重哈希伪造稳定性字段的负例均有自动测试。该运行 `not_lna_result=true`、`spec_pass=null`，不是授权 PDK LNA、物理 MCR 或论文 Fig. 7/Table IV/V 的复现。下一门槛仍是可实现的级间/输出无源与授权 PDK CDF/PCell 参数传播，再对合格候选做连续带外、角落和大信号稳定性验证。
