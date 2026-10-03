# 4 GiB Cadence VM 资源门禁与单候选复验

2026-09-26，用户启用 Windows 系统管理页面文件并重启后，自动管理为开启，页面文件实际分配约 12 GiB；VM 挂起时宿主物理可用内存约 8.63 GiB。短时恢复原 6 GiB VM 后，两次宿主读数为 2.57/2.54 GiB，均低于本项目有源入口的 2.66 GiB 预检门槛，未运行 Spectre/OCEAN。VMware Tools 提供的正常关机返回成功；`vmrun list` 为 0 台，`vmware-vmx` 进程与保存状态文件均消失，VMX 的 checkpoint 字段为空。

按用户授权，在完整关机后备份 VMX，只把 `memsize` 从 6144 改为 4096 MiB；备份与修改后文件逐字节比对，差异仅为四个数字字节，未改磁盘、网络或许可证。4 GiB VM 冷启动后，SSH 可用；来宾 `free -m` 报总内存约 3622 MiB、可用约 2673 MiB、swap 使用 0。宿主 VMware Tools IP 查询在启动后短时失败，来宾 `vmtoolsd` 实际 active；等待式查询通过后，普通查询也恢复。

有界 A09 轻负载验收在 Git 忽略的 `results/logs/a09_4g_20260926_184426/`：3/3 轮 SSH、Tools 与 OCEAN/Spectre 环境检查均为 ok，轮间 30 秒，最低宿主物理余量 5358 MiB，高于执行时设定的 2724 MiB 门槛。负载后项目 `resource_guard` 读数约 5.29 GiB，随后约 5.12 GiB；来宾约 2716–2735 MiB 可用、swap 使用 0，无遗留 OCEAN/Spectre 进程。**这只证明 4 GiB 配置的短时轻负载门禁和一次小仿真可行，不证明长时、并行、角落或三阶段 LNA 仿真稳定。**

同一配置下，阶段 05 首个 OA RD/VBIAS 候选 `S1_seed0_rd120_vb067_4g/20260926T104913Z_d642fae2` 在 Spectre 读网表时因未上传 OA 伴随的 `ade_e.scs` 报 SFE-868，返回 `spectre_error`；该失败归档保留。修复后只对网表明确引用的固定 `ade_e.scs` 做私有路径校验、归档和上传；缺失/上传失败单元测试通过。新 run `S1_seed0_rd120_vb067_4g_fix1/20260926T105153Z_197025ae` 完成直接 Spectre DC/SP/noise，日志 0 errors、5 条既有 SFE-1131 warnings；47 点原始数据，11 文件哈希清单通过。独立重提取 9 个共有指标最大绝对差为 0。带内最差 S21 约 -1.09 dB、S11 约 -0.003 dB、NF 约 4.41 dB、供电约 2.45 mA；仍为 `active_common_source_smoke`、`not_lna_result=true`、`spec_pass=null`，不是合格 LNA。

下一步保持资源门禁，优先解决授权 PDK 的 CDF/PCell 几何参数传播，再设计可实现且稳定的匹配网络与压缩点/fullchain。运行大预算前仍需更长时间和相应负载级别的内存/SSH/Tools 验收。VM 当前运行；不要因本次通过而并行启动扫参。
