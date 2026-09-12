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

## 3. 尚未通过项目

OCEAN/SKILL smoke 尚未完成，原因已经定位：

1. 来宾以 VMware `nogui` 模式启动，没有已登录的 GNOME X 会话；
2. 使用旧 OTA 工程的 `DISPLAY=:1` 时，OCEAN 返回 X Window Display 初始化失败；
3. 改用 `-nograph` 后，该来宾环境未稳定完成 OCEAN 启动，随后 SSH 服务出现连接重置；
4. VMware 主机日志显示来宾工具通道长时间无响应，但虚拟机进程仍在运行。

旧 OTA 工程已经记录：该环境的可靠方式是先登录 GNOME，再复用 `DISPLAY=:1` 和对应 Xauthority。因此本地私有配置已恢复为该模式，VMware 控制台也已打开，等待用户手动登录。项目不会保存或自动输入来宾密码。

后续复验时，SSH 仍在密钥交换阶段被来宾主动重置，因此尚未进入第二次 OCEAN 调用。继续实验前需要先在 VMware 控制台确认来宾响应，并恢复 `sshd` 和 GNOME 会话；不能把该状态归因于 Python 调用层或记录为 OCEAN 通过。

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

## 5. 下一次继续前的人工动作

1. 在已打开的 VMware 控制台确认 RedHat 来宾可响应；
2. 如停在登录界面，由用户手动登录 GNOME；
3. 确认桌面会话已经建立；
4. 不需要在来宾中手工启动 Virtuoso；
5. 回到项目重新运行上述环境验证命令。

## 6. 阶段判定

- 阶段 2“SSH、SCP 和结果回收基础能力”：已通过实机验证。
- 阶段 3“Spectre 命令行环境”：已通过实机验证。
- 阶段 3“OCEAN/SKILL 解释器”：待 GNOME 登录后复验。
- PDK/library/cell/view 和 RF analysis：尚未验证。

因此当前不能声称 Cadence RF 仿真闭环已经完成，也不能进入真实 S 参数结果报告。OCEAN smoke 通过后，下一任务才是建立最小 RF S 参数 testbench。
