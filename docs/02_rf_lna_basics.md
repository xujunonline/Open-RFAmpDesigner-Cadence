# 从 OTA 到 RF LNA

你已经能用 Cadence/Python 自动扫 OTA。迁移到 LNA 时，保留“参数 -> 仿真 -> 指标 -> cost -> 记录”的工程结构，但替换指标体系。

| OTA | LNA |
|---|---|
| 差模增益 | S21/gain |
| UGF/PM | 通带带宽、ripple、稳定性 |
| 输出共模 | bias/common-mode 检查 |
| 电源电流 | power/current budget |
| 输入等效噪声 | NF/NFmin |
| 输出摆幅 | IP1dB/OP1dB |

学习顺序：

1. S 参数和 50 ohm 端口；
2. Smith 圆图和 L 型匹配；
3. LNA 噪声与 Friis 公式；
4. 源退化电感；
5. 大信号压缩点；
6. 宽带 MCR/RLC 网络；
7. Cadence sp/noise/HB testbench；
8. Python 指标提取。

