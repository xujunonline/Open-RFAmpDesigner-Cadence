# 审查问题台账

P0：会产生错误成功结论；P1：关键数据或流程可靠性；P2：文档、验证或后续开发缺口。状态 `closed` 表示问题已有相应范围的验证证据，并不保证未来运行永久稳定；`documented` 表示原论文歧义已记录；`planned` 表示后续功能范围缺口。具体英文依据见同目录 `2026-09-25_paper_claims_matrix.md`。

| ID | 级别 | 发现与证据 | 修复/验证 | 状态 |
| --- | --- | --- | --- | --- |
| A01 | P0 | `fullchain_violations` 对缺失 S11/NF/IP1dB/功耗使用默认值，可能给不完整结果错误评分；原代码见 Git diff。 | 所有必需指标缺测返回 `incomplete/pass=false`，NaN/Inf 拒绝；`tests/test_cost_functions.py`。 | closed |
| A02 | P0 | `Refiner.refine({})` 过去会走 `accepted` 分支。 | 现核对仿真 envelope、当前 spec/candidate/seed 和分析类型，并在本地重算 violation；真实后端未完成前零违规结果仍不接受，`tests/test_agent_safety.py`。后端原始产物真实性属阶段 05/10 待实现范围。 | closed（防误受理） |
| A03 | P1 | `fullchain_eval` 非 dry-run 调注释模板并可能仅凭进程返回码称 `ok`。 | 明确 `not_implemented/pass=false`，直至真实脚本和指标提取实现；同上测试。 | closed |
| A04 | P1 | `active_sizing` 接受负 power ratio，lookup 可为所有级选择同一行或超出级电流。 | 校验非负有限比例、正预算、stage ID 和单级电流上限；测试覆盖。 | closed |
| A05 | P1 | Touchstone 接受 NaN、非递增频率，零 S 系数产生无限 dB；0.1 GHz 浮点误差可排除带边。 | 解析器输入校验、50 ohm 记录、有限 dB floor、带边近似包含；`tests/test_touchstone.py`，旧真实 S2P/PSFASCII 交叉重算 47 点。 | closed |
| A06 | P1 | 二端口 runner 固定远程/本地目录，复跑会覆盖结果；`metrics.json` 保存私有 SSH 目标和命令。 | 独立 run_id 与默认运行子目录；重复指定已有目录时报错；指标 JSON 仅保留返回码和状态。新版 runner 已在独立目录 `20260925T152506Z_273884f2` 实机通过。 | closed |
| A07 | P1 | 仅有五个示例数值也能让 `fullchain_violations` 返回 `pass=true`。 | 无来源时返回 `unverified_score/pass=false`；标记真实 Cadence 且运行成功才允许评为 pass，测试覆盖。真实后端尚未实现，来源由未来 backend 提供。 | closed |
| A08 | P1 | 论文 PDF p.8 Table III 标 `IP1dB`，同页正文把 S9/S10 解释成 `OP1dB=9 dBm`；无法从公开材料推出单一口径。 | YAML 保留逐格对应的 IP1dB 阈值，报告和方案写明歧义；将来 IP/OP 分别提取，不能把 -15 dBm 换成 9 dBm。 | documented |
| A09 | P1 | 审查后真实复验的 SSH 在 banner exchange 阶段超时；新运行止于 `mkdir_failed`，没有 Spectre 日志。 | 对照 OTA 项目确认不是密钥或 `.bashrc`；09-25 硬重置后短时通过但复发，当时宿主仅余约 600 MB。09-26 原 6 GB 配置下已完成 15 轮、约 15 分 36 秒的 SSH/Tools 连续检查及首/中/末三次 OCEAN/Spectre 环境 smoke；15 轮全通过，宿主可用内存最低 2660 MB，末次 OCEAN 后又独立复查 SSH/Tools 成功。原始记录在 `results/logs/a09_20260926_acceptance/`；验收范围仅为该内存条件下的短时/轻负载运行，长时间或高负载扫描仍需单独验证，见 `docs/18_ssh_recovery_from_ota.md`。 | closed（限定范围） |
| A10 | P2 | `run_spec.py` 不带 `--dry-run` 仍只生成 dry-run；重复 spec ID、非法规格数值和非有限 JSON 不被拒绝。 | 强制显式 flag；Spec 与 loader 校验；JSON 序列化前拒绝非有限值；`tests/test_config_contract.py`。 | closed |
| A11 | P2 | `docs/12`、迁移文档、agent 差异和步进指导的“当前状态”相互矛盾，部分仍说 RF S 参数未实测。 | 保留历史日期、补最新状态与证据；更新文档入口。 | closed |
| A12 | P2 | 多个方案文档的示例 JSON 含 `pass:true` 和似真数值，易被误读为实测。 | 在长方案与 agent 示例前明确标为示意；真实指标只引用运行目录。 | closed |
| A13 | P2 | Table II/III 与公式 (1)(2) 原来缺逐项论文数值回归。 | `tests/test_paper_tables.py` 绑定 PDF p.5/p.8 公开值及公式边界。 | closed |
| A14 | P2 | OCEAN 的 noise/compression/fullchain、MCR、基线、图表及 agent loop 仍为模板或骨架。 | 在清单与状态表逐项标出，不把缺功能写成已实现；依 `docs/15` 后续阶段实施。 | planned |
| A15 | P1 | `Refiner` 原来仅校验违规量有限，负值、布尔值及与分项不一致的 `total_violation` 仍可能被当作有效评分。 | 校验非负、非布尔且总量与五个分项一致；可选 ripple 也须非负有限；`tests/test_agent_safety.py` 回归覆盖。 | closed |

本台账不声称发现了全部可能缺陷。A06/A09 的先前失败记录仍保留；A09 关闭的是上述限定窗口的可用性验收，不是长时高负载稳定性的保证。`planned` 是功能范围缺口，不是可以靠单元测试关闭的缺陷。
