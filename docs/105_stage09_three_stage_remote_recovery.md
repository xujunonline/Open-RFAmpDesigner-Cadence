# Stage 09：三级教学候选的远端身份与不重派恢复

## 要解决的故障

`docs/104_stage09_teaching_three_stage_candidate_feedback.md` 的两个候选虽有完整原始档，旧后端却使用随机远端目录且只在仿真后写候选上下文。如果控制端在 Spectre 执行后失去 SSH 回复，无法由本地 run ID 唯一定位原作业，也不能安全地让 Manager 自动重试。本轮只解决**公开 MOS1 三级教学候选**的这条证据/事务链，不扩张为授权 PDK LNA fullchain。

## 派发协议

新候选在远端操作之前独占创建本地运行目录，保存渲染后的网表、公开模型、候选快照、连接身份快照及 `dispatch_plan.json`。计划包含 spec/seed/candidate/run ID、唯一可计算的远端目录、输入哈希、原派发前宿主物理内存余量和 Spectre 超时。远端父目录可以复用，但**候选子目录用独占 `mkdir`**；已存在则拒绝上传/仿真。正常完成后下载原始 DC/SP/noise、工作点、Touchstone、日志和远端输入回读，逐项重算 161 点，再写指标和清单。协议 v3 归档还需由独立审计器重算计划字段与连接身份，旧 v2 成功档继续只读兼容。

若 Spectre 控制调用抛异常或返回 124/255，后端保存 `dispatch_uncertain.json`，不写正式 `metrics.json`/证据清单，`safe_to_retry=false`。确定性的后端错误另记 `evaluation_unverified.json`，不能冒充 SSH 回复不确定。远端身份用于**绑定同一配置**，不构成对本机有写权限攻击者的密码学认证；本地清单也是完整性证据，不是数字签名。

## 只读恢复

`recover_teaching_three_stage_candidate.py` 在本机独占锁下先重建候选/规格/参数和计划网表，核对当前 SSH 配置身份。它用只读 SSH 查询原远端目录有无活跃 Spectre，并对 8 项原始文件（网表、公开模型、日志、DC、OP、SP、noise、S2P）执行两次相隔 3 秒的哈希观察；符号链接、缺件、在途进程、变化的哈希或非干净终结日志均拒绝。下载到隔离目录后再核对逐文件哈希和远端第二次快照，重新运行原 PSFASCII/Touchstone/模型工作点审计。只有临时目录可独立审计通过，才逐文件无覆盖发布，**证据清单最后发布**；重入已完成归档只重审并返回 `already_recovered`。恢复器代码不调用 Spectre。

恢复结果为协议 v4：`spectre_returncode=null`，因为旧控制端未收到成功返回；但远端 `spectre.log` 的 0 errors/0 warnings 终结行、原始文件双次稳定哈希和下载后再审计独立证明该次远端计算完成。`recovery_provenance.json` 明记 `spectre_dispatched_by_recovery=false` 和 `controller_stdout_stderr_captured=false`；不会伪造控制端 stdout/stderr。原 `dispatch_uncertain.json` 保留。

若这次不确定派发发生在第二轮反馈，先恢复候选，再调用 `run_teaching_three_stage_refinement --finalize-trace`。finalizer 重新审计首轮与第二轮、候选计划、第二轮 v4 来源及其清单哈希，只读写 `recovery_ack.json` 和反馈摘要；保留原不确定标记，重复收尾只审计，不再派发。未恢复、来源变化、假确认或非 v4 第二轮一律保持未完成。

## 实际证据

- 首个身份计划 v2 正常档：`results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_dispatch_v2/20260927T183521Z_c14f4fad/`。参数 4.085532 nH，161 点及计划/清单重审通过；它没有后来新增的内存字段和独占远端子目录门禁。
- 新正常 v3 归档：`results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_exclusive_v3/20260927T184352Z_58c45fbb/`。6.0 nH，Spectre 161 点、独占远端目录、计划与清单均重审 `verified`。
- 第一次受控单候选丢回复：`results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_lostreply_v3/20260927T184116Z_0cb68043/`。5.0 nH，真正的 Spectre 返回 0 后仅在本机包装层隐藏该次成功回复，候选先 pending，随后从同一远端目录恢复为 v4；重复恢复返回 `already_recovered`。
- 完整第二轮故障链：首轮为 `docs/104` 的 2.0 nH 原始档；第二轮受控丢回复 trace 位于 `results/runs/teaching_three_stage_feedback_lost_reply/20260927T184753Z_14f1245f/20260927T184753Z_d4102dc4/`，对应 v4 候选 `S1/seed0/S1_seed0_teach3_resonance/20260927T184753Z_11f2efbe/`。候选原始恢复与反馈 finalizer 均重审通过，带内最差 S21 相对首轮提高约 2.887 dB。这里的包装层只隐藏成功回复，**不是运行中真实 SSH 物理断线**；它验证的是同一远端作业的恢复协议。
- 上述四个新运行均是公开 MOS1/理想耦合的直接 Spectre 教学网表，50 Ω 输入与 1787 Ω 差分输出的混合参考阻抗；这些候选没有 IP1dB、PDK 有损无源、DRC 或论文表格资格。5.0/6.0 nH 的 S1 最差 S21 分别约 2.002/1.997 dB，S22 分别约 -2.052/-1.738 dB，NF 均约 5.664 dB，仍失败。相近 S21 不构成优化收敛证明。

## 复核命令

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_teaching_three_stage results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_lostreply_v3/20260927T184116Z_0cb68043
python -m orfadc.experiments.recover_teaching_three_stage_candidate results/runs/teaching_three_stage_candidates/S1/seed0/S1_seed0_teach3_lostreply_v3/20260927T184116Z_0cb68043
python -m orfadc.experiments.run_teaching_three_stage_refinement --audit-trace results/runs/teaching_three_stage_feedback_lost_reply/20260927T184753Z_14f1245f/20260927T184753Z_d4102dc4
python -m pytest -q --basetemp="results/runs/pytest_teach3_recovery_$(Get-Date -Format yyyyMMddHHmmssfff)" tests/test_recover_teaching_three_stage_candidate.py tests/test_run_teaching_three_stage_refinement.py
```

不要对已完成候选再次运行派发命令。原始档、远端身份和本机连接配置保留在 Git 忽略目录，公开文档不携带商业模型或 SSH 凭据。当前恢复器只接管**干净完成的单个三级教学候选**；终态非零 Spectre 失败、截断原始结果、跨控制主机锁、端点认证及真正运行中断线后远端不完整的隔离仍需分别实现。后续三级 planned Manager/Searcher/Refiner 及其 pending 对账已单列 `docs/106_stage10_three_stage_planned_agent.md`；它仍不能替代合格 LNA 的物理与 fullchain 门禁，Stage 09/10/全项目继续 `partial`。
