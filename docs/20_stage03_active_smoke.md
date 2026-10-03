# 阶段 03：有源器件链路的限定范围实测

2026-09-26 在 A09 已验证的轻负载条件下，只读核查旧 OTA 工程已用的本地工艺模型入口、工程库和 `cds.lib` 均可读取。未复制 PDK/PCell/模型文件，未将私有目录、器件模型名或受限网表纳入仓库。文件可访问不等于再分发许可；本项目只保留本地授权环境中的原始产物。

随后在 Git 忽略的 `results/runs/lna_stage03/private_active_smoke/` 使用**单候选、直接 Spectre 网表**测试共源有源器件、偏置电源、50 Ω 端口、DC、`sp` 与 noise。实测有 47 个 0.1-20 GHz 频点；`spectre.log` 为 0 errors、5 warnings、2 notices。5 条 warning 是模型加载时的重复作用域设置，尚未做 foundry/安装级排查，不能忽略或擅自消除。原始目录包含受限网表、日志、PSFASCII、S2P、CSV 和 `metrics.json`，不进入 Git。

本次诊断值：栅极约 0.650 V、漏极约 0.804 V、供电电流约 0.591 mA；带内最差 `S21` 约 -7.54 dB、NF 约 8.62 dB。它证明有源模型能够被 Spectre 调用且 DC/SP/noise 数据可回收，**不证明这是合格 LNA**。该直接网表 smoke 不是 Virtuoso schematic，也没有输入匹配、稳定性、大信号压缩点或候选优化；`circuit_class=active_common_source_smoke`、`not_lna_result=true`、`spec_pass=null` 保持不变。既有 `fullchain_violations` 不会把它当 `active_lna` 通过。

## 后续 OA 原理图进展

同日在本地授权环境中用 Virtuoso/SKILL 建立新的单管共源核心，并使用真实 pin 与 wire 连接；`schCheck` 返回 `(0 0)`、`dbSave=t`，4 个端口、4 个网络均存在。先前只创建 db 端口的 v1 核心检查失败，错误和结果保留，不复用。另建**平面**测试平台，包含 1 个 MOS、2 个 50 Ω port、2 个 DC 电源、2 个电阻、2 个耦合电容和接地符号；`schCheck=(0 0)`、`dbSave=t`，14 个实例、7 个网络。逐网检查确认栅偏、漏负载、两端口与公共地连接正确。平面 testbench 暂未实例化上述核心 cell，二者是不同的验证产物。

OCEAN `design` + `createNetlist` 已从测试平台 schematic 生成 Spectre 输入网表，实例、电源/端口参数和模型引用可在被 Git 忽略的原始网表中核对。首次 OCEAN DC + `sp`/noise 运行中，ADE 启动的 Spectre 在许可证等待阶段达到 300 秒超时，未产生有效仿真指标；该次运行不能算 OA 仿真通过。

## Spectre 许可证排障与复测（2026-09-26）

- 同一份 OA testbench 生成的输入网表，经**直接 Spectre** 运行完成 DC 和带噪声的 SP 分析；`spectre.log` 记录 `Virtuoso_Spectre` 签出、0 errors、5 条 PDK `scalefactor` 警告。基础 Spectre 许可当前可用，原始证据在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/direct_oa_probe_20260926_01/`。
- 默认 OCEAN/ADE 再试仍等待许可证；其子进程命令带 `+preset=mx +mt`。该次限时运行还出现 Xvfb 显示连接中断，不能仅凭其退出码判定许可证服务故障。
- 新建独立 OCEAN 脚本，在 `simulator('spectre)` 之前设置 `envSetVal("spectre.turboOpts" "uniMode" 'string "Spectre")`。此后生成的子进程命令不再带 `+preset=mx +mt`，`Virtuoso_Spectre` 约 0.9 秒签出，ADE 报 `Simulation completed successfully`，`run()` 返回结果目录；`dcOp.dc`、`sp.sp`、`sp.noise.sp` 均非空。OCEAN 退出码为 0。原始脚本、OCEAN/Spectre 日志在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/`，不进入仓库。
- 这组 A/B 证据强烈指向默认 ADE 高性能模式与当前许可权益不匹配，但未从许可服务器得到席位/feature 的权威清单，不能断言具体缺失的授权项。经典模式成功是本环境的可用解决办法，不应无条件套用于其他实验室。Cadence 对 `+preset` 的说明见 [Spectre X 设置](https://community.cadence.com/cadence_blogs_8/b/cic/posts/dynamically-changing-spectre-x-solver-settings)，经典模式的 `uniMode` 设置见 [Cadence 论坛答复](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/56722/is-it-required-a-particular-license-to-plot-internal-veriloga-parameters/1388371)。
- 经典模式运行在分析完成后的 OCEAN 数据目录读取阶段仍有一条 `Could not determine the simulator from data dir`，交互式 Spectre 收尾日志还有 `SPECTRE-25`。它们不能冒充 0-error 全链验收；也不推翻非空结果文件和 ADE 完成记录。后续需核对结果目录和完整指标，再做工程级通过判定。5 条 PDK 模型警告同样保留，未经授权不改模型。

用户提供的 `read_me_licence.txt` 只读核查显示：它含 6 条 Spectre X 相关 feature 记录及“追加到许可证文件”的文字指令。当前激活的许可证文件可读到经典 `Virtuoso_Spectre` feature，未找到上述 6 个同名 feature。这与 A/B 运行相符，但不能验证附带记录的合法授权、签名、主机绑定或是否适用于当前 25.1 安装。**没有执行文件中的追加指令，也没有修改许可证、虚拟机配置或 PDK。**如确需 Spectre X，须由实验室授权管理员向 Cadence 核对权益和正式安装方式；Cadence 对 Spectre X 的 `+preset` 与许可区别见 [Spectre X 模式说明](https://community.cadence.com/cadence_blogs_8/b/cic/posts/spectre-tech-tips-how-to-migrate-to-spectre-x)及[Cadence 许可答复](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/51486/what-the-license-is-required-in-spectre-simulation/1382867)。

## 已有 OA 网表结果的离线指标提取

新增 `src/orfadc/experiments/extract_active_oa.py`，仅对**直接 Spectre 运行 OA 生成网表**所得的 PSFASCII 做离线提取，不将结果冒称 OCEAN 原生导出。输入的 `dcOp.dc`、`dcOpInfo.info`、`sp.sp`、`sp.noise.sp` 均来自上述 0-error 直接运行；最新输出 `waveforms.csv` 和 `metrics.json` 留在 Git 忽略的 `direct_oa_probe_20260926_01/extracted_v2/`，v1 原始提取结果保留不覆盖。全带 0.1-20 GHz 共 47 点，50 Ω 两端口及 1.1 V 电源已在私有 OA 网表中只读核对。

| 指标 | 实测/计算值 | 解释 |
| --- | ---: | --- |
| 最差 S11 | -0.0012 dB | 近乎全反射，未匹配 |
| 最差 S21 | -7.79 dB | 无正增益，非合格 LNA |
| 最差 S22 | -1.72 dB | 输出匹配差 |
| S21 ripple | 0.417 dB | 仅是当前负增益迹线的起伏 |
| 最差 NF / NFmin | 8.75 / 0.213 dB | 原始 NF 与 F 已逐点交叉核验；NFmin 不等于实际 NF |
| 供电电流 / 功耗 | 0.581 mA / 0.639 mW | 由 DC 电源电流及 1.1 V 计算 |

结果 `status=ok_with_warnings`、`circuit_class=active_common_source_smoke`、`not_lna_result=true`、`spec_pass=null`。5 条模型警告保留，不做工艺模型改动。离线提取及相邻解析/契约测试已通过；完整测试套件 76 passed。运行入口：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.extract_active_oa --psf-dir <private-psfascii-dir> --op-info-path <private-psfascii-dir>/dcOpInfo.info --device-instance M1 --device-type bsim4 --output-dir <new-ignored-dir> --run-id <run-id> --supply-voltage-v 1.1
```

`dcOpInfo.info` 的结构体字段由新增解析器按类型声明顺序与数值配对，字段数不一致时拒绝结果。M1 的 Id 约 0.580 mA、VGS 0.650 V、VDS 0.810 V、Vth 0.523 V、VDSAT 0.166 V、gm 4.85 mS、gds 0.222 mS；导出 `VDS-VDSAT≈0.644 V`、`gm/Id≈8.36 V^-1`、`1/gds≈4.51 kΩ`。这支持“有源器件已偏置且未明显缺少 VDS 裕量”的判断，不等于跨工艺条件下的饱和保证，也不证明 RF 规格通过。下一轮应先分析输入匹配和 50 Ω 输出端口对漏端有效负载的影响，再改偏置或器件尺寸；不能仅凭较低的 NFmin 宣称实际 NF 已优化。

以 10 GHz 这个已有采样点为例，由 `Z=50(1+Sii)/(1-Sii)` 换算，在另一端口以 50 Ω 终接的 S 参数条件下，`Zin≈10.6-j2125 Ω`、`Zout≈448-j38 Ω`。对比 1/20 GHz，输入虚部约为 -21.2 kΩ / -1.06 kΩ，说明当前宽带输入阻抗远离 50 Ω。10 GHz 的虚部可粗略等效为约 7.5 fF；若只用串联电感抵消，需要约 33.8 nH，作为本频段的第一版片上网络不合适。**下一候选的设计假设**：先扫描 M1 的 W/偏置以增加有效输入电容和 gm，再评估源退化电感引入实部、栅极/级间网络抵消虚部，并对输出约 448 Ω 到 50 Ω 的阻抗变换单独设计。按过度简化的 `Re(Zin)≈gm*Ls/Cgs`，当前数据估计增加约 39 Ω 实部对应 `Ls` 数十 pH；10 倍有效电容时栅极抵消电感才降到数 nH。以上都只是起始量级，器件寄生、噪声匹配、稳定性和功耗会改变结果，必须用新候选的 DC/SP/noise 重新验证，不得将估算值当成已实现的匹配网络。

前一轮宿主可用内存约 1.36 GB 时未启动 OCEAN；待本轮门禁通过后才验证 batch 模式。设置来源参见 [Cadence OCEAN batch 讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/42502/ocean-script-nested-parametric-analysis-problem)。

## OCEAN 后处理修复复测

2026-09-26 后续在 SSH、VMware Tools、宿主和来宾内存门禁通过时，使用三个独立、Git 忽略的私有目录验证：

1. v4 仅将 `resultsDir` 改成运行**根目录**，PSF 落在其下 `psf/`。ADE 报仿真完成、`run()` 返回根目录，先前的 `Could not determine the simulator from data dir` 消失；但整个 SSH 命令达到 170 秒服务端限时，交互式 Spectre 收尾仍有 `SPECTRE-25`，因此 v4 不算干净通过。
2. v5 在经典 Spectre 和根目录基础上，于 `simulator('spectre)` 前加入 `envSetVal("spectre.envOpts" "controlMode" 'string "batch")`。OCEAN 返回码 0，`run()` 报告根目录，Spectre 正常签出 `Virtuoso_Spectre` 并以 **0 errors、5 PDK warnings、4 notices** 完成，ADE 报成功，结果读取成功；`dcOp.dc`、`sp.sp`、`sp.noise.sp` 非空，运行后无 OCEAN/Spectre/Xvfb 遗留进程。唯一 OCEAN 侧警告来自现有 `.cdsinit` 的阻塞式表单初始化；未改用户配置。此项完成了 OA testbench 的 DC/SP-noise 仿真闭环，仍不是合格 LNA。
3. v6 仅再尝试 `saveOption(?simOutputFormat "psfascii")`，本机 ADE 明确报 `ADE-5012`：该选项不在支持列表。虽然子 Spectre 完成，OCEAN 返回失败；v6 不计入通过，也不把 PSFXL 文件冒充 PSFASCII。v5 的原始结果仍采用 PSFXL，直接 Spectre 的 PSFASCII 指标与 OCEAN 结果是不同运行，不能混写为一次仿真。

本机可用的最小 OCEAN 设置是：

```skill
envSetVal("spectre.turboOpts" "uniMode" 'string "Spectre")
envSetVal("spectre.envOpts" "controlMode" 'string "batch")
simulator('spectre)
resultsDir("<private-run-root>")
```

后续应通过 OCEAN `openResults`/`ocnPrint` 等经实机验证的接口导出 PSFXL 指标，或对同一生成网表进行**单独标注**的直接 Spectre PSFASCII 运行；不再次尝试已拒绝的 ADE `psfascii` 选项。当前 v5 仅证明现有共源测试平台可运行，输入匹配、正增益、压缩点和多候选优化仍待实现。

## v5 PSFXL 的 OCEAN 导出与独立校验

不重跑 Spectre，另用只读 OCEAN 脚本打开 v5 的 `psf/`：`results()` 包含 `dcOp`、`sp_noise`、`sp`，`outputs()` 可见 `/s11`、`/s21`、`/s22`、`/NF`、`/NFmin`、`/F`、`/Fmin`。`ocnPrint` 分别输出三个复数 S 参数的实部/虚部、NF/NFmin dB 与 F/Fmin 线性因子，DC 供电电流由 `getData("VDD:p")` 输出。脚本和原始导出保存在 Git 忽略的 `results/runs/lna_stage03/private_schematic_core/export_v5_psfxl*`；读取运行返回码 0。`ocnPrint` 本次默认只保留约六位有效数字，因此 Python 在导出文本间核对频率轴时允许相应的舍入误差，而不是要求与原始 PSFASCII 位对位相等。

新增 `src/orfadc/cadence/ocean_ascii.py` 和 `src/orfadc/experiments/extract_ocean_oa.py`，检查 10 条波形的频点数、递增频率轴、复数 S 参数、`10log10(F)=NF`、`10log10(Fmin)=NFmin`、DC 电源电流方向，以及 OCEAN/ADE 与 Spectre 0-error 完成日志。生成独立的 `ocean_v5_extracted_20260926_01/waveforms.csv` 和 `metrics.json`；`raw_format=ocean_ocnprint_from_psfxl`、`source_run_kind=oa_schematic_ocean_classic_batch`，与先前直接 Spectre PSFASCII 运行的来源明确区分。47 个频点上，和独立直接运行相比，频率最大相对差约 `3.65e-6`，S11/S21/S22 dB 最大逐点差分别约 `4.4e-6`、`1.0e-5`、`5.4e-6`，NF 最大差约 `5.0e-6` dB；供电电流约 `0.5807901 mA`。两条路径数值接近是交叉验证，**不是同一次运行，也不证明 LNA 性能**。v5 仍有 5 条 PDK `scalefactor` 警告。

运行入口：

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.extract_ocean_oa --export-dir <ignored-export-dir> --ocean-log <ignored-ocean-log> --spectre-log <ignored-spectre-log> --output-dir <new-ignored-dir> --run-id <run-id> --supply-voltage-v 1.1
```

本次完整 Python 测试套件后来增至 83 passed（含 NF dB 导出头校验）。此解析器只证明当前 OA 共源 smoke 的数据回收，`not_lna_result=true`、`spec_pass=null`；后续 v2 对照见 `docs/21_stage03_v2_candidate.md`，输入/输出匹配与合格 LNA 仍未完成。

下一步：基于已核对的 DC 工作区改进输入匹配与增益，建立有来源约束的新候选记录；当前仍无压缩点、规格通过或论文 N65 数值复现。私有 OA 库、受限网表、许可证记录和模型不进入仓库或外部 LLM 请求。Cadence 的 `schCheck`/`dbSave` 与 `design`/`createNetlist` 调用方式参见 [Cadence schematic 检查讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/25244/want-skill-to-check-and-save-schematic/1320595) 和 [Cadence OCEAN 网表讨论](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/17473/how-to-create-netlist-using-ocean-script)。
