# Stage 05：同电路 DC/SP/noise 与 HB 配对审计

此实验解决一个候选证据问题：单独的 OA 共源小信号候选与单独的 HB 压缩扫描，能否被证明是同一个电路的诊断数据。配对仅使用 2026-09-26 已归档的 Spectre 原始结果，**没有**新仿真，也不把两份不同网表仅凭相同 RD/VBIAS 合并。

## 来源与核对方法

- 小信号候选：`results/runs/S1/seed0/S1_seed0_oa_diag/20260926T113051Z_5475bf0d/`，RD=150 ohm、VBIAS=0.67 V，包含候选快照、网表、ADE 模型伴随文件、DC/SP/noise PSFASCII、47 点 CSV、Spectre 日志和哈希清单。
- HB 扫描：`results/runs/hb_sweeps/20260926T115026Z_5f5c561f/`，10 GHz、7 谐波、9 个输入功率点，每点有独立网表、ADE 模型伴随文件、SP/HB 原始文件、日志和哈希清单。
- `audit_diagnostic_pair.py` 先调用 `read_evidenced_metrics` 和现有 `audit_hb_sweep`，再从小信号原始 PSFASCII 独立重提取九项指标；检查候选参数与 HB 配置一致。
- 对每个 HB 点，从候选网表重新生成唯一允许的变体：输入 50 ohm 端口加入该点的 `dbm/freq`，输出 50 ohm 端口改为 `type=dc`，最后增加一行相应的 `hb` 分析。忽略空行和行尾空白后，整个 HB 网表必须逐行相等；ADE 模型伴随文件必须逐字节相等。同频原始 SP S21 还须与候选相差不超过 0.001 dB。
- HB 摘要必须由原始九点重新夹持并计算 IP1dB/OP1dB；无夹持点则拒绝出具本配对报告。报告记录原候选与九个 HB 清单 SHA-256，可再次执行只读审计；SHA-256 是本地一致性校验，不是数字签名。

源模板 SHA-256 **不相同**。这不能证明两份模板文件相同；本次可配对的依据是实际运行网表除预期激励/HB 差异外相等、模型伴随文件相同，以及 10 GHz 小信号 S21 从原始数据提取后逐值相同。保留这个差别，不用模板哈希替代电路比较。

## 已验证结果

只读配对报告保存在 Git 忽略的 `results/runs/diagnostic_pairs/20260926T153255Z_db111acc/`，`evidence_manifest.json` 通过；随后重新读取源归档重建整个报告，结论为 `verified`。小信号候选的 10 GHz S21 与 HB 同次 SP 均为约 2.232983 dB；候选全 0.1–20 GHz 网格的最差 S21 约 -0.180 dB、最差 S11 约 -0.0031 dB、最差 NF 约 4.291 dB、电源电流约 2.389 mA。九点 HB 夹持给出诊断级 IP1dB 约 -8.987 dBm、OP1dB 约 -7.754 dBm。报告把这些值放入同一**诊断**指标对象，`not_lna_result=true`、`spec_pass=null`，不产生论文 Table IV/V 行。

复核入口：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_diagnostic_pair <candidate_run_dir> <hb_sweep_dir>
```

该命令将新建一个独立派生报告；程序化 `audit_diagnostic_pair_report(report_dir, candidate_dir, sweep_dir)` 可只读复核已存报告。测试覆盖元件改动、模型文件变化、原始小信号指标被改与报告漂移。

## 验收边界

该电路是授权工艺的**单管共源诊断**，不是稳定、匹配的 LNA；原 PDK CDF/PCell 几何传播尚未通过。HB 是从同一有效电路派生的独立 Spectre 作业，不是一次完成所有分析的 LNA fullchain。最差 S11 接近 0 dB、采样稳定性不满足，亦无后仿或角落数据。它仅补强 Stage 05 的“同候选跨分析证据绑定”方法；真正的 `fullchain_eval` 仍需要合格 LNA 电路、压缩点、全带指标、同一候选快照和实测原始归档。
