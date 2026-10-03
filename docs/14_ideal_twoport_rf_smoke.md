# Spectre 理想二端口 RF 冒烟仿真

## 1. 目的与边界

本步骤验证以下真实闭环：

```text
Windows Python
  -> SSH/SCP
  -> Linux VM 中的 Cadence Spectre
  -> sp 分析
  -> Touchstone + PSFASCII
  -> Python 解析
  -> CSV + metrics.json + 日志归档
```

测试对象是由 `L + C + R` 构成的被动二端口，不包含 MOS、偏置或商业 PDK。因此它不是 LNA，不代表论文电路，也不能用于报告 LNA gain、NF、IP1dB 或功耗。

## 2. 电路与分析

网表位于 `circuit/spectre/ideal_twoport.scs`。输入和输出均使用 50 ohm `port`，中间网络参数为：

| 参数 | 数值 | 用途 |
| --- | ---: | --- |
| `RLOSS` | 5 ohm | 串联损耗 |
| `LPATH` | 1 nH | 串联电感 |
| `CSHUNT` | 0.5 pF | 对地电容 |

`sp` 分析从 100 MHz 扫到 20 GHz，每十倍频程 20 点，并直接导出 Touchstone v1 的 RI 格式数据。

## 3. 执行方法

前提是被 Git 忽略的 `config/remote_cadence.local.yaml` 已正确配置。

```powershell
cd F:\Open-RFAmpDesigner-Cadence
$env:PYTHONPATH = "$PWD\src"
python -m orfadc.experiments.run_ideal_twoport
```

执行器位于 `src/orfadc/experiments/run_ideal_twoport.py`。解析器位于 `src/orfadc/cadence/touchstone.py`，支持 Touchstone v1 二端口的 RI、MA 和 DB 三种表示。

## 4. 真实验收结果

2026-09-25 的实机运行结果：

- Spectre 版本：`25.1.0.054`；
- 分析类型：`sp`；
- 频率范围：0.1 GHz 到 20 GHz；
- 数据点数：47；
- 日志：0 errors、0 warnings、1 notice；
- 当时单元测试：20 passed；后续审查增加了边界与失败路径测试。

全带汇总值为：

| 汇总量 | 数值 |
| --- | ---: |
| 最差 S11 | -0.249 dB |
| 最低 S21 | -12.955 dB |
| 最差 S22 | -1.814 dB |
| S21 ripple | 12.534 dB |

这些数值符合简单低通网络在 20 GHz 附近严重失配和衰减的预期。它们只证明解析与汇总逻辑使用了真实 Spectre 数据，不是设计指标，也没有 pass/fail 含义。

## 5. 结果文件

首次成功运行的目录 `results/runs/rf_smoke/ideal_twoport/` 包含以下文件。审查后的运行器会为每次新运行创建独立子目录 `results/runs/rf_smoke/ideal_twoport/<timestamp>_<id>/`，避免覆盖旧数据；`metrics.json` 只保存脱敏的步骤状态与返回码。

| 文件 | 内容 |
| --- | --- |
| `netlist.scs` | 本次实际运行的网表副本 |
| `spectre.log` | Spectre 原始日志 |
| `spectre.stdout.log` | SSH 捕获的标准输出 |
| `spectre.stderr.log` | SSH 捕获的标准错误 |
| `ideal_twoport.s2p` | Spectre 导出的 Touchstone |
| `sp_test.sp` | Spectre PSFASCII 原始结果 |
| `sparams.csv` | Python 标准化后的 S 参数表 |
| `metrics.json` | 状态、语义边界、汇总指标和运行元数据 |

`metrics.json` 固定包含 `not_lna_result: true`，防止后续报告误用这组结果。

## 6. 下一步

下一阶段是建立 noise/NF 数据链路。应先用可控测试电路确认 Spectre noise 输出格式和 Python 提取，再接入授权 PDK 的共源或 cascode 单级 LNA。只有有源 LNA 的 DC 工作点、S 参数、gain、NF 和 power 都验证后，才进入 active sizing lookup table 和多智能体工具调用。
