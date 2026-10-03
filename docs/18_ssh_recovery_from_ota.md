# 从 OTA 项目证据排查 Cadence SSH 无响应

## 来源与对照

`F:\VirtuosoFoldedCascodeProject` 的脱敏聊天记录、`docs/01_environment.md`、`src/python/verify_connection.py` 和 `scripts/verify_remote.ps1` 证明：2026-07-19 起，同一 VMware NAT 来宾、`userone` 专用 SSH 密钥和 22 端口曾完成 SSH、SCP、OCEAN 与 Spectre 验收。私钥保存在 Windows 用户的 NTFS `.ssh`，不应迁回 F 盘。来宾 `.bashrc` 曾在非交互会话打印欢迎图，已经加交互判断；那是登录后的 SCP/结构化输出问题，不会造成 SSH banner 之前超时。

本工程在 2026-09-12 至 09-25 曾复验相同远程链路和被动二端口 Spectre 仿真。已有成功运行的原始结果不因当前故障失效。

## 2026-09-25 当前故障证据

| 层级 | 只读检查 | 结论 |
| --- | --- | --- |
| 配置 | VMX 仍为 NAT、4 vCPU、6 GB、关闭 3D；主机磁盘空间充足 | 没有证据表明项目私有 YAML 或网卡模式发生改变。 |
| 目标身份 | 目标 IP 的 ARP MAC 与当前 VMX 生成的 MAC 一致 | 不是连到 DHCP 重新分配后的另一台设备。 |
| TCP/SSH | 22 端口 TCP 连接成功，但原始 socket 读取 3 秒无 SSH banner；SSH 报 `Connection timed out during banner exchange` | 故障在认证、密钥、`.bashrc`、Cadence 命令之前。 |
| VMware | `vmware-vmx` 进程运行；日志出现 Tools/RPC 心跳超时；提权后的只读 `vmrun getGuestIPAddress -wait` 长时间无返回，已中止查询 | 来宾或 VMware 控制通道失响应；不能据进程存在推断 Linux 正常运行。 |
| 宿主服务 | VMware Authorization、NAT、DHCP 服务均为 Running | 不支持“服务完全停止”的解释。 |

最可能是来宾整体卡顿或系统级资源/磁盘 I/O 停滞，次要可能是来宾 sshd 已接受连接但无法调度。仅凭宿主日志不能最终确认 Linux 内核状态；需要恢复来宾控制台或重启后查看 `journalctl`、内存与磁盘记录。VMware 日志中另有多次启动同一 VMDK 的锁冲突，发生在已有 VM 进程持有磁盘时；**不要删除 `.lck` 文件或同时再启动一份 VM**。

## 恢复顺序与边界

1. 保持当前 VMX/VMDK 和结果原样；不要修改私钥、`authorized_keys`、`.bashrc`、NAT 配置或 Cadence 安装。
2. 如 VMware 控制台仍可操作，优先尝试正常来宾关机/重启；只读 `vmrun` 查询已无响应时，不要无限重复。
3. 只有确认正常关机不可行且用户明确接受未保存来宾数据丢失风险后，才考虑 VMware 硬重置。不得在 `vmware-vmx` 仍运行时手动删除磁盘锁；不要直接以结束进程作为首选方案。
4. 重新启动后先确认 VMware Tools 心跳/来宾 IP，再检查 TCP banner、SSH 密钥登录、SCP，然后依次运行本工程 `verify_remote`、二端口 runner 和 OCEAN smoke；每步保存新 run ID 和原始日志。
5. 若重启后仍失响应，检查来宾上次启动的 `journalctl -b -1`、`dmesg`、内存、磁盘和 sshd 日志，避免反复硬重置。不要将商业 PDK 或私钥内容复制入公开仓库。

## 恢复实施与结果

同日晚些时候，用户明确允许在检查风险后硬重置。目录中仅有一个主 VMDK，没有 `.vmsn`/`.vmss` 快照状态；原 `vmware-vmx` 持有磁盘锁。一次 `vmrun stop ... soft` 在限定等待后无返回，已中止。随后一次 `vmrun reset ... hard` 成功返回，日志记录了虚拟 NVMe 控制器复位和 RHEL 启动。启动初期 SSH 暂时超时；约一分钟后 VMware Tools 返回原 IP，SSH 密钥登录成功。

复验产物：

- 新版二端口：`results/runs/rf_smoke/ideal_twoport/20260925T152506Z_273884f2/`，`status=ok`，47 个频点，Spectre 0 errors/0 warnings/1 notice，`spec_pass=null`；
- OCEAN/Spectre 环境：`results/logs/cadence_environment/20260925_after_vm_reset/`，顶层 `status=ok`、OCEAN `status=ok`、OCEAN 报告 `status=ok`；
- `userone` 会话检查：`sshd` active、来宾可用内存约 4.7 GB。普通用户无权读取前一启动的系统 journal，因此尚不能精确归因于 OOM、I/O 或内核卡死。

## 短时恢复后的复发

上述真实仿真成功数分钟后，稳定性复查再次出现 SSH 连接超时。VMware 日志又记录 toolbox RPC/心跳超时，`vmware-vmx` 工作集约 4.9 GB；提权读取的宿主可用物理内存仅约 600 MB，而来宾配置为 6 GB。宿主内存压力是优先排查的强线索，并非已证明的唯一内核根因。不要在同样资源条件下循环硬重置。

当时状态：SSH/Spectre/OCEAN 曾短时恢复并完成实测，但来宾随后再次失响应。A06 的 runner 功能已真实验证；A09 当时仍受阻。后续需观察连续 SSH/Tools 心跳及低预算 smoke。硬重置不是自动化服务应无条件重复执行的常规步骤。

## 2026-09-26 轻负载复验

开始本轮时 `vmrun list` 显示没有运行中的 VM，宿主可用物理内存约 8.24 GB；VMX 仍为 4 vCPU/6 GB/NAT/关闭 3D，未修改配置或清理锁。以 `nogui` 启动后：

- SSH 密钥探测和 Cadence 命令定位成功，VMware Tools 能返回原来宾 IP；
- 分时多轮 SSH 检查保持 `ok`，`sshd` 为 active；SCP 往返文件 SHA-256 一致；
- 新版二端口 runner 在 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/` 完成 47 点 Spectre 分析，日志 0 errors/0 warnings/1 notice，`spec_pass=null`；
- 宿主可用内存从关机时约 8.24 GB 降到启动后 2.22 GB，之后观测为约 2.07、1.83、1.90、1.68、1.80 GB。未运行 OCEAN 或长期扫描。

这证明当前配置下的轻负载 SSH/SCP/Spectre 在本轮观察窗口内可用；不证明昨晚的失响应根因已消除，也不保证 OCEAN 或长时任务稳定。若重负载前可用内存进一步下降，应先释放宿主资源或经授权调整 VM 内存，而不是重复硬重置。

## 2026-09-26 A09 限定范围稳定性验收

未修改 VMX、未降低 6 GB 来宾内存、未执行重置。在宿主可用内存约 2.6 GB 的条件下，用 `scripts/a09_stability_acceptance.ps1` 按 60 秒间隔进行 15 轮 SSH 与 VMware Tools 检查，首轮、中段第 8 轮、末轮第 15 轮分别执行 OCEAN/SKILL 无图形 smoke 及 Spectre 版本探测。脚本在宿主可用内存低于 1024 MB 或任一探测失败时立即停止，不会自动重启来宾。

- 时间：2026-09-26 00:46:08 至 01:01:45 UTC，约 15 分 36 秒；15/15 轮状态为 `ok`；
- SSH 15/15、VMware Tools 15/15；OCEAN 3/3，三个报告的顶层与脚本 `status` 均为 `ok`；
- 宿主可用内存范围 2660-2778 MB，未触发停止阈值；末次 OCEAN 后又单独复查 SSH、Tools 与内存，分别为 `ok`、成功、2673 MB；
- 原始逐轮记录和三个 OCEAN 日志/报告在 `results/logs/a09_20260926_acceptance/`（本地忽略目录）；此前独立 Spectre 二端口实测仍在 `results/runs/rf_smoke/ideal_twoport/20260926T000100Z_239955d5/`。

结论：A09 的 **当前原配置、当前宿主内存余量、约 16 分钟轻负载运行** 验收通过，可继续低预算的下一阶段实测。它不证明先前故障的根因已查明，也不覆盖多小时扫描、并行 Spectre、真实有源 LNA 或 PDK 高负载任务。执行这些任务前须重新检查内存与 SSH/Tools，必要时降低并发或经授权调整 VM 配置；若故障复发，应重新打开 A09 并保留失败日志。
