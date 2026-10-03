# 阶段 04：真实 HB 压缩点数据链路（共源诊断，不是 LNA 验收）

2026-09-26，在已授权 OA 共源级的**私有网表副本**上做 Spectre 25.1 单音 HB。`src/orfadc/experiments/run_hb_diagnostic.py` 只接受已有网表的 SHA-256、RD/VBIAS、输入 dBm、基频和谐波数；输入/输出仍是 50 Ω 端口。输入端口改为 `type=sine dbm=<Pin> freq=<f>`，输出端口仅作 `type=dc` 的 50 Ω 终端，保留原 DC/SP/noise 并附加 `hb hb fundfreqs=[f] maxharms=[N]`。不改 MOS/PCell、模型或源连接；生成的网表及 PDK 伴随文件只存 Git 忽略的运行目录。每次运行先检查宿主可用物理内存至少 2.66 GiB，SSH/Spectre 有超时，逐点独立保存网表、日志、DC/SP/noise/HB 原始 PSFASCII、指标及 SHA-256 清单。

功率参考平面：`PORT1 dbm` 是其 50 Ω 共轭匹配端可提供的输入功率；输出 `PORT2` 是实际 50 Ω 终端。`hb.fd.pss_hb` 的基波电压/电流是峰值相量，故 `Pout=Re(V1·conj(I1))/2=|V1|²/(2·50 Ω)`。解析器逐点核对 `I1=V1/50 Ω` 和基频标头，输出基波功率 dBm 与 `Pout−Pin`，并读取同一次仿真的 `sp.sp` 中精确基频 `S21` 作低功率检查。此定义不把输出节点电压增益混作传输功率增益。单点 `results/runs/hb_diagnostic/20260926T114602Z_208f211d/` 在 -40 dBm、10 GHz、7 谐波下得 `Pout≈-37.76793 dBm`、功率增益 `2.232067 dB`、同次 SP `S21=2.232983 dB`，差约 `-0.000916 dB`；电流/50 Ω 相对差约 `1.7e-16`，清单验证通过。3 谐波运行曾提示谐波数可能不足；7 谐波无该警告，在 -40 dBm 两者基波增益差约 `6e-14 dB`。7 谐波运行仍有 5 条既有 PDK 警告，不能当作工艺签核。

`src/orfadc/experiments/run_hb_sweep.py` 顺序扫功率，要求 4–12 个严格递增点、每点独立原始归档；前三个低功率点按 `extract_p1db` 建线性增益参考，若参考不线性或 1 dB 交点未被相邻实测点夹住，返回结构化 `invalid_linear_reference`/`unbracketed`，不外推。`results/runs/hb_sweeps/20260926T114827Z_0d051b05/` 的 7 点粗网格在 -10 与 0 dBm 之间夹住交点，给出 `IP1dB≈-9.60 dBm`；该 10 dB 夹持太粗。`results/runs/hb_sweeps/20260926T115026Z_5f5c561f/` 的 9 点加密网格以前三点 -60/-50/-40 dBm 建立 `2.232644 dB` 参考，交点在 -9 与 -8 dBm 间，线性插值得到 **诊断级** `IP1dB≈-8.987 dBm`、`OP1dB≈-7.754 dBm`。9/9 点清单与原始基波重提取一致，最大归档差 0；各 HB 均收敛、日志 0 errors/5 既有 PDK warnings，未见“谐波数不足”警告。约 0.61 dB 的粗/密网格差体现步长敏感性，不能把插值的小数位当测量精度。

`src/orfadc/experiments/audit_hb_sweep.py` 是独立、只读的归档审计器。它核对扫参配置、每点运行目录及哈希清单中是否确实包含 HB 基波和 SP 原始文件，再从原始 PSFASCII 重提取每点基波功率与同频 S21，逐项比较 `metrics.json` 和 `power_sweep.csv`，最后重新计算摘要中的 IP1dB/OP1dB。现有 7 点和 9 点归档均通过；合成反例覆盖原始文件篡改、重新哈希后的伪造指标、CSV/摘要漂移和原始文件未纳入清单。SHA-256 清单只能检查归档内部一致性，**不是**防止有权限者整体重写归档的数字签名。

先前失败归档保留：第一次错误预期 `hb.hb`，而本机实测文件是 `hb.fd.pss_hb`、`hb.fi.pss_hb`、`hb.td.pss_hb`；第二次三份原始文件已下载，但因结果 envelope 缺 `source`，没有生成合格 `metrics.json`。这两项是 Python 数据链故障，不是 Spectre/HB 许可证故障。另发现 Windows 文本写入会把已有 CRLF 变为 `CRCRLF`；现有有源候选和 HB 生成器均按 UTF-8 字节写出，回归检查新归档无重复换行，不更改旧失败运行。

复现实验入口（`<...>` 在本机 Git 忽略目录填写，不写进仓库或 LLM 请求）：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.run_hb_sweep `
  --template <私有OA原始网表> --template-sha256 <64位SHA256> `
  --rd-ohm 150 --vbias-v 0.67 --frequency-ghz 10 --harmonics 7 `
  --powers-dbm -60 -50 -40 -12 -11 -10 -9.5 -9 -8
py -m orfadc.experiments.audit_hb_sweep `
  results/runs/hb_sweeps/20260926T115026Z_5f5c561f
```

**复现边界**：这是原有 OA 单管共源诊断电路经直接 Spectre 派生网表的 HB 结果，不是论文三阶段 LNA，也不是 PDK 参数传播已核验的可制造设计。该电路宽带 S11 近 0 dB、采样网格 K<1，仍未满足增益、匹配和稳定性；没有 PEX/角落/温度与更细功率步长验收。故这里的 IP1dB/OP1dB 只证明 Stage 04 的 Cadence 数据链、参考平面和插值流程，`not_lna_result=true`、`spec_pass=null`。后续须在合格 LNA testbench 上重复，并按无条件稳定性、谐波收敛、功率步长和工艺角落审核。
