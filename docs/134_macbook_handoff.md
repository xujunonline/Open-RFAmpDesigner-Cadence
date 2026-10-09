# 134 迁移到 MacBook 继续执行 v2（交接说明与新提示词）

> 2026-10-06。Windows 宿主上 VMware 打开 `IC618_rf.vmx` 一直没有反应，改在新 MacBook 上运行虚拟机和 Claude Code。
> 本文是 docs/130 的补充：docs/130 的阶段、约束、Spectre 账本照常有效，只是执行机器换成 macOS。
> （docs/132 预留给 N65 接入、docs/133 预留给 v2 结果，所以本文编号 134。）

## 1. 交接时的状态（分支 `v2-agentic`，已推送到 GitHub）

| 阶段 | 状态 | 提交 |
|---|---|---|
| 阶段 0 环境与分支 | 完成：88 passed，smoke S2 通过；建 N65 Spectre 账本（0/1500） | `1c8059d` |
| A1 文件名、功率比范围、cadence Spectre 上限 | 完成：99 passed；v1 冻结核对通过 | `02d114a` |
| A2 v2 ReAct 智能体（离线） | 完成：111 passed；scripted S2 通过；docs/131 | `5999a06` |
| A3 真实 LLM 运行 | **未开始，待确认**（建议先 S2 seed 0 冒烟，claude-cli 与 codex-mcp 各一次，约 120–200 次调用） | — |
| N0 虚拟机与登录 | **未完成**：Windows 上虚拟机无法启动，改在 Mac 上做 | — |
| N1–N3、收尾 | 未开始 | — |

LLM 真实调用累计 0 次；N65 Spectre 累计 0/1500。

## 2. 先检查：MacBook 的 CPU 架构（关键）

IC618_rf 是 x86_64 的 CentOS 7 虚拟机。
- **Intel Mac**：VMware Fusion 可以直接运行。
- **Apple 芯片（M1–M4 等，`uname -m` 显示 `arm64`）**：VMware Fusion 只能运行 ARM 客户机，**不能**运行这台 x86 虚拟机；
  UTM/QEMU 软件模拟 x86 理论上能启动，但 Cadence 会慢一个数量级以上，不适合 Spectre 批量运行。
  可选方案：把虚拟机放到一台 x86 的 Linux/Windows 主机（或原 Windows 宿主排障后）上运行，Mac 只运行 Claude Code，通过 SSH 连虚拟机（仓库的远程链路本来就是这样设计的）。

## 3. Mac 上的准备（用户操作）

```bash
git clone -b v2-agentic https://github.com/xujunonline/Open-RFAmpDesigner-Cadence.git
cd Open-RFAmpDesigner-Cadence
python3 -m venv .venv && source .venv/bin/activate      # 让 `python` 指向 3.11+，hook 依赖 `python` 命令
python -m pip install -r config/requirements_repro.txt
```

- 安装并登录 Claude Code（`claude`）与 Codex CLI（`codex`，A3 的 codex-mcp 需要，用 ChatGPT 账号登录）。
- **每次都在激活了 `.venv` 的终端里启动 `claude`**：项目 hook 用 `python "$CLAUDE_PROJECT_DIR/.claude/hooks/…"`，
  若 `python` 命令不存在，守卫 hook 不会运行，远程/Spectre 命令就失去确认保护。
  （2026-10-06 修正：桌面 App 不会激活 `.venv`，实测 hook 因找不到 `python` 失败（exit 127）。现在 hook 命令优先用
  `$CLAUDE_PROJECT_DIR/.venv/bin/python`，不存在时回落 `python`（Windows 不变）。MCP 服务器 `rfamp`/`codex` 仍用 `.mcp.json` 的 `python`，
  未激活 `.venv` 时连不上；`bench` 的 claude-cli / codex-mcp 不依赖它们。）
  （2026-10-07 修复：在 `~/.local/bin/python` 放了一个两行的包装脚本，`exec` 本仓库的 `.venv/bin/python`。
  不能用符号链接：Python 按启动路径寻找 `pyvenv.cfg`，经符号链接启动时找不到，就不会进入 venv。
  `~/.local/bin` 已在桌面 App 的 PATH 里，于是 `.mcp.json` 的 `python` 可用，rfamp 与 codex-bridge 都能正常响应 `initialize`。
  已经打开的会话需要在 `/mcp` 里手动重连这两个服务器；删除该包装脚本即可撤销。）
- 机密文件不在 git 里，需要在 Mac 上重新建：`config/remote_cadence.local.yaml`（按 `config/remote_cadence.example.yaml`，由用户填写）。
  `config/model_paths.local.yaml` 由 N1 盘点后写入。crn40lp 的旧配置、PDK 表、`results/runs/` 留在 Windows，不迁移（v1 结果不改动）。
- 虚拟机：在 VMware Fusion 打开 `IC618_rf.vmx`（从 Windows 的 `F:\IC618_rf\` 整个目录拷过来），网络用 NAT 或仅主机，开机后在虚拟机里 `ip addr` 查 IP。

## 4. 在 Mac 上给 Claude Code 的新提示词

在仓库根目录（已激活 `.venv`）运行 `claude`，粘贴下面整段：

```text
按 docs/130_v2_kickoff.md 继续执行，交接状态见 docs/134_macbook_handoff.md。现在在 macOS 上，分支 v2-agentic。
阶段 0、A1、A2 已在 Windows 上完成（提交 1c8059d、02d114a、5999a06），不要重做。

先做"Mac 环境检查"（无需确认）：
1. git status 干净、当前分支 v2-agentic、HEAD 与 origin/v2-agentic 一致；uname -m；python --version（≥3.11，且来自 .venv）；
   claude --version；codex --version（缺失只记录）。
2. 确认 .claude/settings.json 的两个 hook 在 macOS 上能运行（guard_bash 对 ssh 要求确认、对机密配置文件名拦截；check_python 能编译 .py）。
3. 全量 pytest（预期 111 passed）与 bench smoke，记录耗时；若有平台相关失败，修正后单独提交并说明。
4. 若 uname -m 为 arm64，提醒我 x86 的 IC618_rf 虚拟机不能在 VMware Fusion 上运行（见 docs/134 §2），等我决定虚拟机放在哪里。
汇报后停下。

之后按 docs/130 的顺序推进：
- B 线 N0（Mac 版）：在 Mac 上生成专用密钥 ~/.ssh/ic618_rf（ed25519，无口令；已存在则跳过），然后请我自己运行
  ssh-copy-id -i ~/.ssh/ic618_rf.pub userone@<IP>（我输入 userone 的密码，你不接触密码）；我按 config/remote_cadence.example.yaml
  写好 config/remote_cadence.local.yaml（host、user=userone、identity_file=~/.ssh/ic618_rf）后，你做登录验证
  ssh -i ~/.ssh/ic618_rf userone@<IP> "echo ok; which spectre virtuoso; spectre -W"（需确认；0 次仿真）。
- A3 第 1 步（需确认）：S2 seed 0 冒烟，claude-cli 与 codex-mcp 各一次，ORFADC_LLM_MAX_CALLS=1000，--agent-impl v2。
  开始前报预计调用次数与时长；冒烟后汇报实测调用数与时长，再请我确认 S9s/S10s。
- N1 起：scripts/run_job_queue.cmd 只适用于 Windows，需要后台批量跑时先补一个等价的 scripts/run_job_queue.sh（同一队列格式）并补测试。

docs/130 的约束全部照常：不伪造结果；不读、不打印、不提交 *.local.yaml 与私钥；凭据只由我输入；N65 Spectre 账本上限 1500，
每个用 Spectre 的阶段先报预计次数并等确认，设置 ORFADC_SPECTRE_MAX_PER_DESIGN；结果不确定时不自动重派；
v1 行为冻结；每阶段一个提交，推送和打标签先问我，永不强推。每阶段结束按 docs/130 §6 的格式用中文汇报，在"需确认"处停下。
```

> 2026-10-07 补注：IC618_rf 上没有 `userone` 用户，上面提示词中的 `userone` 实际为 `IC`（docs/132 §2）。

## 4b. codex 命令行：改用固定的正式版（2026-10-08）

**原因**：`~/.local/bin/codex` 原先链接到 ChatGPT.app 自带的 codex。App 用 Sparkle 自动更新，在长时间运行中途把它从
0.159.0-alpha 换成了 0.162.0-alpha.2；新版间歇性报 `workspace routing discovery failed/timed out`，导致 4+2 次 v2 运行作废（docs/133 §6）。

**处理**：
1. 关闭 ChatGPT.app（bundle id `com.openai.codex`）的自动更新：
   `defaults write com.openai.codex SUEnableAutomaticChecks -bool false`，`… SUAutomaticallyUpdate -bool false`（原值都是 1）。
   - 撤销：把两项写回 `true`。
   - App 在下次检查更新时读取这两项；要立即生效需重启 App。
2. 安装官方 GitHub 正式版 `rust-v0.161.0`：
   - 文件 `codex-x86_64-apple-darwin.tar.gz`（106 MB），SHA-256 `cb3d7222…63853`，与发布页一致；签名有效（Team ID 2DC432GLL2）。
   - 装到 `~/.local/bin/codex-stable`；`codex-cli 0.161.0`，沿用 `~/.codex` 中的 ChatGPT 登录。`llm-check`：ok。
3. 切换：后台任务等所有 codex 作业结束（相隔 2 分钟两次检查都空闲）后，把 `~/.local/bin/codex` 改指向 `codex-stable`，旧链接改名为 `codex-app`。
   这样正在跑的运行不会在中途换 codex 版本。撤销：`mv ~/.local/bin/codex-app ~/.local/bin/codex`（覆盖新链接）。
4. 兜底：`llm_cli.with_transient_retries` 仍然保留（只对该错误等 15/30/60 s 重试）；重试次数记在 `llm_usage.transient_retries`。

## 4c. 虚拟机 IP 会被 DHCP 改掉：ssh 每次连接时查当前地址（2026-10-09）

**现象**：IC618_rf 用 VMware NAT 的 DHCP 拿地址，先后变成 .137 → .138 → .139。之前在 `~/.ssh/config` 里把 .137 重定向到写死的 .138；
地址变成 .139 后，所有 ssh/scp 都返回 255，v2 S10 seed 2 因此崩溃（0 次 Spectre，docs/133 §9.1）。

**处理**：`~/.ssh/config` 中 `Host ic618-vm 172.16.218.137` 改成
`ProxyCommand sh -c 'exec nc "$("/Applications/VMware Fusion.app/Contents/Public/vmrun" getGuestIPAddress "/Users/jason/Desktop/IC618_rf/IC618_rf.vmx")" %p'`。
- 每次连接都查虚拟机当前地址（需要客体里的 VMware Tools 在运行）。git 忽略的远程配置里的 `172.16.218.137` 只当作名字使用。
- 其他 Host 条目没有改动；原文件备份为 `~/.ssh/config.bak-20261009`。
- 更彻底的办法：在 VMware 的 `vmnet8/dhcpd.conf` 里为网卡 MAC 固定地址。2026-10-09 已由用户执行 `sudo scripts/pin_vm_ip_mac.sh`：
  MAC `00:0c:29:34:bb:40` 固定为 **172.16.218.100**（在动态范围 .128–.254 之外），原文件备份为 `dhcpd.conf.bak-20261009142044`。
  软重启虚拟机后地址为 .100，ssh 和 Spectre 都正常。上面的动态查地址配置仍保留作兜底。

## 5. 边界

- 本次迁移不改变任何结果；Windows 上的 crn40lp 结果与旧虚拟机保留。
- 平台差异（路径、`python` 命令、`.cmd` 脚本）只做加法式修改，Windows 路径保持可用。
