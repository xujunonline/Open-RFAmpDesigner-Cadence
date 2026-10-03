# Spectre noise/NF 数据链路：被动二端口实机验收

## 当前状态

2026-09-25：`src/orfadc/cadence/noise_metrics.py` 已能从指定名称的 PSFASCII 标量迹线构建逐频点 NF 表、转换线性 noise factor、校验 NFmin 与 S 参数频率轴、输出 CSV，并给出带内最差 NF。测试使用人工构造数据，不是 Spectre 实测。SSH 短时恢复期间新版二端口及 OCEAN smoke 曾实机复验，但随后 VM 再次失响应；noise 本身尚未运行，阶段 02 不能验收。

2026-09-26：A09 限定范围验收后，在原 6 GB VM 下完成真实 Spectre 25.1 `sp` + `donoise=yes` 被动二端口测试。可重复 runner 的结果在 `results/runs/rf_smoke/passive_noise/20260926T011402Z_80ac76f0/`：47 个 0.1-20 GHz 频点，50 Ω 端口，Spectre 0 errors/0 warnings/1 notice；PSFASCII `NF`/`NFmin` 是 dB，`F`/`Fmin` 是线性 noise factor。两组单位换算在逐频点核对后吻合，NF 与 S 参数频率轴一致。该结果是被动 RLC 数据链路实测，不是有源 LNA 的噪声性能或论文规格通过结论。

`circuit/spectre/ideal_twoport_noise_unverified.scs` 的文件名保留最初的“未验证”状态；其语法现已由本机 Spectre 25.1 的 `spectre -h sp` 和独立实跑确认。原始证据包括 `netlist.scs`、`spectre.log`、`sp_noise.noise.sp`、`sp_noise.sp`、`ideal_twoport_noise.s2p` 和归一化 CSV。该电路是被动 RLC，不是 LNA。

## 指标契约

| 字段 | 含义 | 来源与处理 |
| --- | --- | --- |
| `freq_hz` / `freq_ghz` | 分析频率 | 原始 PSFASCII `freq`；必须正、有限、严格递增。 |
| `nf_db` | 指定端口、参考阻抗与源条件下的 noise figure | 明确指定原始迹线单位为 `db` 或 `linear_factor`；后者用 `10 log10(F)` 转换。不可把输出噪声谱密度直接当 NF。 |
| `nfmin_db` | 噪声匹配可达到的最小 NF | 仅当 Spectre 确有独立原始输出且频率对齐时填写；否则 `null`。不能从普通 NF 推断。 |
| 带内汇总 | 最差 NF/NFmin 与频点数 | 当前仅对实际落入带内的样点汇总，不插值；边界需在仿真频率网格上明确覆盖。 |

`NF=10 log10(F)`，其中 `F` 是线性噪声因子。该转换不适用于 V/sqrt(Hz)、V^2/Hz 或 dBm/Hz 等噪声谱密度。带内汇总值不是论文 LNA 的达标结论；只有有源 LNA 的完整仿真、规格和来源记录都齐全，才能进入 fullchain pass/fail。

如果已经有独立 PSFASCII 原始迹线，可在确认真实信号名及单位后运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m orfadc.experiments.extract_noise --psfascii <raw.sp> --nf-signal <verified_name> --nf-unit db --low-ghz 1 --high-ghz 2 --output <new_result_dir>
```

可选 `--nfmin-signal` 和 `--sparams`；后者要求与 noise 使用相同频率网格。工具保留原始数据、CSV 和 `metrics.json`，但固定写入 `status=parsed_unverified`、`simulation_status=unknown`、`spec_pass=null`，因为解析一个文件本身不能证明 Spectre 运行、端口定义或电路类型。

## 已完成的受控验收与复跑

运行前先确认 SSH 与宿主内存；在本轮约 2.6 GB 可用内存下使用单进程、47 点低预算仿真：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m orfadc.cadence.verify_remote
python -m orfadc.experiments.run_passive_noise
```

`run_passive_noise` 为每次运行创建独立目录，不覆盖既有产物。它归档远端网表与日志，下载 S2P/PSFASCII，确认 `NF`/`NFmin` 的 dB 类型、`F`/`Fmin` 的线性类型、50 Ω 参考阻抗、47 点频率对齐及逐点 `10 log10(F)=NF`，然后写 `noise.csv`、`sparams.csv`、`metrics.json`。本次带内最差 NF 约 8.4155 dB，NFmin 约 0 dB；这是 0.1-20 GHz 被动测试电路的值，不应用于论文 LNA 对比。输出固定 `not_lna_result=true`、`spec_pass=null`。

## 后续有源 LNA 验收

1. 先按 `docs/18_ssh_recovery_from_ota.md` 复查 SSH/Tools 和宿主内存；长时或并行任务不在 A09 的验收范围内。
2. 对授权 PDK/教学模型的有源单级 LNA 建立 DC、S 参数和 noise testbench，固定输入/输出参考平面与 50 Ω 条件。
3. 归档 PDK 标识、原始网表、`spectre.log`、PSFASCII、S2P、温度与偏置；确认器件和端口实际定义后提取 NF/NFmin。
4. 只有有源 LNA 的完整仿真才可进入 LNA 指标判断；教学模型仍不能与论文 N65 数值直接比较。

公开 Spectre 语法参考：[Cadence Community 的 SP noise 示例](https://community.cadence.com/cadence_technology_forums/f/mixed-signal-design/42798/spectre-mdl-help-for-sp-donoise-yes-analysis)。该页面提供语法示例，不替代本机版本验证或原始结果检查。
