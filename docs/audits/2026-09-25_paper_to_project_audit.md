# 2026-09-25 英文论文到工程审查报告

本文件保留 2026-09-25 审查过程与当时失败状态；最终收尾判定和 2026-09-26 验收证据见 [审查收尾](2026-09-26_audit_closure.md)。

## 审查结论

论文 Table II 的变量范围、Table III 的十个规格及公式 (1)(2) 已与仓库配置/代码逐项核对，并加回归测试。当前项目的真实 Cadence 证据覆盖远程执行环境和 PDK 无关被动二端口 S 参数；LNA 的 noise、压缩点、Stage 1/2/3、fullchain、多智能体搜索和论文表图仍未实测。审查发现并修复了会把缺测或 mock 数据当成通过候选的路径。审查后新版本的远程复验因 SSH banner exchange 超时而未执行 Spectre，因此阶段 00 保持 `partial`。

详细依据：`2026-09-25_paper_claims_matrix.md`（论文）、`2026-09-25_file_inventory.md`（文件）、`2026-09-25_traceability_matrix.md`（数据流）和 `2026-09-25_issue_register.md`（问题）。

## 范围与方法

1. 记录 Git 未提交修改并保留，检查源码、配置、网表、测试、文档、论文资料和本地运行产物。原始历史聊天只核对其用途和忽略状态，不复制敏感内容。
2. 使用 14 页英文 PDF 的原始表格/图与正文，视觉核对 p.8 Table III 和 Fig. 7，抽取文本仅用于定位。
3. 运行原始测试基线 `20 passed`，审查中增加失败路径与论文值测试；S1 dry-run 可生成候选，未带 `--dry-run` 的调用现明确报错。
4. 从旧真实 `s2p` 与 PSFASCII 交叉读取 47 个频点，并重算 S 参数全带汇总。S21 复数最大差约 `1.5e-16`，频率差不超过 `9.6e-6 Hz`；汇总 S11 -0.2489 dB、最低 S21 -12.9554 dB、S22 -1.8137 dB、ripple 12.5339 dB。它们仅属于被动低通二端口。
5. 尝试新版 runner 一次；其本地失败记录为 `mkdir_failed/returncode 255`，只读 SSH 探针明确报 `Connection timed out during banner exchange`。没有重启或改变虚拟机配置。

## 主要发现

- **论文内部口径冲突**：PDF p.8 Table III 表头/阈值为 IP1dB；同页正文讨论 S9/S10 则称 OP1dB 9 dBm。仓库保持表中 IP1dB 规格，并记录 OP1dB 必须独立测量，不能混用。
- **论文 Fig. 7 标注冲突**：图内曲线含 S21，图注却称 S11/S22。未来本工程图必须按实际原始列名标注。
- **公式实现与完整工具之间有断层**：Stage 2/3 cost 与论文数学形式一致，然而作者的 PSO、SA、MCR 模型和全链仿真并未在当前工程实现。不能把 cost 单元测试等同 Table I 工具复现。
- **误判通过风险已处理**：缺测违规量、无来源分数、Refiner 空反馈及 fullchain 注释模板均不能再报告真实 pass。
- **数据链与文档状态已梳理**：二端口 runner 不再覆盖既有实验目录，新增 JSON 不写入 SSH 目标；文档已区分历史实机验收、当前 SSH 失败与未实现的 LNA 分析。

## 验证与限制

本地 Python 测试为 `36 passed`，`compileall` 通过；测试的 pytest/Python 3.13 弃用警告来自测试框架，不是 RF 计算错误。旧真实 Spectre 日志为 0 errors、0 warnings、1 notice。新版本尚未获得真实 Spectre 成功运行；A06/A09 的远端验证待 SSH 恢复。真实 PDK、OA schematic、NFmin、IP1dB/OP1dB、MCR 校准、五 seeds/表图与 LLM 费用均无项目证据，不列为“完成”。

审查报告形成后，同日继续进行了独立的本地 noise/NF 管线准备；当前测试增至 `47 passed`。该新增范围见 `docs/17_noise_data_pipeline.md`，不改变本报告对真实 Cadence noise 未验证的结论。

同日晚些时候，依据原 OTA 项目记录定位并经用户授权恢复失响应虚拟机。新版二端口 runner 在独立目录实测通过，OCEAN smoke 同样返回 `ok`；A06/A09 已关闭。详见 `docs/18_ssh_recovery_from_ota.md`。本报告前述 SSH 失败为当时审查快照，不应误读为当前连接状态；真实 LNA noise/压缩点仍未完成。

稳定性复查补记：上述成功数分钟后，SSH/Tools 再次失响应。A06 的功能性复验仍成立；A09 已重开为持续运行环境阻塞。宿主可用物理内存约 600 MB，故不再仅靠重复硬重置宣称解决。当前状态以 `docs/16_implementation_status.md` 为准。

## 继续执行

1. 恢复 SSH banner 交换后运行 `python -m orfadc.experiments.run_ideal_twoport`，核对新目录下 `metrics.json`、S2P、PSFASCII 和日志；再运行 OCEAN 环境 smoke。
2. 按 `docs/15_autonomous_completion_prompts.md` 阶段 01/02 完成完整 RF metrics 契约和 Spectre noise 测试。
3. 取得本项目可用的授权器件/库并建立单级 LNA；此前保持 LNA 指标未验证。

验收命令（项目根目录）：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m compileall -q src
python -m pytest tests -q --basetemp=results\runs\.audit_all_tmp
python -m orfadc.experiments.run_spec --spec S1 --dry-run
git diff --check
```
