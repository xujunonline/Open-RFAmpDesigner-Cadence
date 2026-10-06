# 132 N65（IC618_rf）接入记录

> docs/130 B 线（N0–N3）的执行记录。执行机器：Intel MacBook（x86_64，macOS 26.5），虚拟机 IC618_rf 在本机 VMware Fusion 上运行（docs/134）。
> 本文只写结论与指标，**不写 PDK 器件参数、PDK 路径细节、密码或私钥**。N65 Spectre 账本：`results/repro/n65/spectre_ledger.csv`。

## 1. 离线准备（0 次 Spectre）

| 项 | 内容 | 测试 |
|---|---|---|
| `scripts/run_job_queue.sh` | `run_job_queue.ps1` 的 bash 版本，队列格式相同（`#` 注释、`set ORFADC_*=值`、每行一个 bench 子命令），日志同样写到 `results/windows_checks/<ts>_job/`（`progress.txt`、`NN_<cmd>.log`、`DONE.txt`）；兼容 CRLF；参数不做通配展开；失败只记录、不重派 | `tests/test_n65_tooling.py` |
| `pdk_inventory.sh` 可配置 | `ORFADC_PDK_ROOTS`（替换默认搜索根）、`PDK_EXTRA_ROOTS`（追加）、`ORFADC_CDSLIB_FILES`（额外 cds.lib）、`ORFADC_CDS_PREFIXES`（Cadence 安装前缀，其库不算 PDK；默认 `/opt/eda/cadence`）、`ORFADC_INV_SKIP_HOME`（默认 1）；输出新增 `##ROOTS`、`##CDS_PREFIXES` 两行 | 同上（用伪造的 CentOS 目录树在本机实跑脚本） |
| `bench pdk-inventory` 读配置 | 从 `config/remote_cadence.local.yaml` 可选的 `inventory:` 块（见 `config/remote_cadence.example.yaml`）生成上述环境变量，路径须为绝对路径、不含空格与 `..` | 同上 |

- 未设置这些变量时，搜索根与跳过规则同原脚本（crn40lp 行为不变）。唯一的变化是：LIBDIR 段现在也读取 `$HOME/*/*/cds.lib` 和额外配置的 cds.lib（原来只读前两层）。这只多列出库目录，不改动任何文件。
- 后台批量运行示例：`nohup scripts/run_job_queue.sh jobs/<队列>.txt >/dev/null 2>&1 &`，然后看 `progress.txt`。

## 2. N0 虚拟机与登录（进行中）

- 虚拟机 IC618_rf 已在 VMware Fusion 运行。网络为 NAT（vmnet8，172.16.218.0/24），客体 IP 由 VMware Tools 报告，DHCP 租约与网卡 MAC 一致。
- 专用密钥 `~/.ssh/ic618_rf`（ed25519，无口令）已在 Mac 上生成。
- **阻塞**：从 Claude Code 发起的连接无法到达客体（`No route to host`，ARP 不完整；连 NAT 网关 .2 也不通，只有本机接口 .1 通）。
  初步判断是 macOS「本地网络」隐私权限没有授予 Claude 应用，待用户在 Terminal.app 中对照验证。
- 待用户：`ssh-copy-id`（由用户输入密码）、写 `config/remote_cadence.local.yaml`；之后执行者做登录验证（0 次仿真）。

## 3. N1–N3

未开始。
