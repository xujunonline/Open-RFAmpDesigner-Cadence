# S5 历史设计续调实验 · 2026-11-23

本次验证一个具体问题。给 Refiner 一份还有单项违规的 N65 设计，以及几种小改动的缓存模型预测，它能否选出在完整仿真中达标的修改？起点为 seed0 的 D017/C014。上轮的通过设计与验收标签均未输入模型。工程上预先选定 MCR2、MCR3 两个耦合参数，每次只允许改一个，相对变化为 ±3% 或 ±6%。这一范围来自上轮经验。实验使用项目 v2 共用的 ReAct 决策循环、原 S5 判据和 Spectre 后端，使用专门的局部 Refiner 入口。从零开始的三角色搜索是另一项实验，见文档 145。

| 实测步骤 | 最低增益，dB | 纹波，dB | 中心 NF，dB | 全带最差 S11，dB | IP1dB，dBm | 电流，mA |
|---|---:|---:|---:|---:|---:|---:|
| 复测历史起点 | 21.8976 | 2.4654 | 4.9131 | −10.9956 | −16.7318 | 25.7217 |
| 模型选择 MCR2 k 减小 3% | 22.1844 | 2.7881 | 4.8680 | −10.9925 | −17.0863 | 25.7217 |
| 同一设置再次运行 Spectre | 22.1844 | 2.7881 | 4.8680 | −10.9925 | −17.0863 | 25.7217 |

模型调用 `evaluate` 选择 `mcr2_-3pct`，耦合系数从 0.7333793070 降到 0.7113779278。谷底提高 0.2868 dB，峰值提高 0.6095 dB，纹波因而增加 0.3227 dB，距离上限仍有 0.2119 dB。若目标同时要求比原方案纹波更小，上轮 MCR3 +3% 的方案更符合偏好。本轮两次通过均为相同标称条件下的原理图级仿真。NF 判据取中心频率，本方案最大带内 NF 为 6.6836 dB。

运行耗时 20.545 秒。真实设计 LLM 1 次，模型 gpt-6.2-sol，错误、重试和回退均为 0。真实 Spectre 3 次，均成功。批次累计 Spectre 47/63（S2 3/3、S5 44/60），剩 16 次。累计成功设计 LLM 185/1000。

完整动作、各候选预测、设计参数及曲线在 `results/windows_checks/s5_resume_trial_01/summary.json`。原始 Spectre 文件在 `results/runs/repro_cadence_pdk/20261123T235214_a53842/sim00001` 至 `sim00003`。更换新输出目录可复跑；运行前从累计账本核对剩余额度。

```bash
cd /Users/jason/Documents/Open-RFAmpDesigner-Cadence
ORFADC_CODEX_BIN='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex' \
ORFADC_CODEX_MODEL=gpt-6.2-sol ORFADC_V2_WALL_SECONDS=300 ORFADC_LLM_MAX_CALLS=8 \
ORFADC_SPECTRE_MAX_PER_DESIGN=6 PYTHONPATH=src .venv/bin/python -u scripts/run_s5_live.py \
  --resume-from results/windows_checks/20261123T143737_job/design_S5_seed0_mode1_codex-mcp_pdk_n65_v2_s11bt_calls1000_smax60.json \
  --out results/windows_checks/s5_resume_trial_02
```
