# 阶段 05：被动诊断候选入口

2026-09-26 新增 `src/orfadc/experiments/run_passive_candidate.py`，将已有被动二端口 Spectre S 参数/noise runner 接到独占候选目录。它是 **PDK-independent passive diagnostic**，没有 MOS、DC 偏置或压缩点，`circuit_class=passive_twoport`、`not_lna_result=true`、`spec_pass=null`。Table III 的 spec 只作候选来源上下文，**不参与此入口的 LNA 评分**。

## 运行步骤

1. 确认授权 VM 的 SSH 和 Spectre 可用、宿主/来宾内存充足；勿在连接或资源门禁失败时启动扫参。
2. 在仓库根目录执行一个候选（参数示例仅用于被动数据链路）：

   ```powershell
   $env:PYTHONPATH='src'
   python -m orfadc.experiments.run_passive_candidate --spec S1 --seed 0 --rloss-ohm 5 --lpath-nh 1 --cshunt-pf 0.5
   ```

3. 读取打印的 `run_dir`，检查 `candidate.json`、`netlist.scs`、`metrics.json`、`evidence_manifest.json` 以及仿真日志/原始数据。重新运行会产生另一独立 `run_id` 目录，不覆盖旧候选。`read_evidenced_metrics(run_dir)` 可校验清单哈希和指标 envelope；它**不能**独立证明指标源于真实 Spectre。

默认使用本地私有 `config/remote_cadence.local.yaml` 与仓库内固定被动模板。CLI 只允许三个数值：`rloss_ohm` 在 0.1-100、`lpath_nh` 在 0.1-20、`cshunt_pf` 在 0.01-10；非有限值、字符串注入、额外参数和带有有源参数的候选在仿真前拒绝。输入网表只替换固定 `parameters` 行，其余语句来自仓库模板。没有可配置的任意 shell 或 PDK include 字符串。

## 证据和失败边界

`run_passive_noise` 现在可接收上层预留的 `run_id`，与本地目录和远端被动任务对应。候选封装层在结果中加入 spec、candidate、seed、timeout，并归档参数快照；成功时复用原有 S2P、PSFASCII noise/F/NF 交叉校验。远端建目录、上传、Spectre 超时/错误、下载和解析失败保留独立状态及简短 `failure_code`。日志出现许可证等待字样且超时时只记 `license_related_timeout`，这是诊断分类，不是授权权益判定。没有干净 Spectre 完成日志的“成功”结果降级为 `evidence_failed` 或 `incomplete_evidence`，绝不形成 LNA pass。

离线 fake-remote 单元测试覆盖一次成功归档、一次故意建目录失败、许可证相关超时、非干净日志降级、输入白名单和浮点往返；测试中的 `cadence_spectre` 返回是 mock，不是新的实机证据。此前独立被动 Spectre 实测证据仍见 `docs/17_noise_data_pipeline.md`。

首次测试时宿主可用内存约 7.28 GB，但三次只读 SSH 探测在密钥交换阶段被连接重置（返回码 255），当时**未实跑本候选入口**。

## 同日挂起 VM 恢复后的实机复验

后续检查发现 `vmware-vmx` 未运行，但原 VM 存在 `.vmss` 保存状态；没有删除 `.lck`、修改 VMX/VMDK 或执行硬重置。宿主可用内存升至约 8.96 GB 后，以 `nogui` 恢复原 VM，启动后仍约 3.15 GB。SSH 密钥登录、Spectre 命令定位成功；来宾可用内存约 4.2 GB，`vmtoolsd` 进程存在。宿主侧 `vmrun getGuestIPAddress` 仍返回 -1，故**不把 VMware Tools 控制接口记作通过**。

仅运行一个被动诊断候选，原始目录为 `results/runs/S1/seed0/S1_seed0_passive_smoke/20260926T073333Z_a9c38687/`（Git 忽略）。结果：`status=ok`、`simulation_status=ok`、`source=cadence_spectre`、`circuit_class=passive_twoport`、`not_lna_result=true`、`spec_pass=null`；Spectre 日志为 0 errors、0 warnings、1 notice。`candidate.json` 的 5 ohm、1 nH、0.5 pF 与生成网表的参数行一致。11 个文件由 `read_evidenced_metrics` 重新哈希校验，`run_id` 与目录名一致；原始 S2P/PSFASCII noise 独立重提取均为 47 点，NF/NFmin 汇总与 `metrics.json` 一致（此被动网络的 NF 约 8.415 dB，不是 LNA 性能）。结束后远端无遗留 `spectre`/`ocean` 进程，宿主可用内存约 3.14 GB。

随后同一授权 VM 上又做了一次**受控远端权限负例**：保持原 SSH 身份，只将这次调用的运行根改为普通用户不可写的 `/root/orfadc_fail_probe`，超时限为 30 秒；没有修改私有 YAML、VM 配置或许可证。`results/runs/S1/seed0/S1_seed0_passive_deny_root/20260926T074631Z_2f0be63e/` 返回 `mkdir_failed`、`failure_code=remote_directory_failed`、`simulation_status=unknown`、`spec_pass=null`。真实 SSH 命令返回码为 1，执行在上传与 Spectre 之前停止。清单仅含 `candidate`、`metrics`、`netlist` 三项，哈希和 run_id 复核通过；没有伪造 `spectre.log`。这验证的是**真实传输/权限失败归档**，不是 Spectre 算法或电路仿真失败。

宿主侧 `vmrun list` 能看到 1 台运行 VM，`checkToolsState` 返回 `installed`；VMware 日志有来宾 Tools 心跳，来宾 `vmtoolsd` 进程存在，但重复的 `getGuestIPAddress` 仍返回 -1。可通过 SSH 的事实不等于该宿主控制 API 已恢复；当前没有进一步重启 Tools、硬重置或修改 VM 配置。

继续只读排查后，以 20 秒进程上限执行 `vmrun getGuestIPAddress <vmx> -wait`，这一次返回码 0、输出为合法 IPv4 格式（不记录真实 IP）。因此 Tools 的**等待式 IP 查询**已通过；先前不带 `-wait` 的 -1 记录保留。没有重启来宾服务，也未进行长时 Tools 稳定性复验。

至此被动候选入口有一次真实成功和一次受控远端失败记录，但未覆盖 MOS/DC、压缩点、受控有源 fullchain、Spectre 内部失败或 LNA 规格评分；阶段 05 仍为 partial。下一步补有源 backend 的白名单参数传播和 DC/SP/noise/compression 原始重提取，CDF/PCell 仍须在授权交互式环境核验。不能直接把此被动链路升级为论文 LNA 复现。

后续代码将已解析的 S2P 同时汇总为 `s11_db`、`s21_db`、`s22_db`、`ripple_db` 并写入**新运行**的 `metrics.json`，仍保持 `spec_pass=null`。旧实测目录及其清单不回写；对旧 S2P 的只读独立计算得到 0.1-20 GHz 最差 S21 约 -12.96 dB、ripple 约 12.53 dB，仅用于检验摘要算法，不能冒充旧运行曾保存这些字段。
