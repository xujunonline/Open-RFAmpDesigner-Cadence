# Cadence 远程环境实机验证记录

## 1. 验证范围

本记录对应步进指导书阶段 2 的实机收尾和阶段 3 的环境检查。验证只使用本地私有配置，不访问或复制商业 PDK，不运行 LNA 仿真。

## 2. 已通过项目

2026-09-12 已实机确认：

- VMware 中的 RedHat Cadence 来宾能够启动；
- 本机 SSH 私钥存在，项目盘不保存私钥；
- SSH 无密码连接成功；
- 远端用户、主机和工作目录可以通过结构化探针读取；
- `ocean`、`spectre`、`virtuoso` 命令均可被远程 shell 找到；
- SCP 上传和下载成功；
- 往返文件 SHA-256 完全一致；
- Spectre 可真实启动并返回版本 `25.1.0.054`；
- 本地配置、探测输出、传输文件和运行日志均被 Git 忽略。

以上结果证明 Windows 到 Linux 的 SSH/SCP/Spectre 基础链路已经接通。

## 3. OCEAN 阻塞及解决方案

2026-09-24 已完成 OCEAN/SKILL smoke。排障结论如下：

1. 旧 OTA 工程依赖已登录 GNOME 的 `DISPLAY=:1`，但无人值守启动后只有 GDM 的 `DISPLAY=:0`；
2. IC25.1 的 `ocean -nograph` 会调用 Cadence 自带的 `cdsXvfb-run`，来宾原先缺少 `/usr/bin/Xvfb`；
3. `userone` 不在 sudoers，无法安装系统 RPM；RHEL AppStream 元数据可读取，但软件包下载端持续超时；
4. 最终从 Rocky Linux 9 官方 AppStream 获取与 RHEL 9 二进制兼容的 Xvfb 和 server-common RPM，仅解包到来宾用户私有目录 `~/.local/xvfb-root`；
5. runner 新增 `cadence.xvfb_path`，在无图形运行时注入 `CDS_XVFB_PATH`，不修改系统目录，也不依赖 GNOME 登录；
6. 主机内存压力会导致来宾、VMware Tools 和 SSH 同时失去响应。虚拟机已从 8 vCPU/8 GB/3D 调整为 4 vCPU/6 GB/无 3D，原 VMX 配置已在虚拟机目录中备份。

真实验收中，OCEAN 返回码为 0，Virtuoso Framework License (111) 成功签出，下载的报告包含：

```text
status=ok
engine=ocean_skill
```

私有配置、SSH 密钥、RPM 和远端用户目录均不进入公开仓库。

## 4. 已实现的验证命令

代码入口：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m orfadc.cadence.verify_cadence_environment `
  --config config\remote_cadence.local.yaml `
  --ocean-script circuit\ocean\verify_design.ocn `
  --output-dir results\logs\cadence_environment
```

命令按顺序执行：

1. SSH 和 Cadence 工具探测；
2. `spectre -W` 版本验证；
3. 上传最小 `verify_design.ocn`；
4. 启动 OCEAN/SKILL；
5. 下载 OCEAN 日志和 `verify_design_report.txt`；
6. 生成 `cadence_environment_report.json`。

只有所有步骤均成功，顶层 `status` 才会是 `ok`。

## 5. 后续运行要求

1. 虚拟机可使用 `nogui` 模式启动，不需要登录 GNOME；
2. 本地私有配置保持 `ocean_nograph: true`；
3. `cadence.xvfb_path` 指向用户级 Xvfb 的 `usr/bin` 目录；
4. 不要把密码、私钥、RPM 或商业 PDK 文件提交到仓库；
5. 若来宾再次整体失去响应，先检查主机可用内存和 VM 资源，不要把问题误判为 OCEAN 脚本错误。
6. 对本机仅需经典 Spectre 许可的 OCEAN 仿真，在脚本的 `simulator('spectre)` 之前设置 `envSetVal("spectre.turboOpts" "uniMode" 'string "Spectre")`，并检查实际 Spectre 命令不带 `+preset=mx +mt`。这项设置针对本机 2026-09-26 的实测许可差异；换机器后须重新核验，不能据此判断或修改许可文件。证据和后处理注意事项见 `docs/20_stage03_active_smoke.md`。
7. 本机 OA testbench 的干净批处理还要求在 `simulator` 前设置 `envSetVal("spectre.envOpts" "controlMode" 'string "batch")`，且 `resultsDir` 指向运行根目录，由 Cadence 在其中创建 `psf/`；不能把 `resultsDir` 再指向该 `psf/`。2026-09-26 的独立 v5 运行取得 OCEAN 返回码 0、Spectre 0 errors 和非空 DC/SP-noise 文件。ADE 的 `saveOption(?simOutputFormat "psfascii")` 在本机被 `ADE-5012` 拒绝；不要把失败的 v6 当成可用导出方案。

## 6. 阶段判定

- 阶段 2“SSH、SCP 和结果回收基础能力”：已通过实机验证。
- 阶段 3“Spectre 命令行环境”：已通过实机验证。
- 阶段 3“OCEAN/SKILL 解释器”：已通过真实无图形验证。
- PDK/library/cell/view：尚未在本工程 LNA 中验证。
- RF `sp` analysis：2026-09-25 已在 PDK 无关被动二端口上实机通过，证据见 `docs/14_ideal_twoport_rf_smoke.md`。

因此 Cadence 基础执行链和被动二端口 S 参数数据链已经打通；有源 LNA、noise 与压缩点仍未验证。2026-09-25 的审查期间，来宾进程虽在运行，但 SSH 在 banner exchange 超时，新的 Spectre 复验未进入仿真；这不改变此前成功记录，但新增实验须待连接恢复后重新验收。

同日依据原 OTA 工程聊天和当前宿主诊断进一步确认：目标 IP 对应当前 VMX 的网卡，TCP 22 已连接但没有服务端 banner，VMware Tools 心跳及只读 `vmrun` 查询也无响应。问题不在 SSH 私钥或 `.bashrc`；恢复顺序与风险见 `docs/18_ssh_recovery_from_ota.md`。

同日晚些时候，经用户明确同意，在正常关机超时后执行一次 VMware 硬重置。来宾启动后 SSH 密钥探测成功；新版 `run_ideal_twoport` 的独立运行目录 `results/runs/rf_smoke/ideal_twoport/20260925T152506Z_273884f2/` 返回 `status=ok`、47 频点，Spectre 日志为 0 errors/0 warnings/1 notice。OCEAN 环境复验位于 `results/logs/cadence_environment/20260925_after_vm_reset/`，顶层和 OCEAN 报告均为 `ok`。两处结果均被 Git 忽略。当前链路已恢复；先前失响应的精确来宾内核原因尚未证实。

稳定性复查时，SSH 又连接超时，VMware Tools 心跳再次消失。宿主机可用物理内存仅约 600 MB，6 GB 来宾的 `vmware-vmx` 工作集约 4.9 GB；主机内存压力是强线索，但 Linux 上一启动的系统 journal 对普通用户不可读，不能把它写成已证实的唯一根因。现阶段链路为“短时复验成功、持续运行不稳定”。

2026-09-26 复验：VM 已关机，保持原 6 GB 配置无界面启动；SSH/Tools 多轮正常，SCP 往返 SHA-256 一致，独立二端口 Spectre 47 点成功。宿主运行时可用内存最低约 1.68 GB；未再次运行 OCEAN 或长时扫描。因此当前是“轻负载已复验、重负载稳定性待证”，而不是全面恢复保证。详情见 `docs/18_ssh_recovery_from_ota.md`。
