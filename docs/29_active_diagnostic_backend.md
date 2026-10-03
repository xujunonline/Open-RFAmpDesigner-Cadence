# 阶段 05 局部进展：OA 共源级受控诊断候选后端

`src/orfadc/experiments/run_active_diagnostic_candidate.py` 基于**已有授权 OA 生成的私有网表**，只允许修改 `RD` 电阻值（50–1000 Ω）与 `VBIAS`（0.4–0.8 V）。它不修改 MOS 的 W/L、PCell 几何或连接，不解决阶段 03 的 CDF 回调问题，也不生成新的 Virtuoso schematic。网表必须位于 Git 忽略的 `results/runs/` 内，并由调用者提供原文件 SHA-256；哈希变化、目标行不唯一、供电/双 50 Ω 端口/DC/SP-noise testbench 结构不符均在创建候选目录前拒绝。

一次运行独占创建 `results/runs/<spec>/seed<seed>/<candidate>/<run_id>/`，保存候选快照、私有网表副本、Spectre 标准输出/错误与日志、DC/SP/noise 原始 PSFASCII、CSV、指标及 SHA-256 文件清单。指标由本次下载的原始数据经 `extract_active_oa` 重提取；网络/仿真/下载/解析/证据错误单独归类。远端目录含 spec、seed、candidate 与 run_id，避免不同候选共用 run_id 时碰撞。`spec_pass=null`、`not_lna_result=true` 和 `circuit_class=active_common_source_smoke` 固定不变，即使 S21 偶然为正也不能称为合格 LNA。

在创建候选目录前，入口还会读取宿主可用**物理**内存。低于 2.66 GiB、读数无效或试图把阈值设得更低，都直接拒绝运行；不会启动 SSH/Spectre。2.66 GiB 是参照此前 A09 轻负载验收最低余量（记录为 2660 MiB）上取整后的**项目预检值**，并非 VMware/Cadence 官方要求，也不是长时/高负载稳定性的充分保证。VMware Tools、SSH、来宾状态和许可证仍需按阶段提示词独立检查。

2026-09-26 再次只读复核：宿主物理内存约 15.89 GiB、VM 挂起时可用内存两次为 7.00/6.99 GiB，VMX 分配 6144 MiB，且保存状态仍在；前次恢复同一 VM 后宿主余量约 1.27 GiB。按观测，恢复将比 2.66 GiB 门槛低约 1.39 GiB；按分配量做简化预算，恢复前至少要有 8.66 GiB 可用，实际还应留额外余量。当前不启动 VM/仿真。先关闭经用户确认不需要的宿主应用并重新测量；若不能稳定达到约 9 GiB 以上，优先增加宿主物理内存，或在来宾**正常关机**后评估将 VM 降到 4 GiB 并做小负载验收。当前为挂起态，不直接改 VMX、不删除保存状态；增大 Windows 页面文件不等于满足物理内存门禁。

同日进一步只读核查 Windows 页面文件：`Win32_ComputerSystem.AutomaticManagedPagefile=False`，`Win32_PageFileSetting` 与 `Win32_PageFileUsage` 均无条目；系统提交上限约 15.89 GiB，与物理 RAM 相当。C: 可用空间约 37.18 GiB。启用**系统管理**页面文件可扩大提交上限，并可能把不活跃的修改页面换出、释放部分物理 RAM；但不增加物理 RAM，也不能保证 VMware/Cadence 在内存压力下的响应速度。尚未修改系统设置或重启。若用户启用页面文件，重启后仍须记录提交量、可用物理内存和换页/磁盘负载，再决定是否恢复 VM；2.66 GiB 门禁不降低。

在**主机内存、SSH/Tools、许可可用**且实验室授权范围确认后，可在本地 PowerShell 使用以下命令；`<...>` 是本机 Git 忽略目录的路径/哈希，不写入仓库或 LLM 请求。先用 `Get-FileHash -Algorithm SHA256 <私有OA网表>` 得到哈希，再运行单个候选，不批量扫参：

```powershell
$env:PYTHONPATH = 'src'
py -m orfadc.experiments.run_active_diagnostic_candidate `
  --template <私有OA网表> --template-sha256 <64位SHA256> `
  --candidate-id S1_seed0_rd120_vb067 --rd-ohm 120 --vbias-v 0.67
```

2026-09-26 的验收范围只有：10 个新后端 mock/失败单元测试、对已有私有 v2 网表的**只读离线渲染**通过，且源 SHA-256 未变。对旧 v2 直接 Spectre PSFASCII 再作一次只读提取，47 个频点、9 个共有数值指标与旧归档的最大绝对差为 0。新后端没有新的远端 Spectre 实测；当时 Windows 宿主可用物理内存约 2.14 GB，随后复查约 2.07 GB，低于先前轻负载验收余量，因此未启动运行。历史 v1/v2 Cadence 实测仍是独立证据，不能算作这个新后端的成功。新后端能把 Spectre 已完成但解析失败与仿真失败区分，并根据日志单独分类许可等待超时。下一次先做 1 候选/1 seed 的受控实跑，核验日志 0 error、原始数据重提取、网表 RD/VBIAS、证据清单，然后再考虑小范围扫参。压缩点、合格匹配、宽带稳定性和论文 fullchain 仍未实现。

后续状态更新见 `docs/31_vm4g_memory_acceptance.md`：用户启用页面文件后 6 GiB VM 仍低于宿主门禁，正常关机并备份后改为 4 GiB；3 轮轻负载资源/SSH/Tools/OCEAN 验收通过。首次真实后端 run 因遗漏 OA `ade_e.scs` 伴随文件失败，修复上传路径后以新 run_id 完成直接 Spectre DC/SP/noise，哈希清单与独立重提取通过。**以上历史段落描述的是修复前状态，不再是当前阶段 05 的验收结论。**
