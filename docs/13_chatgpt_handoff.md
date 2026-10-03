# Open-RFAmpDesigner-Cadence 网页版 ChatGPT 续接说明

> 用途：将本文件上传到网页版 ChatGPT 的新会话，作为项目背景与当前状态。本文不包含密码、SSH 私钥正文、商业 PDK 文件或受限模型数据。

## 1. 项目目标

本项目在 Cadence Virtuoso、Spectre 和 OCEAN 环境中方法级复现论文《RFAmpDesigner: A Self-Evolving Multi-Agent LLM Framework for Automated Radio Frequency Amplifier Design》。目标包括 Cadence 自动仿真闭环、RF 指标提取、四类工具中间件、Manager/Searcher/Refiner 多智能体框架，以及论文表格和曲线的趋势级复现。

项目不声称严格复现作者的 TSMC N65 数值、作者脚本、lookup table、KB/EB、prompt 或最终候选参数。

## 2. 已有基础

前置项目 `VirtuosoFoldedCascodeProject` 已在 TSMC 40 nm CRN40LP 环境中完成折叠共源共栅全差分 OTA 的 Spectre 仿真、OCEAN/SKILL 原理图生成、Python SSH 自动扫描和 PSFASCII 解析。已验证结果包括约 36.93 dB 增益、25.47 MHz 的首个下降沿 0 dB 频率、89.35 度相位裕度、0.554 V 输出共模和 66 uA 电源电流。

这些能力已迁移为本项目的通用 Cadence runner、远程传输和结果解析基础。

## 3. 当前代码状态

- 仓库根目录：`F:\Open-RFAmpDesigner-Cadence`
- 主分支：`main`
- Python 单元测试：48 项通过（2026-09-26 审查收尾后）
- SSH/SCP：真实环境通过，上传下载 SHA-256 一致
- Spectre：真实启动通过，版本 `25.1.0.054`
- OCEAN/SKILL：真实无图形 smoke 通过
- OCEAN 报告：`status=ok`、`engine=ocean_skill`
- Virtuoso Framework License (111)：真实签出成功
- PDK、library、cell、view：尚未在本项目 RF 电路中验证
- S 参数：PDK 无关理想二端口真实 `sp` 仿真已通过
- noise、compression：尚未运行真实 RF testbench；noise/NF 本地解析与频率对齐已有人工数据测试

理想二端口已生成 47 个频点的 Touchstone、PSFASCII 和标准化 CSV。Spectre 日志为 0 errors、0 warnings、1 notice。该电路是被动 RLC 工具链测试，不是 LNA，也不用于和论文指标作数值比较。

2026-09-25 审查时的新一轮远程复验因 SSH banner exchange 超时而未进入 Spectre；原有成功数据已用 PSFASCII 与 Touchstone 交叉核对。最新审查与修复状态以 `docs/audits/` 和 `docs/16_implementation_status.md` 为准。

同日再次探测仍在 SSH banner exchange 阶段超时。`docs/17_noise_data_pipeline.md` 记录了已完成的本地 NF 数据管线和未完成的真实 Spectre 验收。

随后按用户授权对失响应虚拟机硬重置，SSH、新版二端口 Spectre 和 OCEAN smoke 均恢复且有独立运行记录。最新状态见 `docs/18_ssh_recovery_from_ota.md`；真实 noise/NF 仍未验证。

但数分钟后的稳定性探测再次失败，并出现 VMware Tools 心跳超时；主机可用物理内存约 600 MB。短时实测结果有效，当前远端环境仍不稳定，必须先完成资源排障。

2026-09-26 原 6 GB VM 关机后重新启动，轻负载 SSH/Tools 连续探测、SCP 哈希及新一次二端口 Spectre 均成功；宿主最低约 1.68 GB 可用内存。OCEAN/长时负载的稳定性仍未验收，不能删去前次复发记录。

## 4. OCEAN 无图形方案

来宾没有系统级 Xvfb，普通用户也没有 sudo 权限。项目采用用户级方案：从 Rocky Linux 9 官方 AppStream 获取与 RHEL 9 二进制兼容的 Xvfb 和 server-common RPM，只解包到来宾用户私有目录。

`src/orfadc/cadence/remote_runner.py` 支持配置 `cadence.xvfb_path`。运行 `ocean -nograph` 时，runner 设置 `CDS_XVFB_PATH`，因此不需要登录 GNOME，也不需要写系统目录。

真实路径仅存在于被 Git 忽略的 `config/remote_cadence.local.yaml`。公开示例只保留空占位符。

## 5. 虚拟机稳定性处理

主机总内存约 16 GB，原虚拟机配置为 8 vCPU、8 GB、启用 3D，曾出现 VMware Tools、SSH 和来宾同时失去响应。已备份原 VMX 配置，并调整为 4 vCPU、6 GB、关闭 3D。调整后启动时来宾可用内存约 4.8 GB，SSH 和 OCEAN 验收均完成。

## 6. 多智能体设计状态

论文中的三个智能体是 Python 编排的 LLM agent，而不是三个独立训练模型：

- Manager：维护候选队列，决定搜索、细化、终止和结果汇总；
- Searcher：提出资源分配与新候选，调用 active sizing、matching 和 band planning；
- Refiner：读取违规指标，针对 NF、S11、gain、ripple、linearity 和 power 定向修正。

本项目目前已有确定性 Python 骨架、prompt 文件和 memory 接口，但尚未接入真实 LLM 后端，也尚未完成论文级 search/refine 闭环实验。

## 7. 下一任务

按以下顺序继续：

1. 处理宿主内存压力和 VM 再次失响应，进行持续 SSH/Tools 稳定性检查；
2. 验证最小 RF noise testbench 的 Spectre 语法、真实输出字段和 Python 解析；
3. 接入授权 PDK 的简化单级 LNA，验证偏置、S 参数、gain、NF 和 power；
4. 增加大信号 compression 仿真；
5. 完成 `active_sizing`、`impedance_matching`、`band_planning`、`fullchain_eval` 的真实 Cadence 后端；
6. 再接入 Manager/Searcher/Refiner 的 LLM 后端和 KB/EB。

## 8. 继续任务提示词

请先读取仓库中的 `README.md`、`docs/00_index.md`、`docs/12_cadence_environment_validation.md`、`docs/agent_system/`、`src/orfadc/cadence/remote_runner.py` 和测试。不要重复已经完成的 SSH/SCP/Spectre/OCEAN 环境排障。

下一步请设计并实现“最小 RF noise/NF testbench”，要求：

- 先明确理想被动二端口只能验证 noise 数据管线，不能代表有源 LNA 的 NF；
- 调研并验证 Spectre `noise` 或带 noise 输出的 `sp` 设置；
- 扫描频率并输出可由 Python 解析的 noise factor/noise figure；
- 每次运行保存 netlist、Spectre 日志、原始结果、CSV 和 metrics.json；
- 增加单元测试和真实环境验收；
- 不虚构 NFmin，不把理想或被动电路结果称为 PDK LNA 结果；
- 完成后更新文档并明确下一阶段。

网页版 ChatGPT 只能规划、审阅和生成文本，不能直接访问本地 F 盘、VMware 或 Cadence。实际文件修改和仿真仍应在 Codex 桌面任务中完成。
