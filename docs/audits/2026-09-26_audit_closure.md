# 2026-09-26 论文到工程审查收尾

## 判定

**审查工作完成，项目实现未完成。** 英文论文的核心事实已经映射到规格、公式、工具、Cadence 输入与结果链；相关源码、测试、配置、网表、文档和既有实测产物均纳入文件清单及问题台账。所有当前可在本地修复的 P0/P1 误判路径已修复并测试。审查收尾时 `A09` 尚在观察，后续同日完成限定范围验收（见文末补记）；`A08` 是论文自身的 IP1dB/OP1dB 歧义；`A14` 是尚未实现的项目阶段。

审查依据：[2026-09-25 主报告](2026-09-25_paper_to_project_audit.md)、[论文事实矩阵](2026-09-25_paper_claims_matrix.md)、[文件清单](2026-09-25_file_inventory.md)、[数据追踪矩阵](2026-09-25_traceability_matrix.md)、[问题台账](2026-09-25_issue_register.md)。这组材料的状态是“已做过可审计的逐项核对”，不是“已经发现并消除所有未知缺陷”。

## 完成门槛核验

| 原审查提示词门槛 | 判定与证据 |
| --- | --- |
| 英文论文核心事实及单位可追踪 | 通过；论文事实矩阵列出 PDF 页码、Table/Fig/Eq 与项目落点；Table II/III 和公式 (1)(2) 有回归测试，公式 (3) 标为未实现。 |
| 相关文件、未跟踪项和跨层数据链纳入审查 | 通过；文件清单包括审查后新增 noise/SSH 文件和被忽略的真实运行目录；私有 YAML 只核对存在性；数据追踪矩阵显式标出到 LNA/agent 的断链。 |
| 可本地修复的 P0/P1 已验证，P2 已处理或登记 | 通过；问题台账 A01-A15：P0 2 项已关闭；P1 8 项中 6 项关闭、A08 原文歧义已记录、A09 环境稳定性观察中；P2 5 项中 4 项关闭、A14 为后续功能。A09/A14 不被误标为已实现。 |
| 本地测试及可用 Cadence smoke 有原始证据 | 通过；最终 48 项测试、编译、dry-run、两次新版二端口 S2P/PSFASCII/Spectre 日志及 OCEAN 报告均已核对；真实 noise/LNA/压缩点没有成功声明。 |
| 文档状态一致、下一阶段可执行 | 通过；README、索引、实施状态及本报告分开描述历史失败、短时/轻负载成功和重负载待验；下一步为 A09 受控稳定性验证及阶段 01/02。 |

本节表格记录审查收尾当时的状态；审查门槛的 `通过` 只表示证据已收齐且未解决事项已正确登记，不表示工程所有阶段已交付。A09 的后续验收见文末补记。

## 复核范围与结果

1. 英文 PDF 14 页为第一依据，核对 Table I/II/III、公式 (1)-(3)、Table IV/V/VI 与 Fig. 7-11 的任务结构、变量、单位和统计口径。Table II/III 与公式 (1)(2) 已有数值回归；公式 (3) 的 MCR 数值实现仍缺失。PDF p.8 Table III 的 IP1dB 与正文 OP1dB 表述冲突、Fig. 7 的图内 S21 与图注 S22 冲突，均作为原文歧义保留，未凭猜测改写。
2. 完整性与误判修复涵盖缺测/NaN/Inf、来源与 dry-run、Refiner 非法违规量、被动二端口端口顺序/阻抗/带边、候选运行目录覆盖及私有 SSH 目标外泄。审查后新增的 NF 数据管线仅以人工 PSFASCII 测试，始终写 `parsed_unverified`；没有伪造 Spectre noise 数据。
3. 本地验收：`python -m compileall -q src`、`python -m pytest tests -q --disable-warnings --basetemp=results/runs/.audit_closure_final`（48 passed）、`python -m orfadc.experiments.run_spec --spec S1 --dry-run`；文档相对链接缺失数 0；可公开文件中未发现已知明文密码或私钥头标记；`git diff --check` 无内容错误。上述扫描不是全面的泄密审计，发布前仍应人工复查未跟踪文件。审查期间已有大量用户/先前任务的未提交修改，全部保留，没有重置或删除。
4. 真实 Cadence：2026-09-25 新版二端口 runner 在 `results/runs/rf_smoke/ideal_twoport/20260925T152506Z_273884f2/`，OCEAN 环境在 `results/logs/cadence_environment/20260925_after_vm_reset/`，均有 `status=ok` 及原始结果；2026-09-26 原配置重新启动后，SSH/Tools 多轮正常、SCP 往返 SHA-256 一致、二端口在 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/` 再次完成 47 点，日志 0 errors/0 warnings/1 notice。两个二端口结果均为 `spec_pass=null`，不能代表 LNA 指标。

## 审查收尾时的未关闭事项

| 项 | 状态 | 下一执行动作 |
| --- | --- | --- |
| A08 论文 IP1dB/OP1dB 口径冲突 | documented | 后续有源仿真分别测输入/输出压缩点，不把论文的两个阈值互换。 |
| A09 VMware/SSH 持续稳定性 | monitoring | 轻负载成功不等于重负载稳定；先保证宿主内存余量，再做受控 OCEAN/长时观察。若需改 VMX，必须另行授权。 |
| A14 noise/compression/MCR/agent/baseline 等功能 | planned | 按 `docs/16_implementation_status.md` 从阶段 01/02 推进，保留实测等级。 |

没有作者的 N65 PDK/PCells/post-layout 网表、私有脚本、lookup、KB/EB、prompt 与最终参数，不能严格复现论文数值。当前 PDK 无关 `sp`、SSH/OCEAN 和 48 项单测支持“工程基础已审查并局部实测”，不支持“LNA 或多智能体设计流程已完成”。

## 同日 A09 验收补记

审查收尾之后，A09 在原 6 GB VM 配置、宿主可用内存最低 2660 MB 的条件下完成 15 轮、约 15 分 36 秒的 SSH/Tools 观察及 3 次 OCEAN/Spectre 环境 smoke，全部通过；末次 OCEAN 后的独立复查也正常。证据见 `results/logs/a09_20260926_acceptance/`，详细边界见 `docs/18_ssh_recovery_from_ota.md`。因此台账将 A09 标记为“closed（限定范围）”；上表保留为审查收尾时的历史记录。长时、高负载及并行仿真仍无稳定性保证，也不改变 A14 的未实现状态。
