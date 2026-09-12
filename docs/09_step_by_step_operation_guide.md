# Open-RFAmpDesigner-Cadence 步进式操作指导书

> 目标读者：已经完成过 Cadence/OCEAN/Python 自动扫 OTA 的大二微电子学生。  
> 执行原则：先跑通最小闭环，再逐步加 RF 指标、LNA 拓扑、工具中间件、多智能体、KB/EB 和论文级近似复现。  
> 严格边界：不提交商业 PDK、PCell、模型路径、原始 Spectre netlist、foundry rule deck；不声称严格复现论文 TSMC N65 数值。

## 0. 总体路线图

本项目不要一开始就做三阶段 30 GHz/50 GHz 宽带 LNA。正确顺序是：

1. 本地 Python 骨架检查。
2. 复用你 OTA 项目的远程 OCEAN 调用能力。
3. 建一个最小 RF testbench，先跑 S 参数。
4. 加 noise 仿真，提取 NF/NFmin。
5. 加输入匹配网络，做单级 LNA MVP。
6. 生成 active lookup table。
7. 实现 Stage 2 impedance matching。
8. 实现 Stage 3 band planning 的低保真模型。
9. 连接 fullchain evaluation。
10. 实现 Manager/Searcher/Refiner 确定性版本。
11. 接入 LLM JSON 决策。
12. 做 Table IV/V/VI-like 和 Fig. 7-11-like 输出。

每一步都有明确的输入、操作、输出、验收标准和下一步提示词。

## 1. 阶段 1：本地工程骨架检查

### 1.1 目标

确认当前项目在没有 Cadence 的 Windows 本地也能运行 Python 基础逻辑：

- YAML 规格能读取；
- cost function 能测试；
- dry-run candidate 能生成；
- 运行产物不会污染源码目录。

### 1.2 操作

在 PowerShell 中进入项目根目录：

```powershell
cd F:\Open-RFAmpDesigner-Cadence
```

编译 Python 源码：

```powershell
python -m compileall src
```

运行单规格 dry-run：

```powershell
python src\orfadc\experiments\run_spec.py --spec S1 --dry-run
```

运行测试：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest tests -q
```

### 1.3 验收标准

- `compileall` 无语法错误。
- `pytest` 显示 `2 passed` 或更多测试通过。
- `results/runs/S1/seed0/dry_run_candidates.json` 能生成。
- 该 dry-run 文件只表示候选结构生成成功，不代表任何 Cadence 仿真通过。

### 1.4 常见问题

- `No module named orfadc`：确认当前目录是项目根目录，并设置 `PYTHONPATH` 指向 `$PWD\src`。
- `No module named yaml`：安装或切换到带 PyYAML 的 Python；也可以先让 Codex 改成 JSON fallback。
- `pytest` 警告 Python 3.13 deprecation：通常是 pytest 自身警告，不影响项目逻辑。

## 2. 阶段 2：整理你的 OTA 自动化工程资产

### 2.1 目标

把你之前“折叠共源共栅全差分 OTA 自动扫参”的可复用能力拆出来，形成 RF 项目可迁移清单。

### 2.2 你需要整理的内容

从旧项目找出：

- SSH 连接 Linux VM 的 Python 代码；
- 远程执行 OCEAN/Spectre 的代码；
- 上传/下载文件的代码；
- OCEAN 脚本模板；
- PSFASCII 解析代码；
- 参数扫描循环；
- 结果 CSV/JSON 保存逻辑；
- 最优候选排序逻辑；
- 日志目录组织方式。

### 2.3 建议输出文件

在本项目中新增或整理：

```text
Open-RFAmpDesigner-Cadence/
├─ docs/
│  └─ ota_to_lna_migration_notes.md
├─ config/
│  └─ remote_cadence.local.example.yaml
└─ src/orfadc/cadence/
   ├─ remote_runner.py
   └─ psfascii_reader.py
```

注意：真实账号、IP、密码、PDK 路径必须放在本地 private 文件，不提交。

### 2.4 验收标准

- 能解释 OTA 旧工程中哪些代码可以直接复用，哪些必须改。
- 能用一个 Python 函数远程执行 `hostname` 或 `pwd`。
- 能从远程下载一个文本日志到本地 `results/logs/`。

## 3. 阶段 3：Cadence RF 环境准备

### 3.1 目标

确认 Linux/Cadence 环境能运行 RF 仿真，而不仅是 OTA 的 AC/DC 仿真。

### 3.2 检查项

在 Linux VM 或服务器中检查：

```bash
which virtuoso
which ocean
which spectre
echo $CDS_LIC_FILE
echo $CDS_Netlisting_Mode
```

确认项目工作目录：

```bash
mkdir -p ~/Open-RFAmpDesigner-Cadence-runs
```

确认 Cadence library 映射：

- `cds.lib` 能 include PDK；
- 能新建自己的 library；
- 能打开 Virtuoso；
- 能用 ADE 或 OCEAN 跑一次已有 OTA testbench。

### 3.3 PDK 路线选择

路线 A：实验室授权商业 PDK。

- 优点：最接近真实 RFIC 设计。
- 缺点：不可公开 PDK/netlist/log 中敏感信息。
- 适合：后续课程设计/科研训练的真实 Cadence 实验。

路线 B：Cadence + 教学/简化 MOS/RLC。

- 优点：无 PDK 泄露风险，适合先调通工具流。
- 缺点：不能报告为真实工艺结果。
- 适合：MVP 和代码调试。

### 3.4 验收标准

- 可以从命令行运行 `ocean -nograph -restore <script.ocn>`。
- 可以导出一个 CSV 或 PSFASCII。
- 本地 Python 能拿到远程仿真结果。

## 4. 阶段 4：建立最小 RF S 参数 testbench

### 4.1 目标

先不做完整 LNA，只做一个可仿真的 RF 放大级，证明你能提取 S11/S21/S22。

### 4.2 Virtuoso 操作

1. 新建 library：`orfadc_lna_lib`。
2. 新建 cell：`cs_rf_amp_mvp`。
3. 放一个 NMOS 共源级或共源共栅级。
4. 加偏置电流源或偏置电压源。
5. 输入端使用 port，参考阻抗 50 ohm。
6. 输出端使用 port 或 50 ohm 负载。
7. 暴露变量：

```text
w_main
l_main
vgs_bias
id_bias
ld
ls
lg
cd
```

8. Check and Save。

### 4.3 ADE/OCEAN 仿真设置

先在 ADE 中手工跑通：

- analysis：`sp`
- start：例如 `100M`
- stop：例如 `10G` 或根据 PDK 能力选择
- ports：输入输出 50 ohm
- outputs：S11、S21、S22

再把 ADE 设置导出或手写 OCEAN。

### 4.4 Python 指标提取

导出的 CSV 推荐字段：

```csv
freq_ghz,s11_db,s21_db,s22_db
```

Python 计算：

```text
s11_worst = max(s11_db in band)
s21_min = min(s21_db in band)
s22_worst = max(s22_db in band)
ripple = max(s21_db in band) - min(s21_db in band)
```

### 4.5 验收标准

- 能画出 S11/S21/S22 曲线。
- 能自动生成 `metrics.json`。
- 能判断 S11 是否小于 -10 dB 或 -20 dB。

## 5. 阶段 5：加入 noise 仿真

### 5.1 目标

在同一个 RF 放大级上提取 NF 和 NFmin。

### 5.2 Cadence 操作

在 ADE 中添加 noise 或 sp-noise 分析。常见设置：

- 输入源：port 或 RF source；
- 输出节点：输出端口或输出节点；
- 频率 sweep 与 S 参数一致；
- 温度设置与项目默认一致。

### 5.3 输出字段

推荐 CSV：

```csv
freq_ghz,nf_db,nfmin_db
```

### 5.4 Python 提取

```text
nf_worst = max(nf_db in band)
nf_center = value nearest fc
nfmin_center = value nearest fc
```

### 5.5 验收标准

- NF 曲线不是空值；
- NF 数值没有明显不合理，例如负很多 dB；
- 能写入 `metrics.json`；
- 能用 `stage2_cost()` 计算 NF violation。

## 6. 阶段 6：单级 LNA MVP

### 6.1 目标

从“能跑 RF 仿真”升级到“能自动优化一个简单 LNA”。

### 6.2 建议变量

先用少量变量：

```yaml
design_variables:
  w_main_um: [20, 40, 60, 80, 100]
  vgs_mv: [350, 400, 450, 500]
  ls_ph: [0, 50, 100, 150]
  lg_ph: [100, 300, 500, 700, 900]
```

### 6.3 Cost function

MVP 不要一开始就追论文 S1-S10。先定义你自己的低频/中频教学 spec：

```yaml
spec_id: MVP_RF1
fc_ghz: 1.0
fbw_ratio: 0.2
gain_min_db: 10
s11_max_db: -10
nf_max_db: 5
power_max_ma: 5
```

Cost：

```text
cost = 1000*max(0, s11_worst - s11_max)
     + 1000*max(0, gain_min - s21_min)
     + 1000*max(0, nf_worst - nf_max)
     + 100*max(0, power_ma - power_max)
```

### 6.4 扫描流程

1. Python 生成候选参数。
2. 写入 OCEAN 参数文件或命令行变量。
3. 运行 OCEAN。
4. 导出 S 参数和 NF CSV。
5. 解析指标。
6. 计算 cost。
7. 保存 candidate。
8. 按 cost 排序。

### 6.5 验收标准

- 至少自动跑 20 个候选；
- 每个候选有独立目录；
- 每个候选有 `metrics.json`；
- 能选出当前最优候选；
- 能画最优候选曲线。

## 7. 阶段 7：生成 active lookup table

### 7.1 目标

复现论文 Stage 1 的思想：不要每次让 agent 直接猜 W/VGS，而是先建立工艺相关 lookup table。

### 7.2 扫描内容

对单级/差分级/cascode 级分别扫描：

```yaml
width_um: [45, 54, 63, 72, 81, 90, 99, 108, 117]
vgs_mv: [300, 325, 350, 375, 400, 425, 450, 475, 500]
```

如果你用 TSMC40，范围应根据器件可靠性和 PDK 推荐工作区调整，不照抄论文 N65 数值。

### 7.3 输出字段

```csv
topology,width_um,vgs_mv,current_ma,gm_ms,gds_ms,cgs_ff,cgd_ff,zin_real,zin_imag,zout_real,zout_imag,nf_est_db
```

### 7.4 验收标准

- lookup CSV 可由 Python 读取；
- `active_sizing()` 能按目标电流找到最近候选；
- 不提交含 PDK 路径或敏感模型名的原始仿真日志。

## 8. 阶段 8：实现 Stage 2 阻抗匹配

### 8.1 目标

实现论文的关键工具：给定有源候选，优化输入匹配和关键级被动参数，使 NF 和 S11 满足约束。

### 8.2 变量

来自 Table II Stage 2：

```yaml
k: [0.1, 0.7]
l1_ph: [100, 1000]
l2_ph: [100, 1000]
r1_ohm: [100, 1000]
r2_ohm: [100, 1000]
c1_ff: [0, 50]
c2_ff: [0, 50]
ls_ph: [0, 150]
```

### 8.3 操作顺序

1. 先不用 PSO，手写 20-50 个随机候选。
2. 对每个候选跑 `run_sparam.ocn` 和 `run_noise.ocn`。
3. 用公式 (1) 计算 cost。
4. 确认 cost 排序合理。
5. 再接入 PSO。

### 8.4 验收标准

- 能自动找到比初始匹配更好的 S11 或 NF。
- `impedance_matching.py` 不再只是占位，而能返回真实 `sim_result_cpstages`。
- 所有结果来自 Cadence 仿真或明确标注 fallback。

## 9. 阶段 9：实现 Stage 3 带宽规划

### 9.1 目标

先实现 MCR/RLC 的低保真频率响应计算，再连接少量 Cadence 仿真校准。

### 9.2 最小实现

先不用完整 MCR 公式，先用二阶 RLC 谐振峰近似：

```text
H_i(f) = gain_i / sqrt(1 + Q_i^2 * (f/f0_i - f0_i/f)^2)
H_total_dB = sum(20 log10 |H_i|)
```

之后再替换成论文公式 (3) 的 `Y11(s), Z21(s), I11(s), V(s)`。

### 9.3 验收标准

- 输入目标中心频率和带宽，能生成多个交错峰位；
- 能计算通带 `gain_min` 和 `ripple`；
- `stage3_cost()` 能用于排序；
- 后续可用 Cadence 仿真残差校准。

## 10. 阶段 10：Fullchain evaluation

### 10.1 目标

把 Stage 1/2/3 的候选合并成完整电路参数，调用完整 testbench。

### 10.2 输出目录

每个候选必须保存：

```text
results/runs/<spec>/<seed>/<candidate>/
├─ params.yaml
├─ netlist.scs              # 如果含 PDK 敏感信息，公开仓库不提交
├─ ocean.log
├─ spectre.log
├─ sparams.csv
├─ noise.csv
├─ compression.csv
├─ metrics.json
├─ waveforms.csv
└─ agent_trace.json
```

### 10.3 验收标准

- 一个函数 `fullchain_eval(candidate)` 能跑完整流程；
- `metrics.json` 包含 S11/S21/S22/NF/NFmin/IP1dB/power/ripple；
- 失败也有结构化 failure reason。

## 11. 阶段 11：确定性 Manager/Searcher/Refiner

### 11.1 目标

先不用 LLM，用确定性规则跑通多智能体状态机。

### 11.2 Manager 规则

- 队列为空：调用 Searcher。
- 队列有候选：取优先级最高候选给 Refiner。
- 有 pass 候选：Stop。
- 达到预算：Stop with failure report。

### 11.3 Searcher 规则

固定尝试：

```yaml
power_ratio_options:
  - [0.4, 0.3, 0.3]
  - [0.5, 0.25, 0.25]
  - [0.35, 0.35, 0.30]
```

### 11.4 Refiner 规则

- NF fail：增加 NF headroom。
- S11 fail：重新 Stage 2。
- gain/ripple fail：重新 Stage 3。
- IP1dB fail：降低前级增益或增加后级电流。
- power fail：缩小非关键级。

### 11.5 验收标准

- `agent_trace.json` 记录每一步 action；
- 即使不接 LLM，也能完整 search/refine/stop；
- 失败报告能告诉下一步该改哪个阶段。

## 12. 阶段 12：接入 LLM agent

### 12.1 目标

让 LLM 只做策略决策，不直接写 netlist，不直接接触 PDK。

### 12.2 输出要求

所有 agent 必须 JSON-only：

```json
{
  "thought_summary": "short engineering rationale",
  "action": "RefineCandidate",
  "arguments": {
    "candidate_id": "S1_seed0_cand0001",
    "refine_target": "stage2",
    "nf_headroom_db": 0.4
  },
  "risk_note": "method-level reproduction only"
}
```

### 12.3 验收标准

- JSON 能解析；
- 无自由文本 netlist；
- 每次 LLM 决策都有仿真 observation；
- token 统计写入 experiment summary。

## 13. 阶段 13：表格和图生成

### 13.1 Table-like

- `table_iii_specs.csv`：由 YAML 直接导出。
- `table_iv_like.csv`：S1-S8 不同方法 pass@1 和 Avg Time。
- `table_v_like.csv`：S9/S10 难任务结果和 token。
- `table_vi_like.csv`：effective latency 和 cost。

### 13.2 Fig-like

- Fig. 7-like：S 参数、NF、压缩曲线。
- Fig. 8-like：平均完成时间。
- Fig. 9-like：search/refine 次数。
- Fig. 10-like：simulation cost/sample efficiency。
- Fig. 11-like：FoM evolution。

### 13.3 验收标准

- 图表脚本从 `results/` 读取数据；
- 图标题必须写 `like` 或 `本工程结果`；
- 报告中不声称复现原始曲线。

## 14. 阶段 14：论文级近似复现

### 14.1 目标

在你已经跑通 MVP、多级、agent 后，再尝试接近论文 Table III 的 10 个 specs。

### 14.2 顺序

1. 先 S1：低频、20% BW、普通 NF/linearity。
2. 再 S2：30 GHz。
3. 再 S4：30 GHz、10% BW。
4. 再 S5/S6：宽带。
5. 再 S7：低 NF。
6. 再 S8：低功耗。
7. 最后 S9/S10：高线性度和低 NF 组合。

### 14.3 验收标准

- 每个 spec 至少 5 seeds。
- 每个 seed 有独立 run directory。
- 成功率按 pass@1 报告。
- 明确标注使用的 PDK/模型路线。

## 15. 每周执行计划

### 第 1 周

- 完成本地 Python 检查。
- 整理 OTA 旧工程迁移清单。
- 远程执行器最小验证。

### 第 2 周

- 建 RF S 参数 testbench。
- 自动导出 S11/S21/S22。
- Python 解析曲线和 metrics。

### 第 3 周

- 加 noise。
- 做单级 LNA MVP。
- 自动扫 20-100 个候选。

### 第 4 周

- 生成 active lookup table。
- 实现 Stage 2 随机/PSO 匹配。

### 第 5 周

- 实现 Stage 3 低保真 band planning。
- 接 fullchain evaluation。

### 第 6 周

- 实现确定性 Manager/Searcher/Refiner。
- 保存 KB/EB JSONL。

### 第 7 周

- 接 LLM JSON 决策。
- 做消融实验。

### 第 8 周

- 生成 Table/Fig-like。
- 写课程设计/科研训练报告。

## 16. 你每次开始新任务前要给 Codex 的上下文

每次都明确三件事：

1. 当前阶段；
2. 已经完成的验收结果；
3. 这次只允许改哪些文件。

示例：

```text
当前在 Open-RFAmpDesigner-Cadence 阶段 4：建立最小 RF S 参数 testbench。
已完成：Python dry-run 和 pytest；Cadence 可以运行 OCEAN；已有 OTA 项目的 SSH 调用代码。
本次目标：设计 run_sparam.ocn 模板和 Python CSV 解析流程。请不要接 LLM，不要虚构 PDK 路径，不要生成商业 netlist。
```
