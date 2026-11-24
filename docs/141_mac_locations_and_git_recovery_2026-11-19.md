# 141 原 Mac 运行位置与 Git 补全记录（2026-11-19）

## 1. 目标与当前执行边界

用户确认：本项目以前就在当前这台 Mac 上运行。此次任务是找到既有项目、虚拟机和文档，并从 Git 下载缺失的可恢复资料。

已从项目历史运行日志与交接记录定位到明确的 Mac 路径，且已经补全审阅副本的 Git 分支、版本标签与可达历史。本次工具执行端仍是独立 Linux 工作区，没有挂载 Mac 的 `/Users`、`/Volumes` 或 `/Applications`；所以本文的 Mac 路径是有记录依据的定位线索，尚不代表本轮已在 Mac 磁盘上确认存在。不能把 Linux 工作区中不存在这些路径解释成 Mac 文件丢失。

## 2. 原运行位置

| 对象 | 历史 Mac 路径 | 依据 |
|---|---|---|
| 项目根目录 | `/Users/jason/Documents/Open-RFAmpDesigner-Cadence` | `results/repro/v2_a3/n65/seed4/S2_first_attempt_ssh_failure.log` 第 21 行，以及 `results/repro/v2_a3/n65_s9s10/v2_S10_seed2_crashed_ssh_dhcp.log` 第 118 行 |
| 虚拟机目录 | `/Users/jason/Desktop/IC618_rf/` | `docs/134_macbook_handoff.md` 第 106 行 |
| 虚拟机配置 | `/Users/jason/Desktop/IC618_rf/IC618_rf.vmx` | 同上 |
| VMware Fusion | `/Applications/VMware Fusion.app` | 同上 |
| VM 管理程序 | `/Applications/VMware Fusion.app/Contents/Public/vmrun` | 同上 |

环境指纹：`docs/132_n65_bringup.md` 记录 Intel MacBook、x86_64、macOS 26.5，虚拟机在本机 Fusion 运行；客体是 CentOS 7.9，使用 IC618 / Spectre 18.1.0.077。`docs/139_experiment_report.md` 记载当时宿主为 Core i9-9980HK、32 GB 内存，客体为 4 vCPU、8 GB 内存。这些是历史配置，接手时以现场核查为准。

`docs/128_ic618_vm_pdk_survey.md` 记录虚拟机磁盘有 18 个非空 `IC618-cl1-s0xx.vmdk` 分片，合计约 70 GB。找到一个 `.vmx` 还不足以证明虚拟机完整；应根据当前 VMX 和 VMDK descriptor 的实际引用检查磁盘及父磁盘。不能把历史分片数量作为当前快照链完整性的唯一判据。

## 3. 文档位置

以下路径均相对于上述项目根目录。这些文件受当前 `main` 跟踪，且已在此次下载的审阅副本中确认存在。

| 文件 | 用途 |
|---|---|
| `docs/139_experiment_report.docx` | 完整实验报告，Word 版 |
| `docs/139_experiment_report.md` | 实验报告的可编辑文本 |
| `docs/137_student_guide.md` | 项目设计方案与仿真过程学习指南 |
| `docs/135_v2_reproduction_report.md` | v2 复现总报告、结论与边界 |
| `docs/133_agent_v2_results.md` | v2 实验过程、补充实验与故障记录 |
| `docs/132_n65_bringup.md` | N65 接入、VM 登录与表征过程 |
| `docs/134_macbook_handoff.md` | Mac 历史迁移、虚拟机位置与故障处理 |
| `references/paper/RFAmpDesigner.pdf` | 论文原文 |
| `references/paper/RFAmpDesigner_中文翻译.md` | 论文中文翻译 |

例如，Word 报告的历史完整位置为：

```text
/Users/jason/Documents/Open-RFAmpDesigner-Cadence/docs/139_experiment_report.docx
```

此外，`.gitignore` 记载了本地历史文档 `docs/project_history/Codex完整聊天记录_RFAmpDesigner.md`、`legacy_workspace_README.md`、`继续任务指南.md` 和 `MANIFEST.tsv`。这些未提交到 Git，需在原 Mac 或用户自己的备份中查找；此次不读取其正文。

## 4. 已完成的 Git 补全

操作对象是此次审阅副本：`/workspace/scratch/a028b1fea3c3/review/Open-RFAmpDesigner-Cadence`。

执行的下载命令为：

```bash
git fetch --unshallow --tags origin '+refs/heads/*:refs/remotes/origin/*'
```

| 核查项 | 结果 |
|---|---|
| 当前 HEAD / `origin/main` | 均为 `f198922b9d912d2498088d0a6f0218c1462df8e1` |
| 远端分支 | `origin/main`、`origin/v2-agentic` 已取得 |
| 浅克隆 | 已解除 |
| 可达提交 | 78 个 |
| 版本标签 | `v1-decision-points`、`v1.1-clean`、`v2-agentic-alpha`、`v2.0` |
| 对象完整性 | `git fsck --full --no-reflogs` 通过 |
| 缺失的已跟踪工作树文件 | 无 |
| 既有未提交修改 | 下载前后 `docs/00_index.md`、`docs/140_takeover_review_2026-11-19.md` 的内容哈希一致 |

这里的完整历史指远端现有分支与标签可达的历史；不包含服务端已删除或从未提交的内容。Git 下载没有执行 pull、merge、reset、checkout、clean 或 push。

论文 PDF 可读，共 14 页；Word 报告的 ZIP 完整性检查通过且包含 `word/document.xml`。较早从主分支删除的资料可以从已取得的历史标签查阅，无需改变当前工作树。

## 5. 能与不能从 Git 恢复的内容

| 内容 | 是否可从该 Git 仓库恢复 | 定位/处理方式 |
|---|---|---|
| 已提交源码、脚本、测试、论文和报告 | 是 | 从对应提交取回缺失文件，保留本机已有修改 |
| `results/repro/` 中已提交实验结果、图表、账本 | 是 | 从 Git 补齐，用于报告重算 |
| `IC618_rf.vmx` 和 VMDK 磁盘 | 否 | 先检查桌面的原 VM 目录；缺失时查原始独立副本或用户备份 |
| `config/*.local.yaml` 与 SSH 私钥 | 否 | 仅核对本机是否存在，不读取、打印或替换正文 |
| `results/runs/` 的真实 PDK 表、Y 参数、噪声校准、PSF | 否 | 在原项目目录或备份中恢复同一 N65 环境的完整缓存 |
| `results/windows_checks/` 队列日志 | 否 | Mac 也沿用此目录名称，原机有则保留 |
| 实际 KB/EB 和本地完整历史文档 | 多数未跟踪 | 查本机目录与备份，明确后续实验是否继续使用 |

对全部可达 Git 历史的路径扫描没有发现 VMX、VMDK、OVA、OVF、QCOW2、VHD/VHDX 或 ISO；LFS 列表为空。因此，虚拟机不在这个仓库中，不能通过 Git 下载补回。

## 6. 在 Mac 上执行定位与补缺

配套脚本：`scripts/locate_restore_mac.py`。它只使用 Python 标准库，支持 Python 3.9 及以上。

下载该脚本后，在 Mac 终端运行（按实际下载位置调整）：

```bash
python3 "$HOME/Downloads/locate_restore_mac.py"
```

脚本优先检查历史路径和当前用户对应目录，并在必要时用 Spotlight 查找同名项目或 VMX。已有多个有效项目副本而无法唯一确定时，会列出候选，要求用参数指定：

```bash
python3 "$HOME/Downloads/locate_restore_mac.py" \
  --repo "/Users/jason/Documents/Open-RFAmpDesigner-Cadence"
```

如只需定位与检查：

```bash
python3 "$HOME/Downloads/locate_restore_mac.py" --check-only
```

补缺遵循当前工作树版本：先更新远端引用和标签，再从**当前 HEAD** 恢复缺失的已跟踪普通文件，不把最新远端文件混进旧版本代码。已有文件和暂存区相关改动保留；符号链接、子模块或有符号链接父目录的路径跳过。若远端 main 与本机 HEAD 不同，只报告差异，不自动合并或切换分支。

脚本会检查 VMX 引用的磁盘及小型文本 descriptor 的分片/父磁盘引用，不读取虚拟磁盘中的客户机文件。它会列出关键文档、PDK 缓存目录、本地配置和专用密钥的存在状态，不读取机密配置或私钥正文；不会启动/停止虚拟机、修改 VMware 网络、SSH 进入客体或运行 Cadence/LLM。

运行报告以带时间戳的 `recovery-<时间>-<进程号>.json` 保存到 `~/Documents/RFAmpDesigner-recovery/`。后续以报告中 Mac 现场的“存在、缺失、恢复、保留、无法从 Git 恢复”结果作为依据，再处理确实缺失的本地资产。

## 7. 脚本验证

本次在 Linux 的临时 Git/VM fixture 中完成 9 项标准库测试，并做了独立代码审阅和补充验证。覆盖已有修改保留、暂存删除保留、索引/HEAD 不变、按当前 HEAD 恢复而不混入新上游内容、符号链接父目录保护、原子写入不覆盖、只检查模式、VM 缺片与零字节分片识别、非 VMDK 引用不读取，以及远端地址校验。

对于未解析内嵌 descriptor 的大型磁盘，脚本会将磁盘链完整性标为未知；文件存在性不等于启动或完整性验证。Git 错误只报告类别与退出码，不输出可能带凭据的原始错误。Python 编译与 Python 3.9 语法检查通过。这些验证不代替 Mac 现场运行。

审阅后脚本 SHA-256：`120f30bb36f7e6a2207b7bb77e77f2ba05cf7d90ec042c95bea66f33145c718c`。

## 8. 尚待 Mac 现场完成

本轮已完成历史路径定位和审阅副本的 Git 补全。Mac 现场是否仍有原仓库、VM 磁盘分片、N65 缓存及私密配置，需要上述脚本在 Mac 上执行后才能确认。本机现场执行仍受当前连接能力限制。
